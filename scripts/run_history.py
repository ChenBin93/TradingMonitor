#!/usr/bin/env python3
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import get_settings
from src.data.exchange import OKXAdapter
from src.data.history_db import HistoryDB
from src.data.history_downloader import HistoryDownloader, HistoryStatsComputer
from src.utils.logging import setup_logging

DEFAULT_LOOKBACK_DAYS = [90, 180, 365]


async def download_only(downloader: HistoryDownloader, symbols: list, timeframes: list, days_list: list):
    print(f"开始下载历史数据: {len(symbols)} 标的 x {len(timeframes)} 时间框架 x {days_list} 天")
    start = time.time()
    await downloader.full_sync(days_list=days_list)
    elapsed = time.time() - start
    print(f"下载完成, 耗时 {elapsed:.1f}s")


async def stats_only(computer: HistoryStatsComputer, symbols: list, timeframes: list, days_list: list):
    print(f"开始计算统计数据: {len(symbols)} 标的 x {timeframes} x {days_list} 天")
    start = time.time()
    count = computer.compute_for_all_symbols(symbols, timeframes, days_list=days_list)
    elapsed = time.time() - start
    print(f"统计完成: {count} 条记录, 耗时 {elapsed:.1f}s")


async def full_run(downloader: HistoryDownloader, computer: HistoryStatsComputer, symbols: list, timeframes: list, days_list: list):
    print(f"=== 历史数据完整流程 ===")
    print(f"标的数量: {len(symbols)}")
    print(f"时间框架: {timeframes}")
    print(f"历史周期: {days_list} 天")
    print()
    await download_only(downloader, symbols, timeframes, days_list)
    print()
    await stats_only(computer, symbols, timeframes, days_list)
    print("=== 完成 ===")


def main():
    parser = argparse.ArgumentParser(description="OKX 历史数据下载与统计")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--stats-only", action="store_true")
    parser.add_argument("--days", type=str, default="90,180,365",
                        help="历史窗口，逗号分隔（默认90,180,365）")
    parser.add_argument("--timeframe", type=str, default=None,
                        help="仅指定时间框架（如4h），默认全下载")
    args = parser.parse_args()

    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    settings = get_settings()
    setup_logging(level="INFO", log_file="logs/history.log", console=True)

    db = HistoryDB("data/history.db")
    db.init_schema()

    adapter = OKXAdapter()
    all_symbols = adapter.get_symbol_list(settings.data.top_n)
    all_timeframes = settings.data.timeframes

    if args.timeframe:
        if args.timeframe not in all_timeframes:
            print(f"错误: 不支持的时间框架 '{args.timeframe}'，支持: {all_timeframes}")
            sys.exit(1)
        timeframes = [args.timeframe]
    else:
        timeframes = all_timeframes

    try:
        days_list = [int(d.strip()) for d in args.days.split(",")]
    except ValueError:
        print(f"错误: --days 参数格式错误，请使用逗号分隔的数字，如: 90,180,365")
        sys.exit(1)

    history_cfg = settings.data.history
    downloader = HistoryDownloader(
        db=db,
        config=settings.model_dump(),
        batch_size=history_cfg.get("download_batch_size", 50),
        download_interval=history_cfg.get("download_interval_seconds", 60),
    )
    downloader.set_symbols(all_symbols, timeframes)
    computer = HistoryStatsComputer(db=db, config=settings.model_dump())

    if args.stats_only:
        asyncio.run(stats_only(computer, all_symbols, timeframes, days_list))
    elif args.download_only:
        asyncio.run(download_only(downloader, all_symbols, timeframes, days_list))
    else:
        asyncio.run(full_run(downloader, computer, all_symbols, timeframes, days_list))


if __name__ == "__main__":
    main()
