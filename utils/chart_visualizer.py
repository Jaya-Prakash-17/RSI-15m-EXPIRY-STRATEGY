"""
TradingView-Style Chart Visualizer
Creates candlestick chart with RSI subplot to verify trading signals

Usage:
    python utils/chart_visualizer.py <path_to_csv>

Example:
    python utils/chart_visualizer.py "data/derivatives/NIFTY/2025/NSE-NIFTY-30Dec25-26250-PE_15m.csv"
"""

import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from datetime import datetime

def calculate_rsi(prices, period=14):
    """Calculate RSI using Wilder's smoothing"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # First average (SMA)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    
    # Wilder's smoothing for subsequent values
    for i in range(period, len(prices)):
        avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (period - 1) + loss.iloc[i]) / period
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def plot_tradingview_chart(csv_path, output_path=None):
    """
    Create TradingView-style chart with candlesticks and RSI
    
    Args:
        csv_path: Path to derivative CSV file
        output_path: Path to save image (optional)
    """
    # Load data
    df = pd.read_csv(csv_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    # Calculate RSI if not present
    if 'rsi' not in df.columns and 'RSI' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'])
    else:
        # Normalize column name
        if 'RSI' in df.columns:
            df['rsi'] = df['RSI']
    
    # Add GREEN candle indicator
    df['isGreen'] = df['close'] > df['open']
    
    # Detect RSI crossovers
    df['prev_rsi'] = df['rsi'].shift(1)
    df['cross_above_60'] = (df['prev_rsi'] < 60) & (df['rsi'] >= 60)
    df['alert_candidate'] = df['cross_above_60'] & df['isGreen']
    
    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), 
                                    gridspec_kw={'height_ratios': [3, 1]},
                                    sharex=True)
    
    # Plot 1: Candlestick Chart
    for idx, row in df.iterrows():
        # Determine color
        color = 'green' if row['isGreen'] else 'red'
        edge_color = 'darkgreen' if row['isGreen'] else 'darkred'
        
        # Draw candle body
        height = abs(row['close'] - row['open'])
        bottom = min(row['open'], row['close'])
        
        # Create rectangle for body
        rect = Rectangle((idx, bottom), 0.6, height,
                         facecolor=color, edgecolor=edge_color, alpha=0.8)
        ax1.add_patch(rect)
        
        # Draw wick
        ax1.plot([idx + 0.3, idx + 0.3], [row['low'], row['high']], 
                color=edge_color, linewidth=1)
    
    # Mark alert points
    alerts = df[df['alert_candidate']]
    if not alerts.empty:
        ax1.scatter(alerts.index, alerts['high'], 
                   color='blue', marker='^', s=200, 
                   label='Alert (GREEN + RSI>60)', zorder=5)
    
    # Mark RSI crosses on RED candles (rejected)
    rejected = df[df['cross_above_60'] & ~df['isGreen']]
    if not rejected.empty:
        ax1.scatter(rejected.index, rejected['high'],
                   color='gray', marker='x', s=100,
                   label='RSI Cross (RED - ignored)', zorder=5)
    
    ax1.set_ylabel('Price', fontsize=12, fontweight='bold')
    ax1.set_title(f'TradingView-Style Chart: {os.path.basename(csv_path)}', 
                  fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: RSI
    ax2.plot(df.index, df['rsi'], color='purple', linewidth=2, label='RSI (14)')
    ax2.axhline(y=60, color='red', linestyle='--', label='Threshold (60)', linewidth=1.5)
    ax2.axhline(y=70, color='orange', linestyle=':', label='Overbought (70)', alpha=0.7)
    ax2.axhline(y=30, color='blue', linestyle=':', label='Oversold (30)', alpha=0.7)
    
    # Highlight RSI crossovers
    crosses = df[df['cross_above_60']]
    if not crosses.empty:
        ax2.scatter(crosses.index, crosses['rsi'], 
                   color='red', s=100, zorder=5)
    
    # Fill background for alert zones
    for idx, row in alerts.iterrows():
        ax2.axvspan(idx - 0.5, idx + 0.5, alpha=0.2, color='green')
    
    ax2.set_ylabel('RSI', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Candle Index', fontsize=12, fontweight='bold')
    ax2.set_ylim(0, 100)
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)
    
    # Add summary text
    num_alerts = len(alerts)
    num_rejected = len(rejected)
    summary = f"Total RSI Crosses: {len(crosses)} | GREEN Candles (Alerts): {num_alerts} | RED Candles (Ignored): {num_rejected}"
    fig.text(0.5, 0.02, summary, ha='center', fontsize=11, 
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    
    # Save or show
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"✅ Chart saved to: {output_path}")
    else:
        # Auto-generate output path
        base_name = os.path.basename(csv_path).replace('.csv', '')
        output_dir = os.path.dirname(csv_path)
        output_path = os.path.join(output_dir, f"{base_name}_chart.png")
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"✅ Chart saved to: {output_path}")
    
    plt.close()
    
    # Print summary
    print("\n" + "="*80)
    print("CHART ANALYSIS SUMMARY")
    print("="*80)
    print(f"Total Candles: {len(df)}")
    print(f"GREEN Candles: {df['isGreen'].sum()}")
    print(f"RED Candles: {(~df['isGreen']).sum()}")
    print(f"\nRSI Crossovers above 60: {len(crosses)}")
    print(f"  ✓ On GREEN candles (Alerts): {num_alerts}")
    print(f"  ✗ On RED candles (Ignored): {num_rejected}")
    print("="*80)
    
    if num_alerts > 0:
        print("\nAlert Details:")
        for idx, row in alerts.iterrows():
            print(f"  {row['datetime']} | Close: {row['close']:.2f} | RSI: {row['rsi']:.2f}")
    
    return output_path

def main():
    if len(sys.argv) < 2:
        print("❌ ERROR: No CSV file path provided")
        print("\nUsage: python utils/chart_visualizer.py <path_to_csv>")
        print("\nExamples:")
        print('  python utils/chart_visualizer.py "data/derivatives/NIFTY/2025/NSE-NIFTY-30Dec25-26250-PE_15m.csv"')
        print('  python utils/chart_visualizer.py "data/spot/NIFTY_15m.csv"')
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    if not os.path.exists(csv_path):
        print(f"❌ ERROR: File not found: {csv_path}")
        sys.exit(1)
    
    print("="*80)
    print("TRADINGVIEW-STYLE CHART GENERATOR")
    print("="*80)
    print(f"Input: {csv_path}")
    print("Generating chart...")
    
    try:
        output_path = plot_tradingview_chart(csv_path)
        print(f"\n✅ SUCCESS! Open the image file to view the chart.")
        print(f"\n📊 Chart location: {output_path}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
