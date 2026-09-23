def main():
    import argparse
    import asyncio
    import logging
    import signal
    import socket
    import webbrowser

    import uvicorn
    from filelock import FileLock, Timeout

    from .api import make_admin, make_webhook
    from .config import Config
    from .runtime import Runtime

    parser = argparse.ArgumentParser(description='Stock Bot 本機雙平台股票分析機器人')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--webhook-port', type=int, default=8768)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.port == args.webhook_port or not all(1024 <= p <= 65535 for p in (args.port, args.webhook_port)):
        parser.error('兩個連接埠必須不同，且介於 1024 至 65535。')
    # URL 可能含 Telegram token，禁止 HTTP 函式庫輸出請求日誌。
    for name in ('httpx', 'httpcore', 'openai', 'pyngrok'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    config = Config()
    lock = FileLock(config.root / 'app.lock', timeout=0)

    async def serve():
        runtime = Runtime(config, args.webhook_port)
        servers = [uvicorn.Server(uvicorn.Config(make_admin(runtime, args.port), host='127.0.0.1', port=args.port, access_log=False)),
                   uvicorn.Server(uvicorn.Config(make_webhook(runtime), host='127.0.0.1', port=args.webhook_port, access_log=False))]
        # 由程式統一處理 Ctrl+C，等兩個 server 都關閉完才結束。若交給 uvicorn，
        # 先關完的 server 會重新觸發中斷，取消仍在關閉的另一個，並印出 CancelledError。
        from contextlib import nullcontext
        def handle_exit(sig, frame):
            for server in servers:
                server.force_exit = server.should_exit  # 再按一次 Ctrl+C 則強制結束
                server.should_exit = True
        for server in servers:
            server.capture_signals = nullcontext
        async def browser():
            while not servers[0].started:
                await asyncio.sleep(.1)
            print(f'控制台：http://127.0.0.1:{args.port}；請保持視窗開啟，Ctrl+C 結束。')
            if not args.no_browser:
                webbrowser.open(f'http://127.0.0.1:{args.port}')
        async def shutdown_peer():
            while not servers[0].should_exit and not servers[1].should_exit:
                await asyncio.sleep(.2)
            for server in servers:
                server.should_exit = True
        signals = [s for s in (signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGBREAK', None)) if s]
        previous = {s: signal.signal(s, handle_exit) for s in signals}
        try:
            await asyncio.gather(*(s.serve() for s in servers), browser(), shutdown_peer())
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    try:
        with lock:
            for port in (args.port, args.webhook_port):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', port))
            asyncio.run(serve())
    except Timeout:
        parser.exit(1, 'Stock Bot 已在執行，請開啟原本的控制台。\n')
    except OSError:
        parser.exit(1, '連接埠已被使用，請關閉舊程序或用 --port / --webhook-port 指定其他連接埠。\n')
    except KeyboardInterrupt:
        pass
