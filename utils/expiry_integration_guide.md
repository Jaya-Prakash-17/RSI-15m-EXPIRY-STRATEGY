# ─── REPLACE the _is_expiry_day() and all expiry logic in ───────────────────
# backtest/intraday_engine.py   AND   data/data_manager.py
# with imports from utils.expiry_calendar
# ────────────────────────────────────────────────────────────────────────────
#
# In BOTH files, at the top with other imports, ADD:
#
#   from utils.expiry_calendar import is_expiry_day, get_expiry_for_date
#
# ────────────────────────────────────────────────────────────────────────────
# BACKTEST/INTRADAY_ENGINE.PY — replace the _is_expiry_day method
# ────────────────────────────────────────────────────────────────────────────

# DELETE the entire old _is_expiry_day() method body (it was 60+ lines).
# Replace with this thin wrapper that delegates to expiry_calendar:

    def _is_expiry_day(self, underlying: str, date) -> bool:
        """
        Check if date is an expiry day for the given underlying.
        Delegates to utils.expiry_calendar which has the full verified
        timeline from Jan 2020 to present (all NSE/BSE circular changes).
        """
        from utils.expiry_calendar import is_expiry_day
        return is_expiry_day(underlying, date)

# ────────────────────────────────────────────────────────────────────────────
# DATA/DATA_MANAGER.PY — replace calculate_historical_expiry and
#                         the inline expiry logic in build_option_symbol
# ────────────────────────────────────────────────────────────────────────────

# REPLACE calculate_historical_expiry() with:

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

        expiry = get_expiry_for_date(underlying, reference_date)
        self.logger.info(
            f"[ExpiryCalendar] Expiry for {underlying} "
            f"(ref: {reference_date}) = {expiry}"
        )
        return expiry

# ────────────────────────────────────────────────────────────────────────────
# DATA/DATA_MANAGER.PY — also update detect_expiry_from_files
# The old hardcoded expiry_day logic inside calculate_historical_expiry
# (the big if/elif NIFTY/SENSEX/BANKNIFTY block) should be DELETED entirely.
# ────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────
# LIVE/LIVE_TRADER.PY — replace _get_tradeable_indices expiry_day comparison
# ────────────────────────────────────────────────────────────────────────────

# In _get_tradeable_indices(), replace the naive day-name comparison:
#   if details['expiry_day'] == day_name:
# with:

    def _get_tradeable_indices(self):
        """
        Get all indices that should be traded today.
        Uses expiry_calendar for accurate expiry detection — handles
        all historical day changes for NIFTY, BANKNIFTY, SENSEX.
        """
        from utils.expiry_calendar import is_expiry_day
        from datetime import datetime

        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")

        tradeable = []

        if not self.trade_only_on_expiry:
            indices = list(self.config['indices'].keys())
            self.logger.info(f"trade_only_on_expiry=False, trading ALL indices: {indices}")
            return indices

        for idx in self.config['indices'].keys():
            # Fast local check first (no API call)
            if not is_expiry_day(idx, today):
                self.logger.debug(f"{idx}: not an expiry day today ({today})")
                continue

            # Confirm with Groww API (verifies holiday adjustments and
            # catches any future rule changes we haven't coded yet)
            try:
                expiries = self.dm.get_expiries(idx)
                if today_str in expiries:
                    self.logger.info(f"✅ Confirmed API expiry for {idx} today ({today})")
                    tradeable.append(idx)
                else:
                    self.logger.warning(
                        f"⚠️  expiry_calendar says {idx} expires today "
                        f"but API disagrees. API expiries: {expiries[:5]}. "
                        f"Skipping {idx} to be safe."
                    )
            except Exception as e:
                # API failure: trust local calendar (don't skip trading day)
                self.logger.warning(
                    f"API expiry check failed for {idx}: {e}. "
                    f"Trusting local expiry_calendar."
                )
                tradeable.append(idx)

        return tradeable

# ────────────────────────────────────────────────────────────────────────────
# CONFIG.YAML — clean up the expiry_day field (it's now just documentation)
# ────────────────────────────────────────────────────────────────────────────

# The config.yaml expiry_day fields (Thursday, Tuesday, Wednesday) are no
# longer used by any code — expiry_calendar is the authority.
# Keep them as human-readable comments only. Update to reflect current state:
#
# indices:
#   NIFTY:
#     expiry_day: Tuesday   # Every Tuesday — expiry_calendar.py is authoritative
#     lot_size: 65
#     tick_size: 0.05
#   BANKNIFTY:
#     expiry_day: Tuesday   # Last Tuesday of month — expiry_calendar.py is authoritative
#     lot_size: 30
#     tick_size: 0.05
#   SENSEX:
#     expiry_day: Thursday  # Every Thursday — expiry_calendar.py is authoritative
#     lot_size: 20
#     tick_size: 0.05
