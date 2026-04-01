#!/usr/bin/env python3
"""
Standalone Groww spot 15-minute downloader for:
- NIFTY
- BANKNIFTY
- SENSEX

This script is intentionally independent of the repo's current data layer.
It talks to Groww directly via the official Python SDK, respects conservative
request pacing, merges safely into the target CSVs, and performs a repair pass
for missing or suspiciously sparse weekdays.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None

from growwapi import GrowwAPI


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "spot"

DEFAULT_START = datetime(2020, 1, 1, 9, 0, 0)
DEFAULT_CHUNK_DAYS = 85
DEFAULT_MIN_SECONDS_BETWEEN_CALLS = 0.70
DEFAULT_REQUESTS_PER_MINUTE = 80
DEFAULT_RETRIES = 6
DEFAULT_DAY_RETRIES = 2
DEFAULT_SPARSE_DAY_THRESHOLD = 20

SESSION_START = dt_time(9, 0)
SESSION_END = dt_time(15, 30)


@dataclass(frozen=True)
class SpotSymbol:
    name: str
    exchange: str
    groww_symbol: str


SPOT_SYMBOLS: tuple[SpotSymbol, ...] = (
    SpotSymbol(
        name="BANKNIFTY",
        exchange="NSE",
        groww_symbol="NSE-BANKNIFTY",
    ),
    SpotSymbol(
        name="NIFTY",
        exchange="NSE",
        groww_symbol="NSE-NIFTY",
    ),
    SpotSymbol(
        name="SENSEX",
        exchange="BSE",
        groww_symbol="BSE-SENSEX",
    ),
)


class RateLimiter:
    def __init__(self, min_seconds_between_calls: float, requests_per_minute: int) -> None:
        self.min_seconds_between_calls = float(min_seconds_between_calls)
        self.requests_per_minute = int(requests_per_minute)
        self._last_call_at = 0.0
        self._minute_window: deque[float] = deque()

    def wait(self) -> None:
        now = time.time()

        if self._last_call_at:
            delta = now - self._last_call_at
            if delta < self.min_seconds_between_calls:
                time.sleep(self.min_seconds_between_calls - delta)

        now = time.time()
        while self._minute_window and now - self._minute_window[0] >= 60.0:
            self._minute_window.popleft()

        if len(self._minute_window) >= self.requests_per_minute:
            sleep_for = 60.0 - (now - self._minute_window[0]) + 0.1
            time.sleep(max(0.0, sleep_for))
            now = time.time()
            while self._minute_window and now - self._minute_window[0] >= 60.0:
                self._minute_window.popleft()

        self._last_call_at = time.time()
        self._minute_window.append(self._last_call_at)


def log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone Groww downloader for 15-minute spot candles."
    )
    parser.add_argument(
        "--start",
        default=DEFAULT_START.strftime("%Y-%m-%d"),
        help="Start date in YYYY-MM-DD format. Default: 2020-01-01",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date in YYYY-MM-DD format. Default: today",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        choices=[s.name for s in SPOT_SYMBOLS],
        default=[s.name for s in SPOT_SYMBOLS],
        help="Subset of indices to download.",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=DEFAULT_CHUNK_DAYS,
        help="Max days per request. Keep <= 90 for 15-minute candles. Default: 85",
    )
    parser.add_argument(
        "--min-spacing",
        type=float,
        default=DEFAULT_MIN_SECONDS_BETWEEN_CALLS,
        help="Minimum seconds between Groww requests. Default: 0.70",
    )
    parser.add_argument(
        "--requests-per-minute",
        type=int,
        default=DEFAULT_REQUESTS_PER_MINUTE,
        help="Conservative request ceiling per minute. Default: 80",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ignore existing CSV contents and rebuild from API only.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Directory where BANKNIFTY_15m.csv, NIFTY_15m.csv, and SENSEX_15m.csv "
            "will be written. Default: data/spot"
        ),
    )
    parser.add_argument(
        "--skip-repair-pass",
        action="store_true",
        help="Skip the missing/sparse weekday repair pass.",
    )
    return parser.parse_args()


def load_environment() -> None:
    env_path = ROOT / ".env"
    if load_dotenv is not None and env_path.exists():
        load_dotenv(env_path)


def build_client() -> GrowwAPI:
    access_token = os.getenv("GROWW_ACCESS_TOKEN")
    if access_token:
        log("Using GROWW_ACCESS_TOKEN from environment.")
        return GrowwAPI(access_token)

    api_key = os.getenv("GROWW_API_KEY")
    api_secret = os.getenv("GROWW_API_SECRET")
    if api_key and api_secret:
        log("Generating Groww access token via API key + secret.")
        return GrowwAPI(GrowwAPI.get_access_token(api_key=api_key, secret=api_secret))

    totp_token = os.getenv("GROWW_TOTP_TOKEN")
    totp_secret = os.getenv("GROWW_TOTP_SECRET")
    if totp_token and totp_secret:
        if pyotp is None:
            raise RuntimeError(
                "TOTP auth requested but pyotp is not installed. "
                "Install pyotp or provide GROWW_ACCESS_TOKEN / GROWW_API_KEY + GROWW_API_SECRET."
            )
        log("Generating Groww access token via TOTP flow.")
        totp_code = pyotp.TOTP(totp_secret).now()
        return GrowwAPI(GrowwAPI.get_access_token(api_key=totp_token, totp=totp_code))

    raise RuntimeError(
        "Missing Groww credentials. Provide one of:\n"
        "1. GROWW_ACCESS_TOKEN\n"
        "2. GROWW_API_KEY + GROWW_API_SECRET\n"
        "3. GROWW_TOTP_TOKEN + GROWW_TOTP_SECRET"
    )


def parse_date(date_str: str | None, end_of_day: bool) -> datetime:
    if not date_str:
        now = datetime.now()
        return now
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        return parsed.replace(hour=23, minute=59, second=59)
    return parsed.replace(hour=9, minute=0, second=0)


def iter_chunks(start_dt: datetime, end_dt: datetime, chunk_days: int) -> Iterable[tuple[datetime, datetime]]:
    current = start_dt
    chunk_span = timedelta(days=chunk_days)
    while current <= end_dt:
        chunk_end = min(current + chunk_span, end_dt)
        yield current, chunk_end
        current = chunk_end + timedelta(seconds=1)


def normalize_candles(response: dict) -> pd.DataFrame:
    candles = (response or {}).get("candles") or []
    rows = []
    for candle in candles:
        if len(candle) < 6:
            continue
        rows.append(
            {
                "datetime": pd.to_datetime(candle[0]),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": int(candle[5] or 0),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.sort_values("datetime").reset_index(drop=True)


def is_retryable_error(message: str) -> bool:
    lowered = message.lower()
    retry_tokens = (
        "429",
        "rate limit",
        "ga000",
        "ga003",
        "timeout",
        "temporarily",
        "unable to serve request currently",
        "connection",
        "reset",
        "timed out",
    )
    return any(token in lowered for token in retry_tokens)


def count_weekdays(start_dt: datetime, end_dt: datetime) -> int:
    days = 0
    current = start_dt.date()
    last = end_dt.date()
    while current <= last:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def fetch_candles(
    client: GrowwAPI,
    limiter: RateLimiter,
    spot: SpotSymbol,
    start_dt: datetime,
    end_dt: datetime,
    retries: int,
    empty_retry_count: int,
) -> pd.DataFrame:
    empty_attempts = 0
    for attempt in range(1, retries + 1):
        limiter.wait()
        try:
            response = client.get_historical_candles(
                exchange=getattr(GrowwAPI, f"EXCHANGE_{spot.exchange}"),
                segment=GrowwAPI.SEGMENT_CASH,
                groww_symbol=spot.groww_symbol,
                start_time=start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                candle_interval=GrowwAPI.CANDLE_INTERVAL_MIN_15,
                timeout=45,
            )
            df = normalize_candles(response)
            if not df.empty:
                return df

            empty_attempts += 1
            if empty_attempts > empty_retry_count:
                return df

            weekday_count = count_weekdays(start_dt, end_dt)
            if weekday_count == 0:
                return df

            wait_for = (2 ** (attempt - 1)) + random.uniform(0.3, 1.5)
            log(
                f"{spot.name}: empty response for {start_dt:%Y-%m-%d} -> {end_dt:%Y-%m-%d} "
                f"(attempt {attempt}/{retries}), retrying in {wait_for:.1f}s"
            )
            time.sleep(wait_for)
        except Exception as exc:  # pragma: no cover - depends on runtime/API
            message = str(exc)
            if attempt >= retries or not is_retryable_error(message):
                raise

            wait_for = (2 ** (attempt - 1)) + random.uniform(0.5, 2.0)
            log(
                f"{spot.name}: request failed for {start_dt:%Y-%m-%d} -> {end_dt:%Y-%m-%d} "
                f"({message}). Retrying in {wait_for:.1f}s"
            )
            time.sleep(wait_for)

    return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])


def load_existing(path: Path, overwrite: bool) -> pd.DataFrame:
    if overwrite or not path.exists():
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    df["datetime"] = pd.to_datetime(df["datetime"])
    return df[["datetime", "open", "high", "low", "close", "volume"]].copy()


def output_path_for(spot: SpotSymbol, output_dir: Path) -> Path:
    return output_dir / f"{spot.name}_15m.csv"


def merge_frames(base_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    if base_df.empty:
        merged = new_df.copy()
    elif new_df.empty:
        merged = base_df.copy()
    else:
        merged = pd.concat([base_df, new_df], ignore_index=True)

    if merged.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    merged["datetime"] = pd.to_datetime(merged["datetime"])
    merged = merged.drop_duplicates(subset=["datetime"], keep="last")
    merged = merged.sort_values("datetime").reset_index(drop=True)
    return merged


def atomic_write_csv(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    to_write = df.copy()
    to_write["datetime"] = pd.to_datetime(to_write["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    to_write.to_csv(tmp_path, index=False)
    os.replace(tmp_path, output_path)


def weekday_dates(start_dt: datetime, end_dt: datetime) -> list[date]:
    dates: list[date] = []
    current = start_dt.date()
    last = end_dt.date()
    while current <= last:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def suspicious_dates(df: pd.DataFrame, start_dt: datetime, end_dt: datetime, sparse_threshold: int) -> list[date]:
    if df.empty:
        return weekday_dates(start_dt, end_dt)

    tmp = df.copy()
    tmp["datetime"] = pd.to_datetime(tmp["datetime"])
    counts = tmp.groupby(tmp["datetime"].dt.date).size().to_dict()

    suspects: list[date] = []
    for day in weekday_dates(start_dt, end_dt):
        count = int(counts.get(day, 0))
        if count == 0 or count < sparse_threshold:
            suspects.append(day)
    return suspects


def repair_day(
    client: GrowwAPI,
    limiter: RateLimiter,
    spot: SpotSymbol,
    day: date,
) -> pd.DataFrame:
    start_dt = datetime.combine(day, SESSION_START)
    end_dt = datetime.combine(day, SESSION_END)
    return fetch_candles(
        client=client,
        limiter=limiter,
        spot=spot,
        start_dt=start_dt,
        end_dt=end_dt,
        retries=DEFAULT_DAY_RETRIES,
        empty_retry_count=1,
    )


def summarize(df: pd.DataFrame, requested_start: datetime, requested_end: datetime, sparse_threshold: int) -> str:
    if df.empty:
        return "rows=0"

    suspects = suspicious_dates(df, requested_start, requested_end, sparse_threshold)
    return (
        f"rows={len(df):,}, min={df['datetime'].min()}, max={df['datetime'].max()}, "
        f"suspicious_weekdays={len(suspects)}"
    )


def download_symbol(
    client: GrowwAPI,
    limiter: RateLimiter,
    spot: SpotSymbol,
    output_dir: Path,
    start_dt: datetime,
    end_dt: datetime,
    chunk_days: int,
    overwrite: bool,
    skip_repair_pass: bool,
    sparse_day_threshold: int,
) -> None:
    output_path = output_path_for(spot, output_dir)
    log(f"{spot.name}: loading existing file {output_path}")
    merged = load_existing(output_path, overwrite=overwrite)

    chunk_count = 0
    for chunk_start, chunk_end in iter_chunks(start_dt, end_dt, chunk_days):
        chunk_count += 1
        log(
            f"{spot.name}: downloading chunk {chunk_count} "
            f"{chunk_start:%Y-%m-%d} -> {chunk_end:%Y-%m-%d}"
        )
        chunk_df = fetch_candles(
            client=client,
            limiter=limiter,
            spot=spot,
            start_dt=chunk_start,
            end_dt=chunk_end,
            retries=DEFAULT_RETRIES,
            empty_retry_count=3,
        )
        merged = merge_frames(merged, chunk_df)

    if not skip_repair_pass:
        suspects = suspicious_dates(merged, start_dt, end_dt, sparse_day_threshold)
        if suspects:
            log(f"{spot.name}: running repair pass for {len(suspects)} suspicious weekday(s)")
        for idx, day in enumerate(suspects, 1):
            log(f"{spot.name}: repair {idx}/{len(suspects)} for {day.isoformat()}")
            day_df = repair_day(client, limiter, spot, day)
            merged = merge_frames(merged, day_df)

    merged = merged.sort_values("datetime").reset_index(drop=True)
    atomic_write_csv(merged, output_path)
    log(f"{spot.name}: wrote {output_path}")
    log(f"{spot.name}: {summarize(merged, start_dt, end_dt, sparse_day_threshold)}")


def main() -> int:
    args = parse_args()
    load_environment()

    start_dt = parse_date(args.start, end_of_day=False)
    end_dt = parse_date(args.end, end_of_day=True)
    if end_dt < start_dt:
        raise SystemExit("--end must be on or after --start")
    if args.chunk_days > 90:
        raise SystemExit("--chunk-days must be <= 90 for 15-minute Groww backtesting candles")
    output_dir = Path(args.output_dir).expanduser()

    selected = {symbol.name for symbol in SPOT_SYMBOLS if symbol.name in args.symbols}
    selected_symbols = [symbol for symbol in SPOT_SYMBOLS if symbol.name in selected]

    log("Starting standalone Groww spot downloader")
    log(f"Range: {start_dt} -> {end_dt}")
    log(f"Symbols: {', '.join(symbol.name for symbol in selected_symbols)}")
    log(f"Output directory: {output_dir}")
    log(
        "Request pacing: "
        f"min_spacing={args.min_spacing:.2f}s, requests_per_minute={args.requests_per_minute}, "
        f"chunk_days={args.chunk_days}"
    )

    client = build_client()
    limiter = RateLimiter(
        min_seconds_between_calls=args.min_spacing,
        requests_per_minute=args.requests_per_minute,
    )

    for spot in selected_symbols:
        download_symbol(
            client=client,
            limiter=limiter,
            spot=spot,
            output_dir=output_dir,
            start_dt=start_dt,
            end_dt=end_dt,
            chunk_days=args.chunk_days,
            overwrite=args.overwrite,
            skip_repair_pass=args.skip_repair_pass,
            sparse_day_threshold=DEFAULT_SPARSE_DAY_THRESHOLD,
        )

    log("Download completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("Interrupted by user.")
        raise SystemExit(130)
