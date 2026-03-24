#!/bin/bash
# scripts/check_bot.sh — P-04
# Quick health check: reads the heartbeat file written by the bot every 60s.
# Run: bash scripts/check_bot.sh

HEARTBEAT=/tmp/rsi_bot_heartbeat.json

if [ -f "$HEARTBEAT" ]; then
    python3 -c "
import json, datetime
with open('$HEARTBEAT') as f:
    h = json.load(f)
age = (datetime.datetime.now() - datetime.datetime.fromisoformat(h['timestamp'])).seconds
status = 'ALIVE' if age < 120 else 'STALE'
paper = '(PAPER)' if h.get('paper_trading') else '(LIVE!!!)'
uptime_min = int(h.get('uptime_seconds', 0)) // 60
print(f'Bot {status} {paper} | Last seen {age}s ago | P\&L: Rs.{h[\"daily_pnl\"]} | Trades: {h[\"active_trades\"]} | Uptime: {uptime_min}m')"
else
    echo "Bot NOT running (no heartbeat file found at $HEARTBEAT)"
fi
