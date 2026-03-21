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
    """Validate configuration file."""
    logger = logging.getLogger("LiveRunner")
    
    required_keys = [
        'trading', 'strategy', 'capital', 'risk', 'indices', 'data'
    ]
    
    for key in required_keys:
        if key not in config:
            logger.critical(f"CRITICAL: Missing required config section: {key}")
            return False
    
    # Validate trading window
    if 'window' not in config['trading']:
        logger.critical("CRITICAL: Missing trading.window in config")
        return False
    
    # Validate strategy params
    if config['strategy']['rsi']['period'] <= 0:
        logger.critical("CRITICAL: RSI period must be positive")
        return False
    
    if config['strategy']['alert_validity'] <= 0:
        logger.critical("CRITICAL: Alert validity must be positive")
        return False
    
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
