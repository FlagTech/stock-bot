"""可被終止的資料查詢子程序。stdin/stdout 僅傳 JSON，避免失控查詢耗盡工作執行緒。"""
import asyncio
import json
import os
import sys
from pathlib import Path


class IsolatedMarket:
    def __init__(self, root):
        self.root = root

    async def call(self, name, args):
        from .config import ENV
        env = {k: v for k, v in os.environ.items() if k not in ENV.values()}
        env['PYTHONIOENCODING'] = 'utf-8'
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'stock_bot.tool_worker', str(self.root),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env=env, **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
        try:
            async with asyncio.timeout(70):
                output, _ = await process.communicate(json.dumps({'name': name, 'args': args}).encode('utf-8'))
            if process.returncode:
                raise ValueError('資料查詢失敗。')
            return json.loads(output)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


def main():
    import contextlib
    from filelock import FileLock
    from .ai import TOOLS
    from .analysis_settings import AnalysisSettings
    from .market import Market
    root = Path(sys.argv[1])
    payload = json.loads(sys.stdin.read())
    analysis = AnalysisSettings.model_validate(payload['args'].pop('analysis', {}))
    schema, _ = TOOLS[payload['name']]
    args = schema.model_validate(payload['args']).model_dump(exclude_unset=True)
    # 隔離不同工作更新股名快取；逾時時鎖會隨程序結束釋放。
    with FileLock(root / 'market.lock', timeout=60), contextlib.redirect_stdout(sys.stderr):
        result = Market(root, analysis).call(payload['name'], args)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
