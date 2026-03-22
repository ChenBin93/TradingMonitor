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
    scanner = RealtimeScanner(settings.model_dump())
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
