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
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(f"{os.getpid()}\n")
        _lock_fd.flush()
        # Lock is released automatically when process exits (file closed by OS)
        atexit.register(lambda: os.unlink(LOCK_FILE) if os.path.exists(LOCK_FILE) else None)
        return _lock_fd
    except (IOError, OSError) as e:
        # Lock already held by another process or fcntl not available
        try:
            with open(LOCK_FILE) as f:
                existing_pid = f.read().strip()
        except Exception:
            existing_pid = "unknown"
        
        # Check if fcntl itself is the issue (Windows/No-Fcntl)
        if isinstance(e, ModuleNotFoundError) or "fcntl" in str(e):
             print("\n⚠️  WARNING: Single instance lock (fcntl) not available on this platform. Continuing...")
             return None
             
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

        sq_off_limit = datetime.strptime("15:20", "%H:%M")  # Groww MIS hard cutoff
        if sq_off > sq_off_limit:
            logger.critical(
                f"CRITICAL: auto_square_off ({win['auto_square_off']}) "
                f"is after Groww's 15:20 MIS cutoff. Set to 15:15 or earlier."
            )
            return False
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

    # ── RSI warmup sanity (warning only, not a hard failure) ─────────────────
    warmup = config['strategy'].get('rsi', {}).get('warmup_periods', 0)
    period = config['strategy'].get('rsi', {}).get('period', 0)
    if warmup < period * 2:
        logger.warning(
            f"WARNING: rsi.warmup_periods ({warmup}) is less than "
            f"2× rsi.period ({period}). RSI values may be unstable at session start."
        )

    logger.info("✓ Configuration validation passed")
    return True

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    logger = logging.getLogger("LiveRunner")
    logger.warning("\\n⚠️  Shutdown signal received. Closing positions and exiting...")
    
    # Square off all positions
    if trader_instance:
        try:
            active_trades = trader_instance.tracker.get_active_trades()
            for trade in active_trades:
                exit_qty = trade.get('remaining_qty', trade['qty'])
                logger.info(
                    f"Emergency square-off: {trade['symbol']} | "
                    f"Qty: {exit_qty} (original: {trade['qty']})"
                )
                resp = trader_instance.om.place_exit_order(
                    trade['symbol'],
                    exit_qty,               # remaining_qty after partial exits
                    trade['trading_symbol'],
                    "EMERGENCY_SHUTDOWN"
                )
                if resp and resp.get('groww_order_id'):
                    logger.info(f"Emergency exit order placed: {resp['groww_order_id']}")
                else:
                    logger.critical(f"Emergency exit FAILED for {trade['symbol']} \u2014 CHECK GROWW APP NOW")
        except Exception as e:
            logger.error(f"Error during emergency shutdown: {e}")
    
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
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical(f"Fatal error in trading loop: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("=" * 60)
        logger.info(" LIVE TRADING SESSION ENDED")
        logger.info("=" * 60)

if __name__ == "__main__":
    main()
