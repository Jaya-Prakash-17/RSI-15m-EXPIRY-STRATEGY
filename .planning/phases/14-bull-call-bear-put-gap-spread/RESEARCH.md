# Gap Directional Spread Backtest (Bull Call / Bear Put)

## Logic
1. **Gap Check**:
   - Gap Up / Neutral: `Today_Open_0915 >= Yesterday_Close_1515` -> **Bull Call Spread**
   - Gap Down: `Today_Open_0915 < Yesterday_Close_1515` -> **Bear Put Spread**

2. **Strategy Legs**:
   - **Bull Call Spread**: Buy exactly 1 lot ATM CE, Sell exactly 1 lot OTM CE (5 strikes away, i.e., +250 points for NIFTY).
   - **Bear Put Spread**: Buy exactly 1 lot ATM PE, Sell exactly 1 lot OTM PE (5 strikes away, i.e., -250 points for NIFTY).

3. **Execution Times**:
   - Determine direction at 9:15 AM (after gap is observed). Wait, user says "do this everyday 945 am". So we determine direction using 9:15 open vs yesterday close, but execute at 9:45 AM using the 9:45 AM spot price to calculate ATM? "if gap-up/neutral then atm ce buy ; 5 streks otm ce sell... do this everyday 945 am"
   - Direction rule: `Today_Open(9:15) vs Yesterday_Close`.
   - Entry rule: At 9:45 AM, calculate ATM based on `Spot(9:45)`. Execute the spread based on the direction determined earlier.
   - Exit rule: At 3:15 PM, square off.

## Reporting
- Use `PerformanceReporter(custom_prefix="GAP_SPREAD_5Yr")`.
