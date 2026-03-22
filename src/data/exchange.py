from abc import ABC, abstractmethod
from typing import Any


class ExchangeAdapter(ABC):
    @abstractmethod
    def fetch_tickers(self) -> list[tuple[str, float]]:
        pass

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> list[dict]:
        pass

    @abstractmethod
    def get_symbol_list(self, top_n: int = 200) -> list[str]:
        pass


class OKXAdapter(ExchangeAdapter):
    def __init__(self):
        self._exchange = None
        self._swap_symbols = None

    @property
    def exchange(self):
        if self._exchange is None:
            import ccxt
            self._exchange = ccxt.okx()
            self._exchange.load_markets()
        return self._exchange

    def _get_swap_symbols(self) -> list[str]:
        if self._swap_symbols is None:
            self._swap_symbols = [
                sym for sym, mkt in self.exchange.markets.items()
                if mkt.get("type") == "swap" and mkt.get("active")
                and mkt.get("settle") == "USDT"
            ]
        return self._swap_symbols

    def fetch_tickers(self) -> list[tuple[str, float]]:
        try:
            swap_symbols = self._get_swap_symbols()
            result = []
            for symbol in swap_symbols:
                try:
                    ticker = self.exchange.fetch_ticker(symbol)
                    vol = ticker.get("baseVolume", 0) or 0
                    result.append((symbol, vol))
                except:
                    pass
            result.sort(key=lambda x: x[1], reverse=True)
            return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to fetch tickers: {e}")
            return []

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> list[dict]:
        from datetime import datetime
        for attempt in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                result = []
                for bar in ohlcv:
                    ts, o, h, l, c, v = bar
                    result.append({
                        "timestamp": datetime.fromtimestamp(ts / 1000),
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": float(v),
                    })
                return result
            except Exception as e:
                import logging
                msg = str(e)
                if "Too Many Requests" in msg or "429" in msg:
                    if attempt < 2:
                        import time
                        time.sleep(2 ** attempt * 1.5)
                        continue
                logging.getLogger(__name__).warning(f"Failed to fetch candles for {symbol}: {e}")
                return []
        return []

    def get_symbol_list(self, top_n: int = 200) -> list[str]:
        swap_symbols = self._get_swap_symbols()
        return swap_symbols[:top_n]
