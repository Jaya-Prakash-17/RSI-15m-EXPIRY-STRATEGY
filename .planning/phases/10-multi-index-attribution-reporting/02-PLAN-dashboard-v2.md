# PLAN: Dashboard v2 - Segmented Analytics

**Wave**: 2
**Depends on**: 01-PLAN-attribution-engine.md
**Autonomous**: true
**Files modified**:
- `reporting/performance.py`

## Goal
Upgrade the HTML report template to include instrument-level performance cards and a P&L heatmap.

## Requirements
- **ATTR-02**: Add "Trade Count" and "Win Rate" cards per index.
- **ATTR-03**: Implement instrument-specific P&L heatmaps.

## Tasks

### 1. Unified Summary Grid
<task>
<read_first>
- `reporting/performance.py`
</read_first>
<action>
1. Update the `_generate_html_report` method (or equivalent template section).
2. Insert a Bootstrap `row` above the main stats table.
3. For each active instrument (NIFTY, SENSEX, BANKNIFTY), generate a `col-md-4` card containing:
    - Instrument Name
    - Net P&L (Color-coded: Green for positive, Red for negative)
    - Win % (Progress bar or text)
    - Total Trades
</action>
<acceptance_criteria>
- Opening the generated HTML report shows 3 distinct cards at the top.
- Data in cards matches the segmented stats calculated in Plan 01.
</acceptance_criteria>
</task>

### 2. P&L Heatmap Implementation
<task>
<read_first>
- `reporting/performance.py`
</read_first>
<action>
1. Implement `_create_pnl_heatmap(self, trades_df)` using `plotly.graph_objects.Heatmap`.
2. Group trades by 'Date' and 'Underlying'.
3. Color scale: `RdYlGn` (Red-Yellow-Green).
4. Integrate this chart into the HTML report body.
</action>
<acceptance_criteria>
- Report contains a heatmap chart titled "P&L Attribution Heatmap".
- Hovering over cells shows Date, Instrument, and Total P&L for that day.
</acceptance_criteria>
</task>

### 3. Option Type Bias Analysis
<task>
<read_first>
- `reporting/performance.py`
</read_first>
<action>
1. Add a small table or pie chart showing CE vs PE performance contribution across the whole portfolio.
2. This fulfills the "discretionary" decision to detect directional bias.
</action>
<acceptance_criteria>
- Report includes a section showing "Directional Bias (CE vs PE)".
</acceptance_criteria>
</task>

## Verification
- Generate a full report (`python reporting/performance.py`).
- Inspect `reports/performance_latest.html` for layout correctness and chart interactivity.
