import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import get_settings
from src.core.scanner import Scanner
from src.core.realtime_scanner import RealtimeScanner
from src.core.lifecycle import LifecycleManager
from src.notification.feishu import FeishuClient
from src.utils.logging import setup_logging

_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    _shutdown = True
    print("\nShutdown signal received")


async def run_realtime(settings):
    import asyncio, threading
    from src.data.exchange import OKXAdapter
    from src.core.position_monitor import PositionMonitor
    from src.data.history_db import HistoryDB, HistoryManager
    from src.data.price_cache import PriceCache
    hist_db = HistoryDB("data/history.db")
    hist_db.init_schema()
    hist_manager = HistoryManager(hist_db, default_lookback=90)
    price_cache = PriceCache(max_age_seconds=60)
    scanner = RealtimeScanner(settings.model_dump(), history_manager=hist_manager, price_cache=price_cache)
    adapter = OKXAdapter()
    symbols = adapter.get_symbol_list(settings.data.top_n)

    from src.utils.health import HealthChecker
    from src.core.signal_store import get_signal_store
    hc = HealthChecker()
    hc.register("scanner", lambda: get_signal_store().last_scan() is not None)
    hc.register("positions", lambda: True)
    hc.register("signals", lambda: len(get_signal_store().get_all()) > 0)

    def run_http():
        import http.server, json, socketserver
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == settings.health.endpoint:
                    st = hc.check()
                    self.send_response(200 if st.healthy else 503)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "healthy": st.healthy,
                        "components": {k: v.get("healthy", False) for k, v in st.components.items()},
                        "last_scan": str(get_signal_store().last_scan())[:19],
                        "signal_count": len(get_signal_store().get_all()),
                    }, default=str).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            def log_message(self, format, *args): pass
        with socketserver.TCPServer(("", settings.health.port), H) as httpd:
            httpd.serve_forever()

    if settings.health.enabled:
        t = threading.Thread(target=run_http, daemon=True)
        t.start()

    # 启动历史数据后台下载（不阻塞主监控）
    def start_history_background():
        import asyncio
        from src.data.history_db import HistoryDB
        from src.data.history_downloader import HistoryDownloader, HistoryStatsComputer
        from loguru import logger

        db = HistoryDB("data/history.db")
        db.init_schema()

        history_cfg = settings.data.history
        lookback_days = history_cfg.get("lookback_days", [90, 180, 365])
        downloader = HistoryDownloader(
            db=db,
            config=settings.model_dump(),
            batch_size=history_cfg.get("download_batch_size", 50),
            download_interval=history_cfg.get("download_interval_seconds", 60),
        )
        downloader.set_symbols(symbols, settings.data.timeframes)

        computer = HistoryStatsComputer(db=db, config=settings.model_dump())

        async def history_loop():
            logger.info(f"[History] 开始下载历史数据: {lookback_days} 天")
            await downloader.full_sync(days_list=lookback_days)
            logger.info("[History] 开始计算统计数据...")
            computer.compute_for_all_symbols(symbols, settings.data.timeframes, days_list=lookback_days)
            logger.info("[History] 历史数据流程完成")

        asyncio.run(history_loop())

    t_hist = threading.Thread(target=start_history_background, daemon=True, name="HistoryDownload")
    t_hist.start()

    await scanner.start_and_wait_first_scan(symbols)
    pos_monitor = PositionMonitor(settings.model_dump())
    pos_monitor.start()
    await scanner.wait_until_shutdown()


def run_batch(settings):
    scanner = Scanner(settings.model_dump())
    scanner.run()


def main():
    global _shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    settings = get_settings()
    setup_logging(
        level=settings.logging.level,
        log_file=settings.logging.file,
        console=settings.logging.console,
    )

    lifecycle = LifecycleManager(settings.model_dump())
    lifecycle.on_start()

    use_websocket = settings.data.websocket.get("enabled", False)

    try:
        if use_websocket:
            import asyncio
            asyncio.run(run_realtime(settings))
        else:
            run_batch(settings)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        lifecycle.on_error(e)
        raise
    finally:
        lifecycle.on_stop()


if __name__ == "__main__":
    main()
