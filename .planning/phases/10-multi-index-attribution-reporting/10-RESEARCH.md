# Phase 10: Multi-Index Attribution - Research

**Phase**: 10
**Goal**: Research instrument-level segmentation for performance attribution.

## 1. Trade Logger Update Path
- **Current State**: `trade_log.csv` has `symbol` but no `underlying`.
- **Finding**: Adding an `underlying` column is safer than parsing symbols during every report generation.
- **Migration Plan**:
    - Update `TradeLogger.HEADERS` to include `'underlying'`.
    - Modify `log_entry` and `log_exit` to call `detect_underlying(trade.get('symbol'))`.
    - Modify `_write_row` to handle missing underlying values by parsing the symbol as a fallback (for legacy trades).

## 2. Performance Refactoring Path
- **Current State**: `calculate_advanced_stats` processes a single DataFrame of trades.
- **Segmentation Strategy**:
    - Create a wrapper `PerformanceReporter.calculate_segmented_stats(trades_df)`.
    - Loop logic:
        ```python
        for index_name in ['NIFTY', 'SENSEX', 'BANKNIFTY']:
            index_trades = trades_df[trades_df['underlying'] == index_name]
            stats[index_name] = self.calculate_advanced_stats(index_trades)
        ```
- **Charge Calculation**: Must confirm lot sizes in the refactor. NIFTY (varies), SENSEX (10), BANKNIFTY (varies).

## 3. Dashboard v2 Visualization
- **Layout**: Bootstrap 3-column row injected into the top of the HTML report.
- **Cards**:
    - **Header**: Index Name + Status (Active/Halted).
    - **Body**: Net P&L (bold), Win Rate %, Trade Count.
- **Heatmap (REQ-ATTR-03)**:
    - Use `plotly.express.density_heatmap` or `go.Heatmap`.
    - X: Date, Y: Index, Z: P&L.
    - Provide a toggle to switch between "Total P&L" and "Hit Rate" heatmaps.

## 4. Risks & Mitigations
- **Legacy Logs**: Old `trade_log.csv` files won't have the `underlying` column.
    - *Mitigation*: The `PerformanceReporter` will apply `detect_underlying` to the entire DF if the column is missing on load.
- **Plotly Bloat**: Adding 3 extra segmented charts + heatmap might slow down dashboard loading.
    - *Mitigation*: Use tabbed views or dropdown-based chart swapping to keep the DOM lean.

## 5. Validation Architecture
- **ATTR-01 (Segmentation)**: Verify `stats.json` contains a nested `segmented` key with accurate counts.
- **ATTR-02 (Cards)**: Grep HTML output for `card-title` containing NIFTY/SENSEX/BANKNIFTY.
- **ATTR-03 (Heatmap)**: Verify Plotly JSON in HTML includes a trace with `type: 'heatmap'`.

---
*Date: 2026-04-18*
