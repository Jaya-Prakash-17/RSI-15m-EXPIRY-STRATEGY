# execution/trade_tracker.py
import json
import os
import logging
import tempfile
import shutil
from datetime import datetime
from threading import RLock

class TradeTracker:
    """
    Manages bot trade persistence to isolate bot trades from manual trades.
    Stores trades in bot_trades.json with atomic file operations.
    """
    
    def __init__(self, filepath="data/bot_trades.json"):
        self.logger = logging.getLogger("TradeTracker")
        self.filepath = filepath
        self.lock = RLock()
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Create trade file if it doesn't exist."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        
        if not os.path.exists(self.filepath):
            initial_data = {
                "active_trades": [],
                "closed_trades": [],
                "metadata": {
                    "last_updated": datetime.now().isoformat(),
                    "version": "1.0"
                }
            }
            self._save_data(initial_data)
            self.logger.info(f"Created new trade tracking file: {self.filepath}")
    
    def _load_data(self):
        """Load trade data from file. Handles corruption and missing file gracefully."""
        if not os.path.exists(self.filepath):
            return {"active_trades": [], "closed_trades": [], "metadata": {}}
        
        try:
            with open(self.filepath, 'r') as f:
                content = f.read()
            if not content.strip():
                # Empty file — treat as no data
                self.logger.warning(f"{os.path.basename(self.filepath)} is empty. Starting with fresh state.")
                return {"active_trades": [], "closed_trades": [], "metadata": {}}
            return json.loads(content)
        
        except json.JSONDecodeError as e:
            # File is corrupted — CRITICAL: trader must check broker manually
            self.logger.critical(
                f"🚨 {os.path.basename(self.filepath)} is CORRUPTED (JSONDecodeError: {e}). "
                f"Cannot determine if positions are open. "
                f"CHECK GROWW APP IMMEDIATELY before resuming bot."
            )
            # Save the corrupted file for forensics
            backup_path = self.filepath + f".corrupted_{datetime.now().strftime('%H%M%S')}"
            try:
                shutil.copy(self.filepath, backup_path)
                self.logger.critical(f"Corrupted file backed up to: {backup_path}")
            except Exception:
                pass
            # Return empty state — bot will start but with no known positions
            # (trader must verify manually)
            return {"active_trades": [], "closed_trades": [], "metadata": {}}
        
        except Exception as e:
            self.logger.error(f"Unexpected error loading trade data: {e}")
            return {"active_trades": [], "closed_trades": [], "metadata": {}}
    
    def _save_data(self, data):
        """Atomically save trade data to file using tempfile."""
        data["metadata"] = {
            "last_updated": datetime.now().isoformat(),
            "version": "1.0"
        }
        
        dir_name = os.path.dirname(os.path.abspath(self.filepath))
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', dir=dir_name, delete=False, suffix='.tmp'
            ) as tf:
                json.dump(data, tf, indent=2, default=str)
                temp_path = tf.name
            
            # Atomic replace (overwrites if exists)
            os.replace(temp_path, self.filepath)
        except Exception as e:
            self.logger.error(f"Error saving trade data to {self.filepath}: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise
    
    def add_active_trade(self, trade):
        """Add a new active trade."""
        with self.lock:
            data = self._load_data()
            
            # Generate unique trade ID
            date_str = datetime.now().strftime("%Y%m%d")
            trade_num = len(data["active_trades"]) + len(data["closed_trades"]) + 1
            trade["trade_id"] = f"BOT_{date_str}_{trade_num:03d}"
            trade["status"] = "OPEN"
            trade["created_at"] = datetime.now().isoformat()
            
            data["active_trades"].append(trade)
            self._save_data(data)
            
            self.logger.info(f"Added active trade: {trade['trade_id']}")
            return trade["trade_id"]
    
    def get_active_trades(self):
        """Get all active trades."""
        with self.lock:
            data = self._load_data()
            return data.get("active_trades", [])
            
    def has_active_trade_for_index(self, index_name):
        """Check if there is already an active trade for a specific underlying index."""
        with self.lock:
            active_trades = self.get_active_trades()
            for trade in active_trades:
                if trade.get("underlying") == index_name:
                    return True
            return False
    
    def get_active_trades_for_index(self, underlying: str) -> list:
        """
        Returns active trades filtered to a specific underlying.
        Used for per-index trade guards so NIFTY does not block BANKNIFTY.
        
        Args:
            underlying: 'NIFTY', 'BANKNIFTY', or 'SENSEX'
        """
        with self.lock:
            data = self._load_data()
            return [t for t in data.get("active_trades", [])
                    if t.get("underlying") == underlying]

    def get_pending_for_index(self, pending_entries: dict, underlying: str) -> dict:
        """Filter pending_entries dict to a specific underlying."""
        return {sym: p for sym, p in pending_entries.items()
                if p.get('underlying') == underlying}
    
    def update_trade(self, trade_id, updates):
        """Update an existing trade."""
        with self.lock:
            data = self._load_data()
            
            for trade in data["active_trades"]:
                if trade["trade_id"] == trade_id:
                    trade.update(updates)
                    trade["updated_at"] = datetime.now().isoformat()
                    self._save_data(data)
                    self.logger.info(f"Updated trade: {trade_id}")
                    return True
            
            self.logger.warning(f"Trade not found for update: {trade_id}")
            return False
    
    def close_trade(self, trade_id, exit_price, reason, pnl):
        """Move trade from active to closed."""
        with self.lock:
            data = self._load_data()
            
            for i, trade in enumerate(data["active_trades"]):
                if trade["trade_id"] == trade_id:
                    trade["exit_price"] = exit_price
                    trade["exit_time"] = datetime.now().isoformat()
                    trade["reason"] = reason
                    trade["pnl"] = pnl
                    trade["status"] = "CLOSED"
                    
                    # Move to closed trades
                    data["closed_trades"].append(trade)
                    data["active_trades"].pop(i)
                    
                    self._save_data(data)
                    self.logger.info(f"Closed trade: {trade_id} | PnL: {pnl} | Reason: {reason}")
                    return True
            
            self.logger.warning(f"Trade not found for closing: {trade_id}")
            return False
    
    def get_daily_pnl(self, date=None):
        """Calculate total PnL for a specific date."""
        if date is None:
            date = datetime.now().date()
        
        date_str = date.strftime("%Y%m%d")
        
        with self.lock:
            data = self._load_data()
            daily_pnl = 0.0
            
            for trade in data["closed_trades"]:
                if trade.get("trade_id", "").startswith(f"BOT_{date_str}"):
                    daily_pnl += trade.get("pnl", 0.0)
            
            return daily_pnl
    
    def clear_day_data(self):
        """Clear active trades (called at start of new day)."""
        with self.lock:
            data = self._load_data()
            
            # Move any lingering active trades to closed
            for trade in data["active_trades"]:
                trade["status"] = "EXPIRED"
                trade["reason"] = "DAY_END_CLEANUP"
                data["closed_trades"].append(trade)
            
            data["active_trades"] = []
            self._save_data(data)
            
            self.logger.info("Cleared active trades for new day")
    
    def reconcile_with_positions(self, broker_positions):
        """
        Reconcile bot trades with actual broker positions.
        Returns list of discrepancies.
        """
        with self.lock:
            discrepancies = []
            active_trades = self.get_active_trades()
            
            # Create map of bot trades by trading symbol
            bot_symbols = {t["trading_symbol"]: t for t in active_trades}
            
            # Check each broker position
            for pos in broker_positions:
                symbol = pos.get("trading_symbol")
                qty = pos.get("quantity", 0)
                
                if symbol in bot_symbols:
                    # Expected position
                    bot_trade = bot_symbols[symbol]
                    if abs(qty - bot_trade["qty"]) > 0.01:
                        discrepancies.append({
                            "type": "QUANTITY_MISMATCH",
                            "symbol": symbol,
                            "expected": bot_trade["qty"],
                            "actual": qty
                        })
                else:
                    # This is a manual trade - ignore it
                    self.logger.info(f"Manual trade detected (ignored): {symbol} qty={qty}")
            
            # Check for bot trades without positions
            broker_symbols = {p.get("trading_symbol") for p in broker_positions}
            for symbol, trade in bot_symbols.items():
                if symbol not in broker_symbols:
                    discrepancies.append({
                        "type": "MISSING_POSITION",
                        "symbol": symbol,
                        "expected": trade["qty"],
                        "actual": 0
                    })
            
            if discrepancies:
                self.logger.error(f"Position reconciliation found {len(discrepancies)} discrepancies")
                for d in discrepancies:
                    self.logger.error(f"  {d}")
            else:
                self.logger.info("Position reconciliation successful - all trades match")
            
            return discrepancies

    def get_closed_trades_today(self):
        """Get all trades closed today. Used for daily Telegram summary.
        
        Returns:
            List of closed trade dicts from today's session.
        """
        date_str = datetime.now().strftime("%Y%m%d")
        with self.lock:
            data = self._load_data()
            return [t for t in data["closed_trades"] if t.get("trade_id", "").startswith(f"BOT_{date_str}")]

    # --- Pending Entries Persistence (MEDIUM FIX) ---
    
    def save_pending_entries(self, pending_entries):
        """Persist pending entries to JSON so they survive crashes."""
        with self.lock:
            filepath = self.filepath.replace("bot_trades", "pending_entries")
            try:
                # Convert datetime objects to strings for JSON serialization
                serializable = {}
                for symbol, entry in pending_entries.items():
                    entry_copy = {}
                    for k, v in entry.items():
                        if hasattr(v, 'isoformat'):
                            entry_copy[k] = v.isoformat()
                        elif hasattr(v, 'strftime'):
                            entry_copy[k] = v.strftime('%Y-%m-%d')
                        else:
                            entry_copy[k] = v
                    serializable[symbol] = entry_copy
                
                with open(filepath, 'w') as f:
                    json.dump(serializable, f, indent=2, default=str)
            except Exception as e:
                self.logger.error(f"Error saving pending entries: {e}")

    def load_pending_entries(self):
        """Load pending entries from JSON (for crash recovery)."""
        with self.lock:
            filepath = self.filepath.replace("bot_trades", "pending_entries")
            try:
                if os.path.exists(filepath):
                    with open(filepath, 'r') as f:
                        return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading pending entries: {e}")
            return {}

    def clear_pending_entries(self):
        """Clear pending entries file."""
        with self.lock:
            filepath = self.filepath.replace("bot_trades", "pending_entries")
            try:
                if os.path.exists(filepath):
                    with open(filepath, 'w') as f:
                        json.dump({}, f)
            except Exception as e:
                self.logger.error(f"Error clearing pending entries: {e}")
