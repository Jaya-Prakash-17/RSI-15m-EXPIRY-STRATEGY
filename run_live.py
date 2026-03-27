# run_live.py
import yaml
import logging
import sys
import signal
import os
try:
    import fcntl
except ImportError:
    fcntl = None  # Fallback for Windows
import atexit
from logging.handlers import RotatingFileHandler
from datetime import datetime
from live.live_trader import LiveTrader

LOCK_FILE = "/tmp/rsi_bot_live.lock"
_lock_fd = None  # module-level reference to prevent GC closing the lock

def acquire_single_instance_lock():
    """
    Ensures only one instance of the bot can run at a time.
    Uses an exclusive file lock — automatically released when the process exits.
    Raises SystemExit if another instance is already running.
    """
    global _lock_fd
    try:
        # Create directory if it doesn't exist (handle non-standard systems)
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        _lock_fd = open(LOCK_FILE, 'w')
        
        if fcntl:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt
            msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            
        _lock_fd.write(f"{os.getpid()}\n")
        _lock_fd.flush()

        def release_lock():
            global _lock_fd
            if _lock_fd:
                try:
                    if fcntl: fcntl.flock(_lock_fd, fcntl.LOCK_UN)
                    else:
                        import msvcrt
                        _lock_fd.seek(0)
                        msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                    _lock_fd.close()
                except Exception: pass
            if os.path.exists(LOCK_FILE):
                try: os.unlink(LOCK_FILE)
                except Exception: pass
        
        atexit.register(release_lock)
        return _lock_fd
    except (IOError, OSError) as e:
        # Lock already held by another process or lock not available
        try:
            with open(LOCK_FILE) as f:
                existing_pid = f.read().strip()
        except Exception:
            existing_pid = "unknown"
            
        print(
            f"\n❌ ERROR: Another instance of the RSI bot is already running (PID: {existing_pid}).\n"
            f"   If you are sure no other instance is running, delete the lock file:\n"
            f"   rm {LOCK_FILE}\n"
            f"   Then restart the bot.\n"
        )
        sys.exit(1)

# Global trader instance for graceful shutdown
trader_instance = None

def setup_logging(log_file="live_trading.log"):
    """Configure logging with rotation to prevent disk fill."""
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Rotating file handler: 50 MB per file, keep last 10 = 500 MB max
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=50 * 1024 * 1024,   # 50 MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setFormatter(fmt)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

def validate_environment():
    """Validate environment before starting live trading."""
    logger = logging.getLogger("LiveRunner")
    
    # Check for .env file
    if not os.path.exists(".env"):
        logger.critical("CRITICAL: .env file not found! Create .env with GROWW_API_KEY and GROWW_API_SECRET")
        return False
    
    # Check for required environment variables
    api_key = os.getenv("GROWW_API_KEY")
    api_secret = os.getenv("GROWW_API_SECRET")
    
    if not api_key or not api_secret:
        logger.critical("CRITICAL: GROWW_API_KEY and GROWW_API_SECRET must be set in .env file")
        return False
    
    logger.info("✓ Environment validation passed")
    return True

