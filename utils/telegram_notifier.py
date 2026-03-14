# utils/telegram_notifier.py
"""
Telegram Notifier - Sends trade alerts to your Telegram.
Designed for MANUAL trading assistance: shows you the setup,
you decide whether to take the trade.

SETUP (one-time):
1. Open Telegram → search @BotFather → /newbot → copy BOT_TOKEN
2. Send any message to your new bot
3. Open: https://api.telegram.org/botYOUR_TOKEN/getUpdates
4. Copy the chat.id number from the JSON response
5. Add to your .env file:
      TELEGRAM_BOT_TOKEN=7312456789:AAFxyz...
      TELEGRAM_CHAT_ID=123456789

USAGE in live_trader.py:
    from utils.telegram_notifier import TelegramNotifier
    self.telegram = TelegramNotifier()

    # When alert fires:
    self.telegram.alert_setup(symbol, underlying, strike, opt_type,
                               alert_high, alert_low, sl, t1, t2, t3, rsi)

    # When you manually enter (optional):
    self.telegram.entry_confirmed(symbol, entry_price, sl, t1, t2, t3, qty)

    # When price hits a target or SL (optional):
    self.telegram.target_hit(symbol, tp_num, price, entry_price, qty)
    self.telegram.sl_hit(symbol, price, entry_price, qty, daily_pnl)

    # End of day:
    self.telegram.daily_summary(trades, wins, losses, daily_pnl)
"""

import os
import requests
import logging
from datetime import datetime


