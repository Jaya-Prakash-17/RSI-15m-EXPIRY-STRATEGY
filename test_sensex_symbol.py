
import os
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from growwapi import GrowwAPI

load_dotenv()

def test_symbol(client, symbol, exchange, segment):
    print(f"Testing {symbol} on {exchange}/{segment}...")
    try:
        start = datetime(2026, 3, 1)
        end = datetime(2026, 3, 20)
        resp = client.get_historical_candles(
            exchange=exchange,
            segment=segment,
            groww_symbol=symbol,
            start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
            candle_interval=GrowwAPI.CANDLE_INTERVAL_MIN_15
        )
        if resp and 'candles' in resp and len(resp['candles']) > 0:
            print(f"✅ SUCCESS: Found {len(resp['candles'])} candles for {symbol}")
            return True
        else:
            print(f"❌ FAIL: No candles for {symbol}")
            return False
    except Exception as e:
        print(f"❌ ERROR for {symbol}: {e}")
        return False

def main():
    api_key = os.getenv("GROWW_API_KEY")
    api_secret = os.getenv("GROWW_API_SECRET")
    
    if not api_key:
        print("GROWW_API_KEY not found in .env")
        return

    # Use GrowwAPI.get_access_token if needed
    try:
        access_token = GrowwAPI.get_access_token(api_key=api_key, secret=api_secret)
        client = GrowwAPI(access_token)
    except Exception as e:
        print(f"❌ AUTH ERROR: {e}")
        return
    
    # Symbols to test
    symbols = [
        ("BSE-SENSEX", GrowwAPI.EXCHANGE_BSE, GrowwAPI.SEGMENT_CASH),
        ("SENSEX", GrowwAPI.EXCHANGE_NSE, GrowwAPI.SEGMENT_CASH),
        ("NSE-SENSEX", GrowwAPI.EXCHANGE_NSE, GrowwAPI.SEGMENT_CASH),
        ("NSE-NIFTY", GrowwAPI.EXCHANGE_NSE, GrowwAPI.SEGMENT_CASH), # Baseline success check
    ]
    
    for sym, ex, seg in symbols:
        test_symbol(client, sym, ex, seg)

if __name__ == "__main__":
    main()
