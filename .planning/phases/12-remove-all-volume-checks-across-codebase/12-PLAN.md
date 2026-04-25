# Phase 12: Remove all volume checks across codebase - Plan

**Status:** ## PLANNING COMPLETE
**Wave:** 1
**Autonomous:** true

## Summary
Remove all logical gates, filters, and sorting criteria based on volume data. This ensures the strategy is purely price-action driven and doesn't reject tradeable strikes purely due to low historical volume (which the user believes is hindering trade generation).

## Modified Files
- `config.yaml`
- `backtest/intraday_engine.py`
- `live/live_trader.py`

## Tasks

<task>
<read_first>
- `config.yaml`
</read_first>
<action>
Remove `min_volume_candles_pct` from the `strategy` section in `config.yaml`.
</action>
<acceptance_criteria>
- `config.yaml` does not contain the string `min_volume_candles_pct`.
</acceptance_criteria>
</task>

<task>
<read_first>
- `backtest/intraday_engine.py`
</read_first>
<action>
1. In `IntradayEngine.__init__`, remove the load and warning logic for `vol_filter` (lines 20-26).
2. In `IntradayEngine._is_option_data_tradeable`, remove the volume quality check logic (lines 247-255).
3. In `IntradayEngine.process_expiry_day`, remove the `volume` key from the `candidates` dictionary (line 549) and update the sort key to only use `dist` (line 557).
</action>
<acceptance_criteria>
- `IntradayEngine.__init__` no longer references `min_volume_candles_pct`.
- `_is_option_data_tradeable` return `True, 'ok'` without calculating `zero_vol_pct`.
- `process_expiry_day` sorts candidates by `lambda x: x['dist']` only.
</acceptance_criteria>
</task>

<task>
<read_first>
- `live/live_trader.py`
</read_first>
<action>
1. In `_process_strategy_logic`, remove the `volume` key from the `alert_candidates` dictionary (line 941).
2. In `_process_strategy_logic`, update the sort key for `alert_candidates` to only use `dist` (line 990 [approx]).
3. Remove outdated comments about volume filters near line 576.
</action>
<acceptance_criteria>
- `_process_strategy_logic` does not capture `-x['volume']` in the sort key.
- Comments about Issue #8 (Minimum Volume Filter) are removed.
</acceptance_criteria>
</task>

## Verification
1. Run `grep -r "volume" .` and ensure no logical checks remain (data fetching is okay).
2. Run a sample backtest to ensure no regressions in trade logic.
3. Verify that distance is now the sole tie-breaker (implied by Python's stable sort or by the single key).

## Must-Haves
- [ ] No `min_volume_candles_pct` in `config.yaml`.
- [ ] Volume filter removed from `IntradayEngine`.
- [ ] Volume filter removed from `LiveTrader`.
- [ ] Candidate sorting updated to exclude volume.
