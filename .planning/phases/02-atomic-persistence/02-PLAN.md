---
wave: 1
depends_on: []
files_modified:
  - execution/trade_tracker.py
---

# Plan: Atomic Persistence Infrastructure (Wave 1)

Implement the core persistence logic in `TradeTracker` using atomic write patterns.

<tasks>
<task>
<read_first>
- execution/trade_tracker.py
</read_first>
<action>
Modify `TradeTracker._save_data` to be truly atomic.
- Use `tempfile.NamedTemporaryFile` with `delete=False`.
- Write JSON to the temp file.
- Use `os.replace(temp_path, self.file_path)` for atomic swap.
</action>
<acceptance_criteria>
- `execution/trade_tracker.py` contains `os.replace`.
</acceptance_criteria>
</task>

<task>
<read_first>
- execution/trade_tracker.py
</read_first>
<action>
Implement `save_candle_state(symbol, bars)` and `load_candle_state(symbol)` in `TradeTracker`.
- Save as a separate JSON to avoid bloating trade tracker file.
</action>
<acceptance_criteria>
- `TradeTracker` has `save_candle_state` method.
</acceptance_criteria>
</task>
</tasks>

---

---
wave: 2
depends_on: [1]
files_modified:
  - live/live_trader.py
  - utils/candle_builder.py
---

# Plan: Live Integration (Wave 2)

Connect `LiveTrader` to the atomic persistence system.

<tasks>
<task>
<read_first>
- live/live_trader.py
- utils/candle_builder.py
</read_first>
<action>
Update `LiveTrader._monitor_active_trades` to call `self.tracker.save_candle_state` whenever a new candle is closed in `CandleBuilder`.
Also implement a 60s periodic save of all active candles.
</action>
<acceptance_criteria>
- Newly closed candles appear in `candle_state.json`.
</acceptance_criteria>
</task>

<task>
<read_first>
- live/live_trader.py
</read_first>
<action>
In `LiveTrader.__init__`, load persisted candles and use `self.candle_builder.warm_up_from_df` to restore state.
</action>
<acceptance_criteria>
- RSI is calculated immediately on restart using historical data.
</acceptance_criteria>
</task>
</tasks>
