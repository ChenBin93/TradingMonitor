import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from loguru import logger


@dataclass
class KlineData:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ws_data(cls, symbol: str, timeframe: str, data: list) -> "KlineData":
        ts = int(data[0])
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=datetime.fromtimestamp(ts / 1000),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5]),
        )


class WebSocketManager:
    def __init__(
        self,
        url: str,
        on_kline: Callable[[KlineData], None] | None = None,
        on_trade: Callable[[str, float, float, datetime], None] | None = None,
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        reconnect_delay: int = 5,
        max_reconnect: int = 10,
        ping_interval: int = 30,
    ):
        self.url = url
        self.on_kline = on_kline
        self.on_trade = on_trade
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect = max_reconnect
        self.ping_interval = ping_interval

        self._ws: Optional[Any] = None
        self._running = False
        self._reconnect_count = 0
        self._subscriptions: set[tuple[str, str]] = set()
        self._pending_subscriptions: list[tuple[str, str]] = []
        self._trade_subscriptions: set[str] = set()
        self._pending_trade_subscriptions: list[str] = []
        self._lock = threading.RLock()

    async def connect(self):
        import websockets
        self._ws = await websockets.connect(self.url, ping_interval=self.ping_interval)
        self._running = True
        asyncio.create_task(self._read_loop())
        asyncio.create_task(self._resubscribe_loop())
        logger.info(f"WebSocket connected to {self.url}")

    async def close(self):
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket closed")

    def subscribe(self, symbol: str, timeframe: str):
        with self._lock:
            self._subscriptions.add((symbol, timeframe))
            self._pending_subscriptions.append((symbol, timeframe))

    def unsubscribe(self, symbol: str, timeframe: str):
        with self._lock:
            self._subscriptions.discard((symbol, timeframe))

    def subscribe_trades(self, symbol: str):
        with self._lock:
            self._trade_subscriptions.add(symbol)
            if symbol not in self._pending_trade_subscriptions:
                self._pending_trade_subscriptions.append(symbol)

    async def _resubscribe_loop(self):
        while self._running:
            await asyncio.sleep(1)
            with self._lock:
                if self._pending_trade_subscriptions and self._ws:
                    batch = self._pending_trade_subscriptions[:20]
                    self._pending_trade_subscriptions = self._pending_trade_subscriptions[20:]
                    for sym in batch:
                        await self._send_trade_subscription(sym)
                if self._pending_subscriptions and self._ws:
                    batch = self._pending_subscriptions[:10]
                    self._pending_subscriptions = self._pending_subscriptions[10:]
                    for symbol, tf in batch:
                        await self._send_subscription(symbol, tf)

    async def _send_subscription(self, symbol: str, timeframe: str):
        inst_id = self._format_inst_id(symbol)
        if timeframe.endswith("h") or timeframe.endswith("H"):
            tf_okx = timeframe.upper()
        else:
            tf_okx = timeframe.lower()
        sub = {
            "op": "subscribe",
            "args": [{"instId": inst_id, "channel": f"candle{tf_okx}"}],
        }
        if self._ws:
            await self._ws.send(json.dumps(sub))
            logger.debug(f"Subscribed: {symbol} candle{tf_okx}")

    async def _send_trade_subscription(self, symbol: str):
        inst_id = self._format_inst_id(symbol)
        sub = {
            "op": "subscribe",
            "args": [{"instId": inst_id, "channel": "trades"}],
        }
        if self._ws:
            await self._ws.send(json.dumps(sub))
            logger.debug(f"Subscribed: {symbol} trades")

    async def _read_loop(self):
        while self._running and self._ws:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=60)
                data = json.loads(msg)
                await self._handle_message(data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                if self._running:
                    logger.warning(f"WebSocket read error: {e}")
                break
        if self._running:
            await self._handle_disconnect()

    async def _handle_message(self, data: dict):
        evt = data.get("event")
        if evt in ("subscribe", "unsubscribe"):
            return
        if evt == "error":
            msg = data.get("msg", "")
            if "trades" in msg:
                return
            logger.warning(f"WS error: {msg}")
            return
        arg = data.get("arg", {})
        channel = arg.get("channel", "")

        if channel == "trades":
            await self._handle_trade(arg.get("instId", ""), data.get("data", []))
            return

        if channel.startswith("candle"):
            symbol = self._parse_symbol(arg.get("instId", ""))
            tf = channel.replace("candle", "").lower()
            for candle_data in data.get("data", []):
                kline = KlineData.from_ws_data(symbol, tf, candle_data)
                if self.on_kline:
                    self.on_kline(kline)

    async def _handle_trade(self, inst_id: str, trades: list):
        if not trades or not self.on_trade:
            return
        for trade in trades:
            symbol = self._parse_symbol(inst_id)
            price = float(trade[1])
            volume = float(trade[2])
            ts = datetime.fromtimestamp(int(trade[4]) / 1000)
            self.on_trade(symbol, price, volume, ts)

    async def _handle_disconnect(self):
        if self.on_disconnect:
            self.on_disconnect()
        self._reconnect_count += 1
        if self._reconnect_count >= self.max_reconnect:
            logger.error("Max reconnection attempts reached")
            return
        logger.warning(f"Reconnecting in {self.reconnect_delay}s... ({self._reconnect_count}/{self.max_reconnect})")
        await asyncio.sleep(self.reconnect_delay)
        try:
            await self.connect()
            with self._lock:
                for symbol, tf in self._subscriptions:
                    self._pending_subscriptions.append((symbol, tf))
            self._reconnect_count = 0
            if self.on_connect:
                self.on_connect()
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            await self._handle_disconnect()

    def _format_inst_id(self, symbol: str) -> str:
        if ":" in symbol:
            base_quote = symbol.split(":")[0]
            base = base_quote.split("/")[0]
            quote = base_quote.split("/")[1]
            return f"{base}-{quote}-SWAP"
        if "/" in symbol:
            return symbol.replace("/", "-")
        return f"{symbol}-USD-SWAP"

    def _parse_symbol(self, inst_id: str) -> str:
        if inst_id.endswith("-USD-SWAP"):
            base = inst_id.replace("-USD-SWAP", "")
            return f"{base}/USD:{base}"
        if inst_id.endswith("-USDT-SWAP"):
            base = inst_id.replace("-USDT-SWAP", "")
            return f"{base}/USDT:{base}"
        if inst_id.endswith("-USDT"):
            return inst_id.replace("-USDT", "/USDT")
        return inst_id


class OKXWebSocketManager(WebSocketManager):
    def __init__(self, **kwargs):
        # candle/index/mark-price candle data uses business endpoint
        super().__init__(url="wss://ws.okx.com:8443/ws/v5/business", **kwargs)


class BinanceWebSocketManager(WebSocketManager):
    def __init__(self, **kwargs):
        super().__init__(url="wss://stream.binance.com:9443/ws", **kwargs)

    def _format_inst_id(self, symbol: str) -> str:
        return symbol.lower().replace("/", "")

    def _parse_symbol(self, stream_name: str) -> str:
        stream_name = stream_name.lower()
        symbol_map = {
            "btcusdt": "BTC/USDT",
            "ethusdt": "ETH/USDT",
            "solusdt": "SOL/USDT",
            "bnbusdt": "BNB/USDT",
            "xrpusdt": "XRP/USDT",
            "adausdt": "ADA/USDT",
            "dogeusdt": "DOGE/USDT",
            "dotusdt": "DOT/USDT",
            "maticusdt": "MATIC/USDT",
            "avaxusdt": "AVAX/USDT",
        }
        for k, v in symbol_map.items():
            if k in stream_name:
                return v
        return stream_name.upper()

    async def _handle_message(self, data: dict):
        if "e" in data and data["e"] == "kline":
            symbol = self._parse_symbol(data["s"])
            tf = data["k"]["i"].lower()
            kline = KlineData(
                symbol=symbol,
                timeframe=tf,
                timestamp=datetime.fromtimestamp(data["k"]["t"] / 1000),
                open=float(data["k"]["o"]),
                high=float(data["k"]["h"]),
                low=float(data["k"]["l"]),
                close=float(data["k"]["c"]),
                volume=float(data["k"]["v"]),
            )
            if self.on_kline:
                self.on_kline(kline)


class WebSocketPool:
    def __init__(self, max_connections: int = 3):
        self.max_connections = max_connections
        self._managers: dict[str, WebSocketManager] = {}
        self._lock = threading.Lock()

    def get_manager(self, exchange: str) -> WebSocketManager:
        with self._lock:
            if exchange not in self._managers:
                if exchange == "okx":
                    self._managers[exchange] = OKXWebSocketManager()
                elif exchange == "binance":
                    self._managers[exchange] = BinanceWebSocketManager()
                else:
                    raise ValueError(f"Unsupported exchange: {exchange}")
            return self._managers[exchange]

    async def start_all(self, symbols: list[str], timeframes: list[str]):
        for exchange, manager in self._managers.items():
            for symbol in symbols:
                for tf in timeframes:
                    manager.subscribe(symbol, tf)
            await manager.connect()

    async def stop_all(self):
        for manager in self._managers.values():
            await manager.close()
        self._managers.clear()
