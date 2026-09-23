"""單一應用程式程序使用的持久工作佇列。所有外部事件先保存再確認。"""
import json
import sqlite3
import time
from contextlib import contextmanager
from uuid import uuid4


class Store:
    def __init__(self, root):
        self.path = root / "stock-bot.sqlite3"
        with self.db() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, event TEXT UNIQUE, platform TEXT, session TEXT, target TEXT,
                text TEXT, status TEXT, result TEXT DEFAULT '', error TEXT DEFAULT '',
                created REAL, updated REAL, sent INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, session TEXT, role TEXT, content TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created);
            CREATE INDEX IF NOT EXISTS message_session ON messages(session, id);
            """)
            # 舊資料庫補上進度欄位，供前端顯示目前呼叫的工具。
            if 'progress' not in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN progress TEXT DEFAULT ''")

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET status='interrupted', error='程式中止，請重新提問。' WHERE status='running'")
            db.execute("UPDATE jobs SET status='uncertain', error='傳送時程式中止，請先確認聊天紀錄。' WHERE status='sending'")

    def enqueue(self, platform, session, target, text, event=None):
        text = text.strip()
        if not text or len(text) > 4000:
            raise ValueError("請輸入 1 至 4000 字的問題。")
        now, jid = time.time(), uuid4().hex
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if event:
                existing = db.execute("SELECT id FROM jobs WHERE event=?", (event,)).fetchone()
                if existing:
                    return existing[0], False
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','sending')").fetchone()[0] >= 100:
                raise ValueError("工作佇列已滿，請稍後再試。")
            db.execute("INSERT INTO jobs(id,event,platform,session,target,text,status,created,updated) VALUES(?,?,?,?,?,?,'queued',?,?)",
                       (jid, event, platform, session, target, text, now, now))
        return jid, True

    def claim(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM jobs j WHERE status='queued' AND NOT EXISTS
                (SELECT 1 FROM jobs r WHERE r.session=j.session AND r.status IN ('running','sending'))
                ORDER BY created LIMIT 1""").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row['id']))
                return dict(row)

    def update(self, jid, **fields):
        if not set(fields) <= {'status', 'result', 'error', 'sent', 'progress'}:
            raise ValueError("不支援的工作欄位")
        fields['updated'] = time.time()
        with self.db() as db:
            db.execute("UPDATE jobs SET " + ','.join(f'{k}=?' for k in fields) + " WHERE id=?", (*fields.values(), jid))

    def jobs(self, limit=100):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def history(self, session, turns=None):
        with self.db() as db:
            rows = db.execute("SELECT role,content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
                              (session, -1 if turns is None else turns * 2)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def remember(self, session, question, answer):
        with self.db() as db:
            db.executemany("INSERT INTO messages(session,role,content,created) VALUES(?,?,?,?)",
                           [(session, 'user', question, time.time()), (session, 'assistant', answer, time.time())])

    def reset(self, session):
        with self.db() as db:
            db.execute("DELETE FROM messages WHERE session=?", (session,))

    def meta(self, key, value=None):
        with self.db() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value)))
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def purge(self, days=0):
        cutoff = time.time() - days * 86400
        with self.db() as db:
            db.execute("DELETE FROM messages WHERE created<?", (cutoff,))
            db.execute("DELETE FROM jobs WHERE updated<? AND status NOT IN ('queued','running','sending')", (cutoff,))
