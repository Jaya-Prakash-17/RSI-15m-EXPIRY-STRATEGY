#!/bin/bash
# scripts/setup_service.sh — P-04
# Sets up the RSI bot as a systemd service that auto-restarts on crash.
# Run as root (or with sudo) on Ubuntu/Debian.

# ── REPLACE THESE PLACEHOLDERS ────────────────────────────────
PROJECT_DIR="/PLACEHOLDER/PROJECT_DIR"    # e.g., /home/ubuntu/EXPIRY_RSI_15M_STRATEGY
SERVICE_NAME="rsi-bot"

# ── Install the service ────────────────────────────────────────
echo "Installing systemd service..."
cp "$PROJECT_DIR/scripts/rsi-bot.service" /etc/systemd/system/$SERVICE_NAME.service

# ── Reload, enable, start ─────────────────────────────────────
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

# ── Show status ───────────────────────────────────────────────
echo ""
echo "=== Service Status ==="
systemctl status $SERVICE_NAME --no-pager
echo ""
echo "Useful commands:"
echo "  journalctl -u $SERVICE_NAME -f          # Live log streaming"
echo "  systemctl stop $SERVICE_NAME            # Graceful stop (SIGTERM → squares off)"
echo "  systemctl restart $SERVICE_NAME         # Restart bot"
echo "  systemctl disable $SERVICE_NAME         # Disable autostart on boot"