def validate_config(config):
    """Validate configuration file for structural and safety-critical values."""
    logger = logging.getLogger("LiveRunner")

    # ── Section presence ──────────────────────────────────────────────────────
    required_keys = ['trading', 'strategy', 'capital', 'risk', 'indices', 'data']
    for key in required_keys:
        if key not in config:
            logger.critical(f"CRITICAL: Missing required config section: '{key}'")
            return False

    if 'window' not in config['trading']:
        logger.critical("CRITICAL: Missing trading.window in config")
        return False

    # ── RSI / alert basics ────────────────────────────────────────────────────
    if config['strategy'].get('rsi', {}).get('period', 0) <= 0:
        logger.critical("CRITICAL: strategy.rsi.period must be > 0")
        return False

    if config['strategy'].get('alert_validity', 0) <= 0:
        logger.critical("CRITICAL: strategy.alert_validity must be > 0")
        return False

    # ── Risk limits ───────────────────────────────────────────────────────────
    if config['risk'].get('max_loss_per_day', 0) <= 0:
        logger.critical("CRITICAL: risk.max_loss_per_day must be > 0")
        return False

    # ── Strategy parameters ───────────────────────────────────────────────────
    if config['strategy'].get('lots_per_trade', 0) <= 0:
        logger.critical("CRITICAL: strategy.lots_per_trade must be > 0")
        return False

    if config['strategy'].get('single_lot_exit_target', 0) not in {1, 2, 3}:
        logger.critical("CRITICAL: strategy.single_lot_exit_target must be 1, 2, or 3")
        return False

    if config['strategy'].get('exit_mode') not in {'single_lot', 'multi_lot'}:
        logger.critical("CRITICAL: strategy.exit_mode must be 'single_lot' or 'multi_lot'")
        return False

    # ── Trading window order and Groww MIS cutoff ─────────────────────────────
    try:
        win = config['trading']['window']
        start  = datetime.strptime(win['start'],            "%H:%M")
        end    = datetime.strptime(win['end'],              "%H:%M")
        sq_off = datetime.strptime(win['auto_square_off'],  "%H:%M")

        if not (start < end <= sq_off):
            logger.critical(
                "CRITICAL: Trading window order invalid. "
                "Must satisfy: start < end <= auto_square_off"
            )
            return False

        sq_off_hard_limit = datetime.strptime("15:30", "%H:%M")  # market close
        sq_off_warn_limit = datetime.strptime("15:20", "%H:%M")  # Groww MIS cutoff
        
        if sq_off > sq_off_hard_limit:
            logger.critical(
                f"CRITICAL: auto_square_off ({win['auto_square_off']}) "
                f"is after market close (15:30). This is invalid."
            )
            return False
        
        if sq_off > sq_off_warn_limit:
            logger.warning(
                f"WARNING: auto_square_off ({win['auto_square_off']}) is after "
                f"Groww's 15:20 MIS auto-close. Groww will square off positions "
                f"before the bot does. Bot's square-off serves as a P&L recording "
                f"step only. Continuing."
            )
            # Do NOT return False — this is an accepted risk, not an error
    except (KeyError, ValueError) as e:
        logger.critical(f"CRITICAL: Invalid time format in trading.window: {e}")
        return False

    # ── Lot sizes ─────────────────────────────────────────────────────────────
    for idx, details in config.get('indices', {}).items():
        if details.get('lot_size', 0) <= 0:
            logger.critical(f"CRITICAL: indices.{idx}.lot_size must be > 0")
            return False

    # ── paper_trading must be a boolean ──────────────────────────────────────
    paper = config['trading'].get('paper_trading')
    if not isinstance(paper, bool):
        logger.critical(
            f"CRITICAL: trading.paper_trading must be true/false (boolean), "
            f"got: {type(paper).__name__}"
        )
        return False

    # ── P-26: RSI threshold valid range (0 < x < 100) ────────────────────────
    rsi_threshold = config['strategy'].get('rsi', {}).get('threshold', 60)
    if not (0 < rsi_threshold < 100):
        logger.critical(f"CRITICAL: rsi.threshold must be 0-100, got {rsi_threshold}")
        return False

    # ── P-26: min_sl_pct realistic range (1% – 50%) ──────────────────────────
    min_sl_pct = config['strategy'].get('min_sl_pct', 0.08)
    if not (0.01 <= min_sl_pct <= 0.50):
        logger.critical(
            f"CRITICAL: min_sl_pct must be 0.01-0.50 (1%-50%), got {min_sl_pct:.2%}"
        )
        return False

    # ── P-26: warmup_periods > rsi_period (hard fail) ────────────────────────
    warmup = config['strategy'].get('rsi', {}).get('warmup_periods', 0)
    period = config['strategy'].get('rsi', {}).get('period', 0)
    if warmup < period + 1:
        logger.critical(
            f"CRITICAL: rsi.warmup_periods ({warmup}) must be > rsi.period ({period}). "
            f"Minimum: {period + 1}"
        )
        return False

    min_candles = config['strategy'].get('rsi', {}).get('min_candles_for_signal', period * 3)
    if min_candles < period * 2:
        logger.warning(
            f"WARNING: min_candles_for_signal ({min_candles}) < 2×period ({period*2}). "
            f"RSI signals may be unreliable."
        )

    logger.info("✓ Configuration validation passed")
    return True

