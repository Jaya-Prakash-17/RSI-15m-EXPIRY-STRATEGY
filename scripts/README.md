# Scripts

Operational and deployment scripts for the RSI-15m Bot.

| File | Purpose |
|---|---|
| `setup_service.sh` | **Service Installer.** Configures the RSI bot as a systemd service (Linux/VPS). Handles auto-restart and log rotation. |
| `check_bot.sh` | **Health Monitor.** Quick script to check if the bot process is running and grep latest logs. |
| `rsi-bot.service` | **Service Template.** Standard systemd unit file with environment variable pass-through. |
| `paper_trading_checklist.md` | **SOP Checklist.** Comprehensive 20-session paper trading cycle checklist to ensure production readiness before live trading. |

## Deployment (Linux)

To run the bot 24/7 on a VPS:

```bash
chmod +x scripts/setup_service.sh
sudo ./scripts/setup_service.sh
```

This will create a service named `rsi-bot.service`. You can then manage it with:

```bash
sudo systemctl status rsi-bot
sudo systemctl restart rsi-bot
```
