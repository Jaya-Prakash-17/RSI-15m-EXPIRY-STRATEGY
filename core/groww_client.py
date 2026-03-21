# core/groww_client.py
import logging
import os
import random
import datetime
import pandas as pd
import numpy as np
import dotenv
dotenv.load_dotenv()

try:
    from growwapi import GrowwAPI
    HAS_GROWW_SDK = True
except ImportError:
    HAS_GROWW_SDK = False

class GrowwClient:
    def __init__(self, api_key=None, api_secret=None):
        self.logger = logging.getLogger("GrowwClient")
        self.api_key = api_key or os.getenv("GROWW_API_KEY")
        self.api_secret = api_secret or os.getenv("GROWW_API_SECRET")
        self.client = None
        self._instrument_cache = {}  # symbol -> instrument dict. Static per session.
        
        # NO MOCK MODE - Fail fast if requirements not met
        if not HAS_GROWW_SDK:
            error_msg = (
                "CRITICAL: Groww SDK not installed. "
                "Install with: pip install growwapi"
            )
            self.logger.critical(error_msg)
            raise ImportError(error_msg)
        
        if not self.api_key or not self.api_secret:
            self.logger.warning(
                "API credentials missing. "
                "Set GROWW_API_KEY and GROWW_API_SECRET in .env file if trading or downloading data."
            )
            # We don't raise here anymore to allow backtests with local data to start.
            return
        
        # Attempt initial authentication but don't crash if it fails (lazy fallback)
        try:
            self._authenticate()
        except Exception as e:
            self.logger.warning(f"Initial authentication failed: {e}. Will retry on next API call.")


    def _authenticate(self):
        """Internal authentication logic with better error messages."""
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials missing. Cannot authenticate.")

        try:
            access_token = GrowwAPI.get_access_token(api_key=self.api_key, secret=self.api_secret)
            self.client = GrowwAPI(access_token)
            self.logger.info("Successfully authenticated with Groww API.")
        except Exception as e:
            msg = str(e)
            if "Authorisation failed" in msg or "permissions" in msg:
                error_msg = (
                    "CRITICAL: Groww Authorisation Failed. "
                    "1. Check if GROWW_API_KEY is correct and NOT EXPIRED (JWT tokens expire daily). "
                    "2. Ensure 'Trading API' is enabled on your Groww developer portal. "
                    "3. Ensure you have 'Approved' the daily session if using Key/Secret flow."
                )
            else:
                error_msg = f"CRITICAL: Authentication failed: {e}"
            
            self.logger.error(error_msg)
            raise ConnectionError(error_msg)


    def _safe_call(self, api_func, *args, **kwargs):
        """
        Wrapper for all Groww API calls.
        On 401 Unauthorized or token-related error, re-authenticates and retries once.
        On any other error, raises normally.
        """
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            is_auth_error = ('401' in error_str or 
                            'unauthorized' in error_str or 
                            'token' in error_str or
                            'expired' in error_str)
            if is_auth_error:
                self.logger.warning(
                    f"Auth error detected ({type(e).__name__}). "
                    f"Re-authenticating and retrying..."
                )
                try:
                    self._authenticate()
                    self.logger.info("Re-authentication successful. Retrying API call.")
                    return api_func(*args, **kwargs)
                except Exception as re_auth_err:
                    self.logger.critical(f"Re-authentication FAILED: {re_auth_err}")
                    self.logger.critical("All API calls will fail. Manual intervention needed.")
                    raise ConnectionError(f"Re-auth failed: {re_auth_err}") from re_auth_err
            raise  # Re-raise non-auth errors unchanged


    def get_historical_candles(self, symbol, interval, start_date, end_date):
        """
        Fetch historical candles.
        symbol: groww_symbol (e.g. NSE-NIFTY-25Jan24-21500-CE) or Index Name (NIFTY/BANKNIFTY)
        """
        try:
            interval_map = {
                1: GrowwAPI.CANDLE_INTERVAL_MIN_1,
                5: GrowwAPI.CANDLE_INTERVAL_MIN_5,
                15: GrowwAPI.CANDLE_INTERVAL_MIN_15,
                30: GrowwAPI.CANDLE_INTERVAL_MIN_30,
                60: GrowwAPI.CANDLE_INTERVAL_HOUR_1,
                240: GrowwAPI.CANDLE_INTERVAL_HOUR_4,
                1440: GrowwAPI.CANDLE_INTERVAL_DAY
            }
            sdk_interval = interval_map.get(interval, GrowwAPI.CANDLE_INTERVAL_MIN_15)
            
            # Correct Index Symbol Mapping (per Groww API docs)
            # Format: Exchange-TradingSymbol
            index_symbols = {
                "NIFTY": "NSE-NIFTY",
                "BANKNIFTY": "NSE-BANKNIFTY",
                "SENSEX": "BSE-SENSEX"
            }
            
            # Determine correct symbol and segment
            if symbol in index_symbols:
                # It's an index
                groww_symbol = index_symbols[symbol]
                exchange = GrowwAPI.EXCHANGE_NSE if "NSE" in groww_symbol else GrowwAPI.EXCHANGE_BSE
                segment = GrowwAPI.SEGMENT_CASH  # Indices are always CASH segment
            else:
                # It's an option or other derivative
                groww_symbol = symbol
                # Determine exchange from symbol prefix (BSE-SENSEX... or NSE-NIFTY...)
                exchange = GrowwAPI.EXCHANGE_BSE if symbol.startswith("BSE-") else GrowwAPI.EXCHANGE_NSE
                segment = GrowwAPI.SEGMENT_FNO
            
            if not self.client: self._authenticate()
            
            try:
                self.logger.info(f"Fetching candles for {symbol} using symbol: {groww_symbol}, segment: {segment}")
                resp = self.client.get_historical_candles(
                    exchange=exchange,
                    segment=segment,
                    groww_symbol=groww_symbol,
                    start_time=start_date.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=end_date.strftime("%Y-%m-%d %H:%M:%S"),
                    candle_interval=sdk_interval
                )
                
                # DEBUG: Log response metadata
                if resp:
                    candles_count = len(resp.get('candles', []))
                    if candles_count == 0:
                        self.logger.warning(f"RAW API Response for {symbol} (EMPTY): {resp}")
                    else:
                        self.logger.debug(f"API Response for {symbol}: {candles_count} candles returned.")
                else:
                    self.logger.warning(f"API Response for {symbol} is None.")
                
                if resp and 'candles' in resp and len(resp['candles']) > 0:
                        data = []
                        for candle in resp['candles']:
                            # Safe parsing with defaults
                            try:
                                dt = pd.to_datetime(candle[0])
                                o = float(candle[1] or 0.0)
                                h = float(candle[2] or 0.0)
                                l = float(candle[3] or 0.0)
                                c = float(candle[4] or 0.0)
                                v = int(candle[5] or 0)
                                
                                data.append({
                                    'datetime': dt,
                                    'open': o,
                                    'high': h,
                                    'low': l,
                                    'close': c,
                                    'volume': v
                                })
                            except (ValueError, TypeError, IndexError) as parse_err:
                                self.logger.warning(f"Skipping malformed candle: {candle} Error: {parse_err}")
                                continue
                        
                        return pd.DataFrame(data)
                
                self.logger.warning(f"No candle data returned for {symbol}")
                return pd.DataFrame()
                
            except Exception as e:
                self.logger.error(f"Error fetching candles for {symbol}: {e}")
                return pd.DataFrame()

        except Exception as e:
            self.logger.error(f"Error in get_historical_candles wrapper: {e}")
            return pd.DataFrame()


    def get_order_status(self, order_id):
        """Fetch status of an order."""
        try:
            if not self.client: self._authenticate()
            segment = GrowwAPI.SEGMENT_FNO
            resp = self._safe_call(
                self.client.get_order_status,
                groww_order_id=order_id,
                segment=segment
            )
            return {
                "status": resp.get("order_status"),
                "filled_quantity": resp.get("filled_quantity", 0),
                "groww_order_id": resp.get("groww_order_id"),
                "fill_price": float(resp.get("average_fill_price") or 0)
            }
        except Exception as e:
            self.logger.error(f"Error fetching order status {order_id}: {e}")
            return {"status": "ERROR"}

    def get_ltp(self, symbol):
        """Get Last Traded Price.
        
        For INDEX spot prices: pass just the name ('NIFTY', 'BANKNIFTY', 'SENSEX')
            → queries CASH segment with correct index symbol mapping.
        For OPTION prices: pass the FULL Groww symbol (e.g. 'NSE-NIFTY-25Jan24-21500-CE')
            → queries FNO segment. Do NOT pass just 'NIFTY' for option LTP.
        """
        try:
            # Index Mapping Logic for LTP (Compact format)
            index_map = {
                "NIFTY": "NSE_NIFTY",
                "BANKNIFTY": "NSE_BANKNIFTY",
                "SENSEX": "BSE_SENSEX"
            }
            
            if symbol in index_map:
                key = index_map[symbol]
                segment = GrowwAPI.SEGMENT_CASH
            else:
                # Option LTP - resolve to compact format via instruments
                if not self.client: self._authenticate()
                
                # BUG-008: Use instrument cache to avoid excessive API calls
                if symbol not in self._instrument_cache:
                    self.logger.debug(f"Cache miss — fetching instrument for {symbol}")
                    instr = self._safe_call(self.client.get_instrument_by_groww_symbol, symbol)
                    if instr:
                        self._instrument_cache[symbol] = instr
                
                instr = self._instrument_cache.get(symbol)
                
                if not instr:
                    self.logger.error(f"Could not resolve instrument for option symbol {symbol}")
                    return None
                
                key = f"{instr['exchange']}_{instr['trading_symbol']}"
                segment = GrowwAPI.SEGMENT_FNO

            if not self.client: self._authenticate()
            resp = self._safe_call(
                self.client.get_ltp,
                segment=segment,
                exchange_trading_symbols=key
            )
            return float(resp['ltp']) if resp and 'ltp' in resp else None
            
        except Exception as e:
            self.logger.error(f"Error fetching LTP for {symbol}: {e}")
            return None

    def place_order(self, symbol, qty, side, order_type="MARKET", price=None, product="MIS", trading_symbol=None):
        """
        Place order.
        Requires trading_symbol for real API usage.
        """
        if not trading_symbol:
            self.logger.error("Trading Symbol is REQUIRED for place_order.")
            return None

        try:
            groww_side = GrowwAPI.TRANSACTION_TYPE_BUY if side.upper() == "BUY" else GrowwAPI.TRANSACTION_TYPE_SELL
            groww_product = GrowwAPI.PRODUCT_MIS if product.upper() == "MIS" else GrowwAPI.PRODUCT_CNC
            
            groww_order_type = GrowwAPI.ORDER_TYPE_MARKET
            trigger_price = None
            limit_price = price
            
            if order_type.upper() == "LIMIT":
                groww_order_type = GrowwAPI.ORDER_TYPE_LIMIT
            elif order_type.upper() in ["SL-M", "SL_M"]:
                groww_order_type = GrowwAPI.ORDER_TYPE_STOP_LOSS_MARKET
                trigger_price = price
                limit_price = None 
            elif order_type.upper() == "SL":
                groww_order_type = GrowwAPI.ORDER_TYPE_STOP_LOSS
                trigger_price = price
            
            # Determine exchange from symbol/trading_symbol
            # SENSEX options may just be 'SENSEX...' in compact format
            if (trading_symbol and trading_symbol.startswith("SENSEX")) or (symbol and symbol.startswith("BSE-")):
                exchange = GrowwAPI.EXCHANGE_BSE
            else:
                exchange = GrowwAPI.EXCHANGE_NSE
            
            if not self.client: self._authenticate()
            resp = self._safe_call(
                self.client.place_order,
                trading_symbol=trading_symbol,
                quantity=qty,
                validity=GrowwAPI.VALIDITY_DAY,
                exchange=exchange,
                segment=GrowwAPI.SEGMENT_FNO,
                product=groww_product,
                order_type=groww_order_type,
                transaction_type=groww_side,
                price=limit_price,
                trigger_price=trigger_price
            )
            return resp

        except Exception as e:
            self.logger.error(f"Order placement failed: {e}")
            return None

    def get_balance(self):
        try:
            if not self.client: self._authenticate()
            resp = self.client.get_available_margin_details()
            if 'fno_margin_details' in resp:
                return float(resp['fno_margin_details'].get('option_buy_balance_available', 0.0))
            return float(resp.get('clear_cash', 0.0))
        except Exception as e:
            self.logger.error(f"Failed to fetch balance: {e}")
            return None

    def clear_instrument_cache(self):
        """Clear instrument cache. Call at session start or during testing."""
        self._instrument_cache.clear()
        self.logger.info("Instrument cache cleared")

    def modify_order(self, order_id, qty=None, order_type=None, price=None, trigger_price=None):
        """
        Modify an existing open/pending order.
        Used for trailing SL by modifying trigger_price.
        
        Args:
            order_id: groww_order_id returned from place_order
            qty: New quantity (optional)
            order_type: New order type (optional)
            price: New limit price (optional)
            trigger_price: New trigger price for SL orders (optional)
        
        Returns:
            Modified order response or None on failure
        """
        try:
            # Build modification params
            modify_params = {
                'groww_order_id': order_id,
                'segment': GrowwAPI.SEGMENT_FNO
            }
            
            if qty is not None:
                modify_params['quantity'] = qty
            
            if order_type is not None:
                if order_type.upper() == "MARKET":
                    modify_params['order_type'] = GrowwAPI.ORDER_TYPE_MARKET
                elif order_type.upper() == "LIMIT":
                    modify_params['order_type'] = GrowwAPI.ORDER_TYPE_LIMIT
                elif order_type.upper() in ["SL-M", "SL_M"]:
                    modify_params['order_type'] = GrowwAPI.ORDER_TYPE_STOP_LOSS_MARKET
                elif order_type.upper() == "SL":
                    modify_params['order_type'] = GrowwAPI.ORDER_TYPE_STOP_LOSS
            
            if price is not None:
                modify_params['price'] = price
            
            if trigger_price is not None:
                modify_params['trigger_price'] = trigger_price
            
            if not self.client: self._authenticate()
            resp = self.client.modify_order(**modify_params)
            
            if resp and 'groww_order_id' in resp:
                self.logger.info(f"Order {order_id} modified successfully")
                return resp
            
            self.logger.error(f"Order modification failed: {resp}")
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to modify order {order_id}: {e}")
            return None

    def cancel_order(self, order_id, segment=None):
        """
        Cancel a pending/open order.
        
        Args:
            order_id: groww_order_id to cancel
            segment: segment type (defaults to SEGMENT_FNO)
        
        Returns:
            Cancellation response or None on failure
        """
        try:
            seg = segment or GrowwAPI.SEGMENT_FNO
            if not self.client: self._authenticate()
            resp = self.client.cancel_order(
                groww_order_id=order_id,
                segment=seg
            )
            
            if resp:
                self.logger.info(f"Order {order_id} cancelled successfully")
                return resp
            
            self.logger.error(f"Order cancellation failed: {resp}")
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {e}")
            return None

    def get_contracts(self, underlying, expiry_date):
        try:
            # Use BSE for SENSEX, NSE for others
            exchange = GrowwAPI.EXCHANGE_BSE if underlying == "SENSEX" else GrowwAPI.EXCHANGE_NSE
            
            if not self.client: self._authenticate()
            resp = self.client.get_contracts(
                exchange=exchange,
                underlying_symbol=underlying,
                expiry_date=expiry_date.strftime("%Y-%m-%d")
            )
            return resp.get('contracts', [])
        except Exception as e:
            self.logger.error(f"Failed to get contracts: {e}")
            return []

    def get_expiries(self, underlying):
        try:
            # Use BSE for SENSEX, NSE for others
            exchange = GrowwAPI.EXCHANGE_BSE if underlying == "SENSEX" else GrowwAPI.EXCHANGE_NSE
            
            if not self.client: self._authenticate()
            resp = self.client.get_expiries(
                exchange=exchange,
                underlying_symbol=underlying
            )
            return resp.get('expiries', [])
        except Exception as e:
            self.logger.error(f"Failed to get expiries: {e}")
            return []

    def get_option_chain_details(self, underlying: str, expiry_date) -> dict:
        """
        Build a (strike, option_type) -> groww_symbol mapping using get_contracts().
        get_contracts() is the official documented Groww SDK method.
        Returns: dict like {(22500.0, 'CE'): 'NSE-NIFTY-07Jan26-22500-CE', ...}
        """
        try:
            exchange = GrowwAPI.EXCHANGE_BSE if underlying == "SENSEX" else GrowwAPI.EXCHANGE_NSE
            if not self.client:
                self._authenticate()
            resp = self.client.get_contracts(
                exchange=exchange,
                underlying_symbol=underlying,
                expiry_date=expiry_date.strftime("%Y-%m-%d")
            )
            contracts = resp.get('contracts', [])
            if not contracts:
                self.logger.warning(f"No contracts from API for {underlying} {expiry_date}")
                return {}

            mapping = {}
            for contract in contracts:
                # Format: NSE-NIFTY-07Jan26-22500-CE  or  BSE-SENSEX-08Jan26-80000-PE
                parts = contract.split('-')
                if len(parts) >= 5:
                    try:
                        strike = float(parts[-2])
                        opt_type = parts[-1]  # 'CE' or 'PE'
                        mapping[(strike, opt_type)] = contract
                    except (ValueError, IndexError):
                        self.logger.debug(f"Could not parse contract: {contract}")
                        continue

            self.logger.info(f"Option chain for {underlying} {expiry_date}: {len(mapping)} contracts")
            return mapping

        except Exception as e:
            self.logger.error(f"Failed to fetch option chain for {underlying}: {e}")
            return {}