def validate_system_clock(logger) -> bool:
    """P-13: Validate server clock is within 60s of actual IST using worldtimeapi.org."""
    import urllib.request, json as _json
    try:
        url = "http://worldtimeapi.org/api/timezone/Asia/Kolkata"
        req = urllib.request.Request(url, headers={'User-Agent': 'RSI-Bot/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
        api_time = datetime.fromisoformat(data['datetime'][:19])
        local_time = datetime.now()
        drift = abs((api_time - local_time).total_seconds())
        if drift > 60:
            logger.critical(
                f"CLOCK DRIFT: {drift:.0f}s off IST. "
                f"Local={local_time.strftime('%H:%M:%S')} "
                f"IST={api_time.strftime('%H:%M:%S')}. "
                f"Fix: sudo ntpdate pool.ntp.org"
            )
            return False
        logger.info(f"\u2713 Clock validated (drift: {drift:.1f}s)")
        return True
    except Exception as e:
        logger.warning(f"Clock validation unavailable: {e}. Continuing.")
        return True   # Don't block startup if API is unreachable

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    logger = logging.getLogger("LiveRunner")
    logger.info("Interrupted by user (Ctrl+C). Shutting down...")
    
    # Notify owner via Telegram
    global trader_instance
    if trader_instance and hasattr(trader_instance, 'telegram'):
        trader_instance.telegram.alert_manual_shutdown()
    
    logger.info("Alert sent to owner. Trades remain OPEN for manual management. Exiting.")
    sys.exit(0)

def main():
    global trader_instance
    
    # Ensure only one instance runs
    acquire_single_instance_lock()
    
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    setup_logging()
    logger = logging.getLogger("LiveRunner")
    
    logger.info("=" * 60)
    logger.info(" LIVE TRADING BOT - STARTING")
    logger.info("=" * 60)
    
    # Validate environment
    if not validate_environment():
        logger.critical("Environment validation failed. Exiting.")
        sys.exit(1)
    
    # Load configuration
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Failed to load config.yaml: {e}")
        sys.exit(1)
    
    # Validate configuration
    if not validate_config(config):
        logger.critical("Configuration validation failed. Exiting.")
        sys.exit(1)

    # P-13: Validate system clock is within 60s of IST
    if not validate_system_clock(logger):
        logger.critical("System clock drift detected. Fix before trading. Exiting.")
        sys.exit(1)

    # Initialize LiveTrader
    try:
        logger.info("Initializing Live Trader...")
        trader_instance = LiveTrader(config)
        logger.info("✓ Live Trader initialized successfully")
    except Exception as e:
        logger.critical(f"Failed to initialize Live Trader: {e}")
        sys.exit(1)

    # API Health Check — verify Groww connection before entering the trading loop.
    # Paper trading mode also requires a live connection for LTP polling, so we
    # always check, regardless of paper_trading flag (SEC-002).
    logger.info("Verifying Groww API connection...")
    try:
        balance = trader_instance.client.get_balance()
        if balance is None:
            logger.critical("CRITICAL: Groww API returned None balance. Check credentials.")
            logger.critical("Ensure GROWW_API_KEY is valid and not expired (tokens expire daily).")
            sys.exit(1)
        logger.info(f"✅ Groww API connected. Available margin: ₹{balance:,.0f}")
    except Exception as e:
        logger.critical(f"CRITICAL: Cannot connect to Groww API: {e}")
        logger.critical("Check GROWW_API_KEY in .env file. Exiting.")
        sys.exit(1)

   # Final confirmation
    logger.warning("=" * 60)
    logger.warning(" ⚠️  LIVE TRADING MODE - REAL MONEY AT RISK")
    logger.warning("=" * 60)
    logger.warning(f" Trading Window: {config['trading']['window']['start']} - {config['trading']['window']['end']}")
    logger.warning(f" Max Loss Per Day: ₹{config['risk']['max_loss_per_day']}")
    logger.warning(f" Capital: ₹{config['capital']['initial']}")
    logger.warning("=" * 60)
    
    # Run trading bot
    try:
        logger.info("Starting trading loop...")
        trader_instance.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C). Shutting down...")
        if hasattr(trader_instance, 'telegram'):
            trader_instance.telegram.alert_manual_shutdown()
        logger.info("Alert sent to owner. Trades remain open.")
    except Exception as e:
        logger.critical(f"Fatal error in trading loop: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("=" * 60)
        logger.info(" LIVE TRADING SESSION ENDED")
        logger.info("=" * 60)

if __name__ == "__main__":
    main()
