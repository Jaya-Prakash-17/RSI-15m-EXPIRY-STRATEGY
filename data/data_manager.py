# data/data_manager.py
import os
import pandas as pd
import logging
from datetime import datetime, timedelta
import pytz
from data.historical_downloader import HistoricalDownloader
from core.exceptions import DataError
from utils.symbol_parser import build_option_symbol

class DataManager:
    def __init__(self, config):
        self.logger = logging.getLogger("DataManager")
        self.config = config
        self.downloader = HistoricalDownloader(config)
        self.base_path = config['data']['storage_path']
        self.offline_mode = config.get('backtest', {}).get('offline_mode', False)
        self.data_cache = {}
        # Cache for option chain mapping: (underlying, date) -> { (strike, type): trading_symbol }
        self.chain_cache = {}
        self.expiry_cache = {}

    def clear_cache(self, clear_spot=False):
        """
        Clears derivative data from memory to save space, but retains spot data
        by default since spot history is small and reused for RSI warmup across days.
        """
        if clear_spot:
            self.data_cache = {}
            self.logger.info("Complete data cache cleared.")
        else:
            # Only keep files in the 'spot' directory
            self.data_cache = {
                path: df for path, df in self.data_cache.items()
                if os.sep + "spot" + os.sep in path
            }
            self.logger.info("Derivative cache cleared. Spot data retained.")

    def _check_for_gaps(self, df, start_date, end_date, symbol):
        """
        P-04: Internal Gap Detection.
        Validates whether the dataframe contains expected trading sessions.
        Returns a list of missing (start, end) date segments.
        """
        if df.empty:
            return [(start_date, end_date)]

        df = df.copy()
        df['date'] = df['datetime'].dt.date
        actual_days = set(df['date'].unique())

        # Determine expected trading days (Monday-Friday)
        expected_days = pd.date_range(start=start_date, end=end_date, freq='B').date

        missing_segments = []
        current_missing_start = None

        for day in expected_days:
            # Simple check: Does at least one candle exist for this trading day?
            if day not in actual_days:
                if current_missing_start is None:
                    current_missing_start = day
            else:
                if current_missing_start is not None:
                    # Found the end of a gap
                    missing_segments.append((
                        pd.to_datetime(current_missing_start),
                        pd.to_datetime(day) - timedelta(seconds=1)
                    ))
                    current_missing_start = None

        # Handle trailing gap at end of range
        if current_missing_start is not None:
            missing_segments.append((pd.to_datetime(current_missing_start), end_date))

        return missing_segments

    def get_spot_candles(self, symbol, start_date, end_date, refresh=False):
        filepath = os.path.join(self.base_path, "spot", f"{symbol}_15m.csv")

        file_exists = os.path.exists(filepath)
        need_download = refresh or not file_exists
        gaps = []

        if not need_download and file_exists:
            df = self._load_csv(filepath)
            if df.empty:
                need_download = True
            else:
                df['datetime'] = pd.to_datetime(df['datetime'])
                file_min = df['datetime'].min()
                file_max = df['datetime'].max()

                # Boundary check
                if file_min > start_date or file_max < end_date:
                    self.logger.info(f"Spot {symbol} boundary mismatch: file={file_min.date()} to {file_max.date()}, requested={start_date.date()} to {end_date.date()}")
                    need_download = True
                else:
                    # P-04: Interval Gap Check
                    gaps = self._check_for_gaps(df, start_date, end_date, symbol)
                    if gaps:
                        self.logger.warning(f"Detected {len(gaps)} gaps in {symbol} spot data.")
                        for gs, ge in gaps:
                            self.logger.info(f"  Missing: {gs.date()} to {ge.date()}")
                        need_download = True

        if need_download:
            if self.offline_mode:
                self.logger.warning(f"Offline Mode: Skipping download/repair of {symbol} spot data.")
            elif file_exists and not refresh:
                # Smart fallback: file exists but has boundary/gap issues
                # Use existing data without API call, just log the issue
                self.logger.info(f"Using existing spot data for {symbol} (file present, skipping API repair)")
            else:
                # File truly missing or refresh requested — must download
                self.logger.info(f"Spot data for {symbol} {'updating from API...' if refresh else 'not found locally, downloading...'}")
                if gaps:
                    for gs, ge in gaps:
                        self.downloader.download_spot_data(symbol, gs, ge)
                else:
                    self.downloader.download_spot_data(symbol, start_date, end_date)

                if filepath in self.data_cache: del self.data_cache[filepath]

        df = self._load_csv(filepath)
        return self._filter_date_range(df, start_date, end_date)

    def get_derivative_candles(self, underlying, contract_name, year, start_date, end_date, refresh=False):
        filepath = os.path.join(self.base_path, "derivatives", underlying, str(year), f"{contract_name}_15m.csv")

        file_exists = os.path.exists(filepath)
        need_download = refresh or not file_exists

        # Check if existing file covers the requested date range
        if not need_download and file_exists:
            existing_df = self._load_csv(filepath)
            if not existing_df.empty and 'datetime' in existing_df.columns:
                existing_df['datetime'] = pd.to_datetime(existing_df['datetime'])
                file_max_date = existing_df['datetime'].max().date()
                file_min_date = existing_df['datetime'].min().date()
                requested_end = end_date.date() if hasattr(end_date, 'date') else end_date
                requested_start = start_date.date() if hasattr(start_date, 'date') else start_date

                if file_max_date < requested_end or file_min_date > requested_start:
                    self.logger.debug(f"Derivative {contract_name} boundary mismatch (file: {file_min_date} to {file_max_date}, need {requested_start} to {requested_end})")
                    need_download = True

        if need_download:
            if self.offline_mode:
                self.logger.debug(f"Offline Mode: Using existing derivative data for {contract_name} (even if range incomplete).")
            else:
                # File truly missing or range incomplete — must download
                self.logger.info(f"Derivative data for {contract_name} {'updating from API...' if refresh else 'not found/incomplete locally, downloading...'}")
                success = self.downloader.download_derivative_data(underlying, contract_name, year, start_date, end_date)
                if not success and not os.path.exists(filepath):
                    return pd.DataFrame()
                if filepath in self.data_cache: del self.data_cache[filepath]

        df = self._load_csv(filepath)
        return self._filter_date_range(df, start_date, end_date)

    def _load_csv(self, filepath):
        if filepath in self.data_cache: return self.data_cache[filepath]
        try:
            df = pd.read_csv(filepath)
            if df.empty:
                self.logger.warning(f"CSV file is empty: {filepath}")
                return pd.DataFrame()  # Not cached — retry on next call
            df['datetime'] = pd.to_datetime(df['datetime'])
            if not df.empty:
                df = df.sort_values('datetime').reset_index(drop=True)
            self.data_cache[filepath] = df
            return df
        except pd.errors.EmptyDataError:
            self.logger.warning(f"Empty CSV: {filepath}")
            return pd.DataFrame()
        except Exception as e:
            self.logger.error(f"Error reading {filepath}: {e}")
            # Keep return pd.DataFrame() — don't raise here
            # (raising would crash the bot on a single bad file)
            # The DataError class is available for future use; log only for now
            return pd.DataFrame()  # Not cached — retry on next call

    def _filter_date_range(self, df, start, end):
        if df.empty: return df
        # P-22: O(log n) filtering using searchsorted
        start_idx = df['datetime'].searchsorted(pd.Timestamp(start), side='left')
        end_idx = df['datetime'].searchsorted(pd.Timestamp(end), side='right')
        return df.iloc[start_idx:end_idx].copy().reset_index(drop=True)

    def get_expiries(self, underlying):
        today = datetime.now().date()
        if underlying in self.expiry_cache and self.expiry_cache[underlying]['date'] == today:
            return self.expiry_cache[underlying]['data']

        expiries = self.downloader.client.get_expiries(underlying)
        if expiries:
            self.expiry_cache[underlying] = {'date': today, 'data': expiries}
        return expiries

    def detect_expiry_from_files(self, underlying, reference_date):
        """
        Tier 1: Detect actual expiry from existing historical data files.
        This is the most accurate method as it uses actual traded contracts.

        Args:
            underlying: Index name
            reference_date: Historical date

        Returns:
            Expiry date if found in existing files, None otherwise
        """
        if isinstance(reference_date, datetime):
            reference_date = reference_date.date()

        # Look for derivative CSV files matching this period
        derivative_path = os.path.join(self.base_path, 'derivatives', underlying)
        if not os.path.exists(derivative_path):
            return None

        # Get year directory
        year = reference_date.year
        year_path = os.path.join(derivative_path, str(year))
        if not os.path.exists(year_path):
            return None

        # Search for files with dates around this period
        # File format: {Exchange}-{underlying}-{ddMMMYY}-{strike}-{type}.csv
        # CRASH FIX: SENSEX uses BSE- prefix, not NSE-
        import re
        exchange_prefix = 'BSE' if underlying == 'SENSEX' else 'NSE'
        expiry_pattern = re.compile(rf'{exchange_prefix}-{underlying}-([0-9]{{2}}[A-Za-z]{{3}}[0-9]{{2}})-')

        found_expiries = set()
        for filename in os.listdir(year_path):
            match = expiry_pattern.search(filename)
            if match:
                expiry_str = match.group(1)
                try:
                    # Parse: 03Dec25 -> 2025-12-03
                    expiry_date = datetime.strptime(expiry_str, '%d%b%y').date()
                    # Check if this expiry is close to our reference date (within 2 weeks)
                    days_diff = abs((expiry_date - reference_date).days)
                    if days_diff <= 14:  # Within 2 weeks
                        found_expiries.add(expiry_date)
                except:
                    pass

        if found_expiries:
            # Find the nearest expiry >= reference_date
            future_expiries = [e for e in found_expiries if e >= reference_date]
            if future_expiries:
                expiry = min(future_expiries)
                self.logger.info(f"[Tier 1] Found expiry {expiry} from existing files for {underlying}")
                return expiry

        return None

    def calculate_historical_expiry(self, underlying: str, reference_date) -> 'date':
        """
        Calculate the historical expiry date for an underlying on a given
        reference date. Uses utils.expiry_calendar — the single source of
        truth covering all NSE/BSE changes from Jan 2020 to present.

        This is used in backtesting where the Groww API doesn't have
        historical expiry data, so we compute it from rules.
        """
        from utils.expiry_calendar import get_expiry_for_date
        from datetime import datetime

        if isinstance(reference_date, datetime):
            reference_date = reference_date.date()
        elif hasattr(reference_date, 'date'):
            reference_date = reference_date.date()

        expiry = get_expiry_for_date(underlying, reference_date)
        self.logger.info(
            f"[ExpiryCalendar] Expiry for {underlying} "
            f"(ref: {reference_date}) = {expiry}"
        )
        return expiry

    def get_trading_symbol(self, underlying, expiry_date, strike, opt_type):
        """
        Map contract details to actual Trading Symbol using Option Chain.
        Falls back to constructing symbol if API lookup fails.
        """
        # Create a cache key based on day so we don't refetch too often if loop calls this
        today = datetime.now().date()
        cache_key = (underlying, expiry_date, today)

        if cache_key not in self.chain_cache:
            # Fetch and cache
            mapping = self.downloader.client.get_option_chain_details(underlying, expiry_date)
            if mapping:
                self.chain_cache[cache_key] = mapping
            else:
                self.logger.warning(f"Could not fetch option chain mapping for {underlying} {expiry_date}")

        mapping = self.chain_cache.get(cache_key, {})
        trading_symbol = mapping.get((float(strike), opt_type))

        # If found in chain, return it
        if trading_symbol:
            return trading_symbol

        # Fallback: Constructing symbols manually is unsafe because formats vary by exchange/SDK.
        # Instead, we abort and log the failure.
        self.logger.error(
            f"Option chain lookup failed for {underlying} {expiry_date} {strike} {opt_type}. "
            f"Cannot safely construct trading symbol. Entry aborted."
        )
        return None  # Caller checks for None and aborts entry

    def get_nearest_expiry(self, underlying, reference_date=None):
        """
        Get the nearest expiry date for an underlying from Groww API.

        For weekly expiries (NIFTY, SENSEX): Returns next weekly expiry
        For monthly expiries (BANKNIFTY): Returns next monthly expiry
        """
        if reference_date is None:
            reference_date = datetime.now().date()
        elif isinstance(reference_date, datetime):
            reference_date = reference_date.date()

        # Fetch expiries from API
        expiries = self.get_expiries(underlying)

        if not expiries:
            self.logger.warning(f"No expiries found for {underlying}, using reference date")
            return reference_date

        # Convert expiry strings to dates and sort
        try:
            expiry_dates = [datetime.strptime(exp, "%Y-%m-%d").date() for exp in expiries]
            expiry_dates.sort()
        except Exception as e:
            self.logger.error(f"Error parsing expiry dates: {e}")
            return reference_date

        # Find nearest expiry >= reference_date
        for exp_date in expiry_dates:
            if exp_date >= reference_date:
                self.logger.info(f"Using expiry date {exp_date} for {underlying} (ref: {reference_date})")
                return exp_date

        # If no future expiry found, use the last one
        if expiry_dates:
            self.logger.warning(f"No future expiry found, using last available: {expiry_dates[-1]}")
            return expiry_dates[-1]

        return reference_date

    def build_option_symbol(self, underlying, reference_date, strike, opt_type, use_historical=False):
        """
        Build option symbol using API or historical calculation.

        For live trading:
        1. Get expiries from API (returns currently active expiries)
        2. Find nearest expiry >= reference_date
        3. Get contracts from API for that expiry
        4. Match by strike + option type to get exact contract name

        For backtesting (use_historical=True):
        1. Calculate historical expiry based on NSE rules (day of week, holidays)
        2. Construct symbol manually (API only has future expiries, not historical)

        Falls back to manual symbol construction if API fails.

        Args:
            underlying: Index name (NIFTY, BANKNIFTY, SENSEX)
            reference_date: Reference date - used to find nearest expiry
            strike: Strike price
            opt_type: 'CE' or 'PE'
            use_historical: If True, use calculated historical expiry instead of live API

        Returns:
            Option symbol like: NSE-NIFTY-02Jan25-23950-CE or BSE-SENSEX-05Feb26-84000-CE
        """
        ref_date = reference_date.date() if hasattr(reference_date, 'date') else reference_date

        expiry_date = None

        if use_historical:
            # For backtesting: Calculate historical expiry directly
            # The live API only returns future/active expiries, not historical ones
            expiry_date = self.calculate_historical_expiry(underlying, reference_date)
            self.logger.info(f"Using historical calculated expiry {expiry_date} for {underlying} (ref: {ref_date})")
        else:
            # For live trading: Use API to get current expiries
            try:
                expiry_date = self.get_nearest_expiry(underlying, ref_date)
            except Exception as e:
                self.logger.warning(f"Failed to get expiry from API for {underlying}: {e}")

            # Fallback: Calculate expiry if API fails
            if expiry_date is None:
                expiry_date = self.calculate_historical_expiry(underlying, reference_date)
                self.logger.info(f"Using calculated expiry {expiry_date} for {underlying}")

        # Step 2: Try to get exact symbol from contracts API (only for live trading)
        # Historical contracts won't be in the API, so skip for backtesting
        if not use_historical:
            try:
                # Cache key for contracts
                cache_key = f"contracts_{underlying}_{expiry_date}"

                if cache_key not in self.chain_cache:
                    contracts = self.downloader.client.get_contracts(underlying, expiry_date)
                    # Build mapping: (strike, opt_type) -> symbol
                    contract_map = {}
                    for contract in contracts:
                        # Parse contract: BSE-SENSEX-05Feb26-84000-CE or NSE-NIFTY-03Feb26-25000-CE
                        parts = contract.split('-')
                        if len(parts) >= 5:
                            c_strike = float(parts[-2])
                            c_type = parts[-1]
                            contract_map[(c_strike, c_type)] = contract
                    self.chain_cache[cache_key] = contract_map
                    self.logger.debug(f"Cached {len(contract_map)} contracts for {underlying} expiry {expiry_date}")

                contract_map = self.chain_cache.get(cache_key, {})
                exact_symbol = contract_map.get((float(strike), opt_type))

                if exact_symbol:
                    return exact_symbol
                else:
                    self.logger.debug(f"No contract found for {underlying} {strike} {opt_type}, constructing manually")
            except Exception as e:
                self.logger.warning(f"Failed to get contract from API: {e}")

        # Fallback: Construct symbol manually
        symbol = build_option_symbol(underlying, expiry_date, strike, opt_type)

        self.logger.info(f"Using constructed symbol {symbol} for {underlying} (ref: {ref_date})")

        return symbol
