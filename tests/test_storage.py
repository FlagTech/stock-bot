from stock_bot.storage import Store


def test_deduplication_and_session_order(tmp_path):
    store = Store(tmp_path)
    first, fresh = store.enqueue('line', 'user1', '1', 'one', 'evt1')
    assert fresh
    assert store.enqueue('line', 'user1', '1', 'one', 'evt1') == (first, False)
    second, _ = store.enqueue('line', 'user1', '1', 'two', 'evt2')
    third, _ = store.enqueue('line', 'user2', '2', 'three', 'evt3')
    assert store.claim()['id'] == first
    assert store.claim()['id'] == third
    assert store.claim() is None
    store.update(first, status='done')
    assert store.claim()['id'] == second


def test_restart_never_blindly_resends(tmp_path):
    store = Store(tmp_path)
    a, _ = store.enqueue('line', 'a', 'a', 'hello')
    b, _ = store.enqueue('line', 'b', 'b', 'hello')
    store.update(a, status='running')
    store.update(b, status='sending')
    Store(tmp_path).recover()
    assert {j['status'] for j in store.jobs()} == {'interrupted', 'uncertain'}


def test_conversation_isolation_and_reset(tmp_path):
    store = Store(tmp_path)
    store.remember('line:a', 'question A', 'answer A')
    store.remember('telegram:a', 'question B', 'answer B')
    assert store.history('line:a', 5)[0]['content'] == 'question A'
    store.reset('line:a')
    assert not store.history('line:a', 5)
    assert len(store.history('telegram:a', 5)) == 2


def test_purge_keeps_in_flight(tmp_path):
    store = Store(tmp_path)
    jid, _ = store.enqueue('local', 'local', '', 'question')
    store.remember('local', 'q', 'a')
    store.purge()
    assert store.jobs()[0]['id'] == jid
    assert store.history('local', 5) == []


def test_job_progress_column_is_added_to_old_database(tmp_path):
    import sqlite3
    from stock_bot.storage import Store
    with sqlite3.connect(tmp_path / 'stock-bot.sqlite3') as db:
        db.execute("""CREATE TABLE jobs (id TEXT PRIMARY KEY, event TEXT UNIQUE, platform TEXT, session TEXT, target TEXT,
            text TEXT, status TEXT, result TEXT DEFAULT '', error TEXT DEFAULT '', created REAL, updated REAL, sent INTEGER DEFAULT 0)""")
    store = Store(tmp_path)
    jid, _ = store.enqueue('local', 's', '', '台積電')
    store.update(jid, progress='正在呼叫 股價查詢 工具')
    assert store.jobs()[0]['progress'] == '正在呼叫 股價查詢 工具'