class TelegramNotifier:
    """
    Sends clean, actionable trade setup alerts to Telegram.
    All methods are fire-and-forget — they never crash your main bot.
    """

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.logger = logging.getLogger("TelegramNotifier")

        self.enabled = bool(self.token and self.chat_id)
        if self.enabled:
            self.logger.info("✅ Telegram notifications enabled")
        else:
            self.logger.warning(
                "⚠️  Telegram not configured — add TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID to your .env file"
            )

    # ─────────────────────────────────────────────
    # INTERNAL SEND — never raises, never crashes bot
    # ─────────────────────────────────────────────

    def _send(self, message: str):
        """Send a message. Silent fail — will never crash the bot."""
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
            if not resp.ok:
                self.logger.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
        except requests.exceptions.Timeout:
            self.logger.warning("Telegram send timed out (5s) — skipping")
        except Exception as e:
            self.logger.error(f"Telegram send failed: {e}")

    @staticmethod
    def _now():
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _date():
        return datetime.now().strftime("%d %b %Y")

    # ─────────────────────────────────────────────
    # 1. ALERT SETUP — main notification
    #    Called when RSI crosses above threshold on a green candle.
    #    This is the most important message — gives you everything
    #    you need to decide whether to take the trade manually.
    # ─────────────────────────────────────────────

    def alert_setup(
        self,
        symbol: str,
        underlying: str,
        strike,
        opt_type: str,
        alert_high: float,
        alert_low: float,
        sl: float,
        t1: float,
        t2: float,
        t3: float,
        rsi: float,
        expiry_date=None,
        alert_validity_candles: int = 1,
    ):
        """
        THE main alert. Fires when RSI breakout setup is detected.
        Shows exactly what to buy, where to enter, where to put SL, and targets.

        Parameters:
            symbol          : Full option symbol e.g. NSE-NIFTY-27Mar26-22500-CE
            underlying      : NIFTY / BANKNIFTY / SENSEX
            strike          : Strike price (number)
            opt_type        : CE or PE
            alert_high      : High of alert candle = your entry trigger price
            alert_low       : Low of alert candle
            sl              : Stop loss = alert_low - 1
            t1/t2/t3        : Target 1, 2, 3 prices
            rsi             : Current RSI value
            expiry_date     : Expiry date object or string (optional)
            alert_validity_candles : How many 15-min candles this alert is valid for
        """
        alert_range = round(alert_high - alert_low, 2)
        sl_points = round(alert_high - sl, 2)
        t1_r = round((t1 - alert_high) / sl_points, 1) if sl_points else 0
        t2_r = round((t2 - alert_high) / sl_points, 1) if sl_points else 0
        t3_r = round((t3 - alert_high) / sl_points, 1) if sl_points else 0

        validity_mins = alert_validity_candles * 15
        expiry_str = str(expiry_date) if expiry_date else "today"

        msg = (
            f"🔔 <b>TRADE SETUP ALERT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>{underlying} {int(strike)} {opt_type}</b>  |  Expiry: {expiry_str}\n"
            f"🕐 {self._now()}\n"
            f"📊 RSI: <b>{rsi:.1f}</b> (crossed above threshold ✅)\n\n"
            f"──── ENTRY ────\n"
            f"⚡ Buy above:  <b>₹{alert_high:.2f}</b>  ← trigger price\n"
            f"📏 Candle range:  ₹{alert_range:.2f}\n\n"
            f"──── EXITS ────\n"
            f"🔴 Stop Loss:  <b>₹{sl:.2f}</b>  ({sl_points:.2f} pts below entry)\n"
            f"🎯 Target 1:   <b>₹{t1:.2f}</b>  (+{round(t1-alert_high,2):.2f} | {t1_r}R)\n"
            f"🎯 Target 2:   <b>₹{t2:.2f}</b>  (+{round(t2-alert_high,2):.2f} | {t2_r}R)\n"
            f"🎯 Target 3:   <b>₹{t3:.2f}</b>  (+{round(t3-alert_high,2):.2f} | {t3_r}R)\n\n"
            f"──── INFO ────\n"
            f"⏳ Valid for next <b>{validity_mins} mins</b> ({alert_validity_candles} candle)\n"
            f"📋 Symbol: <code>{symbol}</code>"
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 2. ALERT EXPIRED — setup didn't trigger
    # ─────────────────────────────────────────────

    def alert_expired(self, symbol: str, underlying: str, strike, opt_type: str, alert_high: float):
        """Fires when alert validity window passed without price breaking alert_high."""
        msg = (
            f"⏰ <b>SETUP EXPIRED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 {underlying} {int(strike)} {opt_type}\n"
            f"🕐 {self._now()}\n\n"
            f"Price never broke ₹{alert_high:.2f}\n"
            f"Setup cancelled. Watching for new signal..."
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 3. ENTRY CONFIRMED — you placed the trade
    #    Call this manually or from your order confirmation
    # ─────────────────────────────────────────────

    def entry_confirmed(
        self,
        symbol: str,
        entry_price: float,
        sl: float,
        t1: float,
        t2: float,
        t3: float,
        qty: int,
        mode: str = "multi_lot",
    ):
        """
        Optional — call this when you've actually entered the trade.
        Gives you a clean reference card for the open position.
        """
        risk_per_unit = round(entry_price - sl, 2)
        risk_total = round(risk_per_unit * qty, 2)

        msg = (
            f"✅ <b>TRADE ENTERED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <code>{symbol}</code>\n"
            f"🕐 {self._now()}\n\n"
            f"💰 Entry:      <b>₹{entry_price:.2f}</b>\n"
            f"📦 Qty:        <b>{qty} units</b>  ({mode})\n\n"
            f"──── YOUR EXITS ────\n"
            f"🔴 SL:         <b>₹{sl:.2f}</b>  (risk: ₹{risk_per_unit:.2f}/unit)\n"
            f"🎯 T1:         <b>₹{t1:.2f}</b>\n"
            f"🎯 T2:         <b>₹{t2:.2f}</b>\n"
            f"🎯 T3:         <b>₹{t3:.2f}</b>\n\n"
            f"💸 Max risk this trade: <b>₹{risk_total:.2f}</b>\n\n"
            f"👆 Set your SL order NOW at ₹{sl:.2f}"
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 4. TARGET HIT
    # ─────────────────────────────────────────────

    def target_hit(
        self,
        symbol: str,
        tp_num: int,
        price: float,
        entry_price: float,
        qty_exited: int,
        new_sl: float = None,
    ):
        """Call when price reaches a target level."""
        profit = round((price - entry_price) * qty_exited, 2)
        next_action = ""
        if tp_num == 1:
            next_action = f"\n👉 Move SL to ₹{new_sl:.2f}" if new_sl else "\n👉 Trail your SL now"
        elif tp_num == 2:
            next_action = f"\n👉 Move SL to ₹{new_sl:.2f}" if new_sl else "\n👉 Let T3 run"
        elif tp_num == 3:
            next_action = "\n🏁 Final target — consider full exit"

        msg = (
            f"🎯 <b>TARGET {tp_num} HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <code>{symbol}</code>\n"
            f"🕐 {self._now()}\n\n"
            f"📈 Price:      <b>₹{price:.2f}</b>\n"
            f"📊 Entry was:  ₹{entry_price:.2f}\n"
            f"✅ Profit ({qty_exited} units): <b>+₹{profit:.2f}</b>"
            f"{next_action}"
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 5. STOP LOSS HIT
    # ─────────────────────────────────────────────

    def sl_hit(
        self,
        symbol: str,
        price: float,
        entry_price: float,
        qty: int,
        daily_pnl: float = 0,
    ):
        """Call when price hits stop loss."""
        loss = round((price - entry_price) * qty, 2)
        daily_color = "🟢" if daily_pnl >= 0 else "🔴"

        msg = (
            f"🛑 <b>STOP LOSS HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <code>{symbol}</code>\n"
            f"🕐 {self._now()}\n\n"
            f"📉 Exit price:  <b>₹{price:.2f}</b>\n"
            f"📊 Entry was:   ₹{entry_price:.2f}\n"
            f"❌ Loss ({qty} units): <b>₹{loss:.2f}</b>\n\n"
            f"{daily_color} Daily P&L so far: <b>₹{daily_pnl:+.2f}</b>\n\n"
            f"💡 Stick to the plan. One loss is fine."
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 6. SQUARE OFF (end of day forced close)
    # ─────────────────────────────────────────────

    def square_off(self, symbol: str, price: float, entry_price: float, qty: int, reason: str = "SQ_OFF"):
        """Call on forced square-off at end of trading window."""
        pnl = round((price - entry_price) * qty, 2)
        icon = "🟢" if pnl >= 0 else "🔴"

        msg = (
            f"🔔 <b>POSITION CLOSED — {reason}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <code>{symbol}</code>\n"
            f"🕐 {self._now()}\n\n"
            f"💰 Exit:   <b>₹{price:.2f}</b>\n"
            f"📊 Entry:  ₹{entry_price:.2f}\n"
            f"{icon} P&L: <b>₹{pnl:+.2f}</b>"
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 7. DAILY SUMMARY
    # ─────────────────────────────────────────────

    def daily_summary(
        self,
        total_trades: int,
        wins: int,
        losses: int,
        daily_pnl: float,
        best_trade: float = None,
        worst_trade: float = None,
    ):
        """Send end-of-day performance summary."""
        win_rate = round(wins / total_trades * 100) if total_trades else 0
        pnl_icon = "🟢" if daily_pnl >= 0 else "🔴"
        best_str = f"\n🏆 Best trade:  ₹{best_trade:+.2f}" if best_trade is not None else ""
        worst_str = f"\n💀 Worst trade: ₹{worst_trade:+.2f}" if worst_trade is not None else ""

        msg = (
            f"📋 <b>DAILY SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {self._date()}\n\n"
            f"📊 Trades:    {total_trades}  (✅{wins}W  ❌{losses}L)\n"
            f"🎯 Win rate:  <b>{win_rate}%</b>"
            f"{best_str}"
            f"{worst_str}\n\n"
            f"{pnl_icon} Daily P&L: <b>₹{daily_pnl:+.2f}</b>"
        )
        self._send(msg)

    # ─────────────────────────────────────────────
    # 8. SYSTEM ALERTS (bot health)
    # ─────────────────────────────────────────────

    def bot_started(self, mode: str = "PAPER", window_start: str = "10:15", window_end: str = "15:00"):
        """Send when bot starts up. Confirms your phone is receiving alerts."""
        msg = (
            f"🤖 <b>BOT STARTED</b>  [{mode}]\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {self._date()}  {self._now()}\n"
            f"⏰ Trading window: {window_start} – {window_end}\n\n"
            f"✅ Telegram alerts are working!\n"
            f"You'll get notified on every setup."
        )
        self._send(msg)

    def daily_loss_limit_hit(self, daily_pnl: float, limit: float):
        """Send when daily loss limit is reached and bot stops trading."""
        msg = (
            f"🚨 <b>DAILY LOSS LIMIT HIT — TRADING STOPPED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {self._now()}\n\n"
            f"📉 Daily P&L:  <b>₹{daily_pnl:+.2f}</b>\n"
            f"🔴 Limit:      ₹{limit:.2f}\n\n"
            f"🛑 Bot will not take new trades today.\n"
            f"Close any open positions manually."
        )
        self._send(msg)

    def test_connection(self):
        """
        Send a test message to confirm everything is working.
        Call this from command line:
            python -c "
            from dotenv import load_dotenv; load_dotenv()
            from utils.telegram_notifier import TelegramNotifier
            TelegramNotifier().test_connection()
            "
        """
        msg = (
            f"✅ <b>TEST — Telegram is working!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {self._now()}  {self._date()}\n\n"
            f"Your RSI Breakout bot will send\n"
            f"trade alerts to this chat.\n\n"
            f"<i>Setup complete. Happy trading! 🚀</i>"
        )
        self._send(msg)
        self.logger.info("Test message sent to Telegram")
