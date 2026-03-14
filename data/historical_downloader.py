# data/historical_downloader.py
import os
import pandas as pd
import logging
import time
from core.groww_client import GrowwClient
from datetime import datetime, timedelta

class HistoricalDownloader:
    # Maximum candles per API request (conservative estimate for 15min TF)
    # 15min: ~26 candles/day × 30 days = ~780 candles, set chunk to 30 days
    MAX_DAYS_PER_CHUNK = {
        1: 7,       # 1 min: 375 candles/day, ~7 days max
        5: 15,      # 5 min: 75 candles/day, ~15 days max
        15: 30,     # 15 min: 25 candles/day, ~30 days max
        30: 60,     # 30 min: 12 candles/day, ~60 days max
        60: 90,     # 1 hour: 6 candles/day, ~90 days max
    }
    
    def __init__(self, config):
        self.logger = logging.getLogger("HistoricalDownloader")
        self.config = config
        self.client = GrowwClient()
        self.base_path = config['data']['storage_path']
        self.retry_count = config['data'].get('download_retry_count', 3)

    def download_spot_data(self, symbol, start_date, end_date):
        """
        Downloads spot data and saves to CSV.
        Path: data/spot/<SYMBOL>_15m.csv
        """
        self.logger.info(f"Downloading spot data for {symbol} from {start_date} to {end_date}")
        
        df = self._download_chunked(symbol, 15, start_date, end_date)
        if df is None or df.empty:
            return False

        filepath = os.path.join(self.base_path, "spot", f"{symbol}_15m.csv")
        self._save_dataframe(df, filepath)
        return True

    def download_derivative_data(self, symbol, contract_name, year, start_date, end_date):
        """
        Downloads derivative data and saves to CSV.
        Path: data/derivatives/<UNDERLYING>/<YEAR>/<CONTRACT>_15m.csv
        """
        self.logger.info(f"Downloading derivative data for {contract_name}...")
        
        df = self._download_chunked(contract_name, 15, start_date, end_date)
        if df is None or df.empty:
            return False

        # Construct path
        directory = os.path.join(self.base_path, "derivatives", symbol, str(year))
        os.makedirs(directory, exist_ok=True)
        
        filepath = os.path.join(directory, f"{contract_name}_15m.csv")
        self._save_dataframe(df, filepath)
        return True

    def _download_chunked(self, symbol, interval, start_date, end_date):
        """
        Downloads data in chunks to avoid API candle limits.
        For 15min timeframe, uses ~30 day chunks.
        """
        # Get max days per chunk for this interval
        max_days = self.MAX_DAYS_PER_CHUNK.get(interval, 30)
        
        # Convert to datetime if needed
        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date)
        if isinstance(end_date, str):
            end_date = pd.to_datetime(end_date)
        
        # Calculate total days
        total_days = (end_date - start_date).days
        
        if total_days <= max_days:
            # Single request is fine
            return self._download_with_retry(symbol, interval, start_date, end_date)
        
        # Need to chunk
        self.logger.info(f"Large date range ({total_days} days), downloading in {max_days}-day chunks...")
        
        all_dfs = []
        chunk_start = start_date
        chunk_num = 0
        
        while chunk_start < end_date:
            chunk_end = min(chunk_start + timedelta(days=max_days), end_date)
            chunk_num += 1
            
            self.logger.info(f"Downloading chunk {chunk_num}: {chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}")
            
            df = self._download_with_retry(symbol, interval, chunk_start, chunk_end)
            if df is not None and not df.empty:
                all_dfs.append(df)
            
            # Move to next chunk
            chunk_start = chunk_end + timedelta(days=1)
            
            # Small delay between chunks to avoid rate limiting
            time.sleep(0.5)
        
        if not all_dfs:
            self.logger.warning(f"No data downloaded for {symbol}")
            return None
        
        # Combine all chunks
        combined_df = pd.concat(all_dfs, ignore_index=True)
        combined_df['datetime'] = pd.to_datetime(combined_df['datetime'])
        combined_df = combined_df.drop_duplicates(subset=['datetime']).sort_values('datetime')
        
        self.logger.info(f"Combined {len(all_dfs)} chunks: {len(combined_df)} total rows for {symbol}")
        return combined_df

    def _download_with_retry(self, symbol, interval, start_date, end_date):
        """Attempts to download with retries."""
        for attempt in range(self.retry_count):
            try:
                df = self.client.get_historical_candles(symbol, interval, start_date, end_date)
                if not df.empty:
                    return df
            except Exception as e:
                self.logger.warning(f"Download attempt {attempt+1} failed for {symbol}: {e}")
            
            time.sleep(1)  # Backoff
            
        self.logger.warning(f"All download attempts failed for {symbol}")
        return None

    def _save_dataframe(self, df, filepath):
        """Saves dataframe to CSV, merging with existing data if present."""
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        if os.path.exists(filepath):
            try:
                existing_df = pd.read_csv(filepath)
                # Convert datetime to ensure proper merging
                existing_df['datetime'] = pd.to_datetime(existing_df['datetime'])
                df['datetime'] = pd.to_datetime(df['datetime'])
                
                # Merge: Concatenate and drop duplicates based on datetime
                merged_df = pd.concat([existing_df, df])
                merged_df = merged_df.drop_duplicates(subset=['datetime']).sort_values('datetime')
                
                merged_df.to_csv(filepath, index=False)
                self.logger.info(f"Merged and saved {len(merged_df)} rows to {filepath}")
                return
            except Exception as e:
                self.logger.error(f"Error merging data for {filepath}: {e}. Overwriting.")
        
        # Fallback or new file
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.sort_values('datetime', inplace=True)
        df.to_csv(filepath, index=False)
        self.logger.info(f"Saved {len(df)} rows to {filepath}")
