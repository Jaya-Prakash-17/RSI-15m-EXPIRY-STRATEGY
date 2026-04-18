
import os
import sys
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

def calculate_rsi(series, period=11):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    # Wilder's smoothing Parity
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def generate_inspector_dashboard(summary_json_path):
    """
    Builds a Visual Trade Inspector Dashboard with Boxes and Line Segments.
    """
    if not os.path.exists(summary_json_path):
        print(f"Error: Summary file {summary_json_path} not found.")
        return

    base_name = os.path.basename(summary_json_path).replace(".json", "")
    output_dir = os.path.join("reports", "inspection")
    os.makedirs(output_dir, exist_ok=True)
    output_html = os.path.join(output_dir, f"inspection-{base_name}.html")

    with open(summary_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    trades = data.get('trades', [])
    if not trades:
        print("No trades found in summary.")
        return

    html_content = [
        "<html><head><title>Visual Trade Inspector</title>",
        "<style>",
        "body { font-family: 'Inter', sans-serif; background-color: #0c0d10; color: #d1d4dc; padding: 20px; }",
        ".trade-row { display: flex; gap: 20px; margin-bottom: 50px; background: #131722; border: 1px solid #2a2e39; border-radius: 8px; padding: 15px; }",
        ".chart-col { flex: 3; }",
        ".stats-col { flex: 1; padding: 20px; background: #1e222d; border-radius: 6px; }",
        ".stat-item { display: flex; justify-content: space-between; font-size: 13px; border-bottom: 1px solid #2a2e39; padding: 8px 0; }",
        ".stat-label { color: #787b86; } .stat-value { color: #f2f3f5; font-weight: 600; }",
        ".pnl-pos { color: #089981; } .pnl-neg { color: #f23645; }",
        "</style></head><body>",
        f"<h1>Inspection: {base_name}</h1>"
    ]

    for i, trade in enumerate(trades):
        symbol = trade['symbol']
        underlying = trade['underlying']
        alert_time = pd.to_datetime(trade['entry_candle_datetime'])
        entry_time = pd.to_datetime(trade['entry_time'])
        exit_time = pd.to_datetime(trade['exit_time'])

        csv_path = f"data/derivatives/{underlying}/{entry_time.year}/{symbol}_15m.csv"
        if not os.path.exists(csv_path):
            html_content.append(f"<div class='trade-row'>Error: Data for {symbol} missing</div>")
            continue

        df = pd.read_csv(csv_path)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        df['RSI'] = calculate_rsi(df['close'], period=11)

        idx_alert = df[df['datetime'] <= alert_time].index.max()
        idx_entry = df[df['datetime'] <= entry_time].index.max()
        idx_exit = df[df['datetime'] >= exit_time].index.min()

        start_idx = max(0, idx_alert - 20)
        end_idx = min(len(df) - 1, idx_exit + 10)
        plot_df = df.iloc[start_idx:end_idx+1].copy()

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])

        # Candles
        fig.add_trace(go.Candlestick(
            x=plot_df['datetime'], open=plot_df['open'], high=plot_df['high'],
            low=plot_df['low'], close=plot_df['close'],
            increasing_line_color='#089981', decreasing_line_color='#f23645',
            increasing_fillcolor='#089981', decreasing_fillcolor='#f23645',
            line=dict(width=1),
            name="Price"
        ), row=1, col=1)

        # 1. Alert Highlight (Orange Box)
        alert_candle = df.loc[idx_alert]
        fig.add_shape(
            type="rect",
            x0=alert_candle['datetime'], x1=alert_candle['datetime'],
            y0=alert_candle['low'], y1=alert_candle['high'],
            line=dict(color="#fb923c", width=3), fillcolor="rgba(251, 146, 60, 0.2)",
            row=1, col=1
        )

        # Formatting for categoric axis alignment
        entry_ts = entry_time.strftime('%Y-%m-%d %H:%M:%S')
        exit_ts = exit_time.strftime('%Y-%m-%d %H:%M:%S')
        # Right edge of chart for horizontal rays
        ray_end_ts = plot_df['datetime'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S')

        # 2. Entry Point — TradingView-style filled triangle (up)
        fig.add_trace(go.Scatter(
            x=[entry_ts], y=[trade['entry_price']],
            mode="markers+text",
            marker=dict(symbol="triangle-up", size=16, color="#26a69a",
                        line=dict(width=0)),
            text=["ENTRY"], textposition="bottom center",
            textfont=dict(color="#26a69a", size=11, family="Inter"),
            name="Entry", hovertemplate=f"Entry: ₹{trade['entry_price']:.2f}<extra></extra>"
        ), row=1, col=1)

        # 3. Exit Point — filled triangle (down), color by P&L
        exit_won = trade.get('pnl_net', 0) > 0
        exit_color = "#26a69a" if exit_won else "#ef5350"
        fig.add_trace(go.Scatter(
            x=[exit_ts], y=[trade['exit_price']],
            mode="markers+text",
            marker=dict(symbol="triangle-down", size=16, color=exit_color,
                        line=dict(width=0)),
            text=[f"EXIT ({trade['reason']})"], textposition="top center",
            textfont=dict(color=exit_color, size=11, family="Inter"),
            name="Exit", hovertemplate=f"Exit: ₹{trade['exit_price']:.2f}<extra></extra>"
        ), row=1, col=1)

        # 4. SL Horizontal Ray — extends from entry to chart right edge
        fig.add_shape(
            type="line", x0=entry_ts, x1=ray_end_ts,
            y0=trade['sl'], y1=trade['sl'],
            line=dict(color="#ef5350", width=1.5, dash="dash"),
            row=1, col=1
        )
        # SL price label on the right edge
        fig.add_annotation(
            x=ray_end_ts, y=trade['sl'],
            text=f"  SL ₹{trade['sl']:.1f}", showarrow=False,
            xanchor="left", font=dict(color="#ef5350", size=10),
            bgcolor="rgba(239,83,80,0.15)", borderpad=2,
            row=1, col=1
        )

        # TP Horizontal Rays — each extends from entry to right edge
        if 'targets' in trade:
            tp_colors = ["#26a69a", "#66bb6a", "#81c784"]
            for j, tgt in enumerate(trade['targets']):
                tpc = tp_colors[j % len(tp_colors)]
                fig.add_shape(
                    type="line", x0=entry_ts, x1=ray_end_ts,
                    y0=tgt, y1=tgt,
                    line=dict(color=tpc, width=1.5, dash="dash"),
                    row=1, col=1
                )
                fig.add_annotation(
                    x=ray_end_ts, y=tgt,
                    text=f"  TP{j+1} ₹{tgt:.1f}", showarrow=False,
                    xanchor="left", font=dict(color=tpc, size=10),
                    bgcolor=f"rgba(38,166,154,0.15)", borderpad=2,
                    row=1, col=1
                )

        # 5. Entry price ray (subtle reference line)
        fig.add_shape(
            type="line", x0=entry_ts, x1=ray_end_ts,
            y0=trade['entry_price'], y1=trade['entry_price'],
            line=dict(color="rgba(255,255,255,0.12)", width=1, dash="dot"),
            row=1, col=1
        )
        # 6. Connecting Line (trade duration flow)
        fig.add_shape(
            type="line", x0=entry_ts, x1=exit_ts,
            y0=trade['entry_price'], y1=trade['exit_price'],
            line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dot"),
            row=1, col=1
        )

        # RSI
        fig.add_trace(go.Scatter(x=plot_df['datetime'], y=plot_df['RSI'],
                                 line=dict(color='#7e57c2', width=1.5),
                                 name="RSI"), row=2, col=1)
        for lvl in [30, 40, 50, 60, 70]:
            fig.add_hline(y=lvl, line=dict(color='#2a2e39', width=1, dash='dot'), row=2, col=1)

        # RSI range coloring
        fig.add_hrect(y0=40, y1=60, fillcolor="rgba(126, 87, 194, 0.05)", line_width=0, row=2, col=1)

        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722",
            height=600, margin=dict(l=10, r=40, t=10, b=10),
            xaxis_rangeslider_visible=False, xaxis_type='category', showlegend=False
        )
        fig.update_yaxes(side="right", gridcolor='#2a2e39')

        chart_html = fig.to_html(full_html=False, include_plotlyjs='cdn' if i == 0 else False)
        pnl_class = "pnl-pos" if trade.get('pnl_net', 0) >= 0 else "pnl-neg"

        # Format targets if multi-lot
        target_html = ""
        if 'targets' in trade and isinstance(trade['targets'], list):
            for j, t in enumerate(trade['targets']):
                target_html += f'<div class="stat-item"><span class="stat-label">Target {j+1}</span><span class="stat-value">₹{t:.2f}</span></div>'

        trade_html = f"""
        <div class="trade-row">
            <div class="chart-col">{chart_html}</div>
            <div class="stats-col">
                <h2 style="margin-top:0; color:#ffd700;">{symbol}</h2>
                <div style="margin-bottom:15px; font-size:12px; color:#8892b0;">Trade #{i+1}</div>

                <div class="stat-item"><span class="stat-label">Alert Candle</span><span class="stat-value">{trade.get('entry_candle_datetime', 'N/A')}</span></div>
                <div class="stat-item"><span class="stat-label">Alert Range</span><span class="stat-value" style="color:#fb923c;">₹{alert_candle['low']:.2f} - ₹{alert_candle['high']:.2f}</span></div>
                <div class="stat-item"><span class="stat-label">Entry Time</span><span class="stat-value">{trade.get('entry_time', 'N/A')}</span></div>
                <div class="stat-item"><span class="stat-label">Entry Price</span><span class="stat-value">₹{trade.get('entry_price', 0):.2f}</span></div>

                <div style="margin: 10px 0; border-top: 1px dashed #2a2e39;"></div>

                <div class="stat-item"><span class="stat-label">Stop Loss</span><span class="stat-value" style="color:#ff4757;">₹{trade.get('sl', 0):.2f}</span></div>
                {target_html}

                <div style="margin: 10px 0; border-top: 1px dashed #2a2e39;"></div>

                <div class="stat-item"><span class="stat-label">Exit Time</span><span class="stat-value">{trade.get('exit_time', 'N/A')}</span></div>
                <div class="stat-item"><span class="stat-label">Exit Price</span><span class="stat-value">₹{trade.get('exit_price', 0):.2f}</span></div>
                <div class="stat-item"><span class="stat-label">Reason</span><span class="stat-value">{trade.get('reason', 'N/A')}</span></div>
                <div class="stat-item"><span class="stat-label">Quantity</span><span class="stat-value">{trade.get('qty', 0)}</span></div>

                <div style="margin: 15px 0; padding:10px; background:#0f3460; border-radius:4px; text-align:center;">
                    <div class="stat-label" style="font-size:11px; margin-bottom:5px;">NET PNL</div>
                    <div class="stat-value {pnl_class}" style="font-size:20px;">₹{trade.get('pnl_net', 0):,.2f}</div>
                </div>
            </div>
        </div>
        """
        html_content.append(trade_html)

    html_content.append("</body></html>")
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write("\n".join(html_content))
    print(f"DONE: Inspection report saved to {output_html}")
    return output_html

if __name__ == "__main__":
    report = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        report = arg if os.path.exists(arg) else os.path.join("reports", arg)
    if not report:
        files = [os.path.join("reports", f) for f in os.listdir("reports") if f.endswith("_summary.json")]
        if files: report = max(files, key=os.path.getctime)
    if report: generate_inspector_dashboard(report)
