import pytest
from datetime import datetime, timedelta
from src.alerts.deduplication import DeduplicationStore


def test_dedup_basic():
    store = DeduplicationStore(window_minutes=30)
    assert store.should_notify("BTC/USDT", "bb_width_squeeze", "stage1") is True
    assert store.should_notify("BTC/USDT", "bb_width_squeeze", "stage1") is False


def test_dedup_different_signals():
    store = DeduplicationStore(window_minutes=30)
    assert store.should_notify("BTC/USDT", "signal_a", "stage1") is True
    assert store.should_notify("BTC/USDT", "signal_b", "stage1") is True


def test_dedup_window_expired():
    store = DeduplicationStore(window_minutes=1)
    assert store.should_notify("BTC/USDT", "test", "stage1") is True
    store._store["BTC/USDT:test:stage1"] = [datetime.now() - timedelta(minutes=2)]
    assert store.should_notify("BTC/USDT", "test", "stage1") is True


def test_dedup_cleanup():
    store = DeduplicationStore(window_minutes=30)
    store._store["old"] = [datetime.now() - timedelta(hours=1)]
    store._store["recent"] = [datetime.now()]
    store.cleanup()
    assert "old" not in store._store
    assert "recent" in store._store
