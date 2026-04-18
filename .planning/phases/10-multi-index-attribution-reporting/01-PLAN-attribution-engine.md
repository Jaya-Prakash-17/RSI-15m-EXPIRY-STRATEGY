# PLAN: Multi-Index Attribution Engine

**Wave**: 1
**Depends on**: None
**Autonomous**: true
**Files modified**:
- `utils/trade_logger.py`
- `reporting/performance.py`
- `live/live_trader.py`

## Goal
Implement the core data structures and logic to segment performance metrics by instrument (NIFTY, SENSEX, BANKNIFTY) and option type (CE/PE).

## Requirements
- **ATTR-01**: Segment performance reports by instrument.
- **Decision (CONTEXT)**: Update `TradeLogger` with explicit `underlying` column.

## Tasks

### 1. Update TradeLogger Schema
<task>
<read_first>
- `utils/trade_logger.py`
</read_first>
<action>
1. Update `TradeLogger.HEADERS` to include `'underlying'` as the 5th column (after 'mode').
2. Modify `log_entry`, `log_exit`, and `log_partial_exit` to include the `underlying` key in the `row` dictionary.
3. Import `detect_underlying` from `utils.symbol_parser` to populate this key if it's missing from the `trade` dict.
</action>
<acceptance_criteria>
- `grep "'underlying'" utils/trade_logger.py` returns the new header.
- New trade logs created by the bot contain the instrument name (e.g., NIFTY) in the 5th column.
</acceptance_criteria>
</task>

### 2. LiveTrader Integration
<task>
<read_first>
- `live/live_trader.py`
</read_first>
<action>
Ensure all calls to `self.trade_logger.log_*` methods implicitly or explicitly pass a trade dictionary that contains the `underlying` key (which is already present in `trade_record` logic).
</action>
<acceptance_criteria>
- `live_trader.py` calls to logger methods function without errors (verified by running a mock log entry).
</acceptance_criteria>
</task>

### 3. PerformanceReporter Ingestion Upgrade
<task>
<read_first>
- `reporting/performance.py`
- `utils/symbol_parser.py`
</read_first>
<action>
1. Update `load_trades()`: After reading the CSV, check if the `'underlying'` column exists.
2. If missing (legacy log), apply `SymbolParser.detect_underlying` to the `'symbol'` column to create it.
3. Ensure the column is present before any calculations begin.
</action>
<acceptance_criteria>
- `performance.py` can process a `trade_log.csv` that lacks the `underlying` column by self-repairing the dataframe in memory.
</acceptance_criteria>
</task>

### 4. Segmented Stats Calculation
<task>
<read_first>
- `reporting/performance.py`
- `utils/symbol_parser.py`
</read_first>
<action>
1. Modify `calculate_advanced_stats` to accept an optional `underlying` filter.
2. Implement a loop that iterates through all unique instruments found in the trades dataframe.
3. Calculate stats for each group and store them in a nested dictionary: `self.stats['segmented'][instrument_name]`.
4. Include Option Type (CE/PE) segmentation within each instrument group using `SymbolParser.parse_opt_type`.
</action>
<acceptance_criteria>
- `stats.json` (if output) contains a `segmented` section with NIFTY, SENSEX, and BANKNIFTY keys.
- Win rates and P&L sums for each segment match the global total.
</acceptance_criteria>
</task>

## Verification
- Run a report on a sample log file containing mixed instruments.
- Check generated `stats.json` for segmented data integrity.
