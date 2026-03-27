# RSI-15m EXPIRY BREAKOUT BOT
## PAPER TRADING VALIDATION CHECKLIST

---

## PRE-SESSION CHECKLIST (run before each paper session)

[ ] **Groww API credentials not expired**
    Command: `python -c "from core.groww_client import GrowwClient; print('Balance:', GrowwClient().get_balance())"`
    Expected: prints a ₹ balance, not None or error

[ ] **Telegram working**
    Command: `python -c "from dotenv import load_dotenv; load_dotenv(); from utils.telegram_notifier import TelegramNotifier; TelegramNotifier().test_connection()"`
    Expected: receive "✅ TEST — Telegram is working!" on your phone

[ ] **Bot starts cleanly**
    Command: `python run_live.py`
    Expected: no CRITICAL errors, "✓ Configuration validation passed"
    Expected: Telegram receives "🤖 BOT STARTED [PAPER]"

[ ] **Config correct**
    Command: `python -c "import yaml; c=yaml.safe_load(open('config.yaml')); print('paper:', c['trading']['paper_trading'], '| lots:', c['strategy']['lots_per_trade'], '| max_loss:', c['risk']['max_loss_per_day'])"`
    Expected: paper: True | lots: 1 | max_loss: 5000

---

## DURING-SESSION MONITORING

[ ] **Check heartbeat is alive** (every 30 min while monitoring)
    Command: `powershell -Command "Get-Content -Path 'live_trading.log' -Tail 20 | Select-String 'Polling'"`
    Expected: Shows recent activity logs

[ ] **Kill switch works** (test on first session only)
    Command: `touch /tmp/rsi_bot_kill`
    Expected: Bot logs "KILL SWITCH ACTIVATED", sends Telegram, exits gracefully
    After test: restart bot for rest of session

---

## POST-SESSION CHECKLIST

[ ] **Daily summary Telegram received**
    Expected: "📋 DAILY SUMMARY" with trades/wins/losses/P&L

[ ] **No unhandled exceptions in logs**
    Command: `Select-String -Path "live_trading.log" -Pattern "Traceback|Exception|ERROR" | Measure-Object | Select-Object -Property Count`
    Target: 0 unhandled exceptions

[ ] **Run reconciliation**
    Command: `python daily_reconcile.py`
    Expected: prints bot P&L for today, sends Telegram

[ ] **Review log for warnings**
    Command: `Select-String -Path "live_trading.log" -Pattern "WARNING|CRITICAL" | Select-Object -Last 20`

---

## GRADUATION CRITERIA (when to go live)

Go live when ALL of the following are true:
* [ ] 20 paper sessions completed
* [ ] Zero unhandled exceptions across all sessions
* [ ] Backtest shows 20+ trades with positive expectancy
* [ ] Telegram alerts received correctly in every session
* [ ] Daily reconcile runs without errors in every session
* [ ] Kill switch tested and confirmed working
* [ ] You've watched 5 sessions manually from open to close
* [ ] You understand what happens at 15:25 (Groww squares off first at 15:20)

---

## LIVE TRADING DEBUT SETTINGS

When first going live, use these settings:
```yaml
trading:
  paper_trading: false    # THE ONLY CHANGE
strategy:
  lots_per_trade: 1       # stay at 1 for first 20 live sessions
risk:
  max_loss_per_day: 2000  # tighter limit for first week
```

---

## EMERGENCY PROCEDURE

If something goes wrong during live trading:

**Step 1 (fastest):** `touch /tmp/rsi_bot_kill`
Bot will square off or notify and shut down as configured.

**Step 2 (if bot is unresponsive):** Kill the process via Terminal (Ctrl+C).

**Step 3 (last resort):** 
1. Open Groww app → Portfolio → F&O Positions.
2. Manually square off any open positions.
3. Set limit/market sell order for each open option lot.
