# run_live.py
import yaml
import logging
import sys
import signal
import os
from datetime import datetime
from live.live_trader import LiveTrader

# Global trader instance for graceful shutdown
trader_instance = None

def setup_logging(log_file="live_trading.log"):
    """Configure logging for live trading."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a'),  # Append mode for live
            logging.StreamHandler(sys.stdout)
        ]
    )

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
                logger.info(f"Emergency square-off: {trade['symbol']}")
                trader_instance.om.place_exit_order(
                    trade['symbol'],
                    trade.get('remaining_qty', trade['qty']),
                    trade['trading_symbol'],
                    "EMERGENCY_SHUTDOWN"
                )
        except Exception as e:
            logger.error(f"Error during emergency shutdown: {e}")
    
    sys.exit(0)

def main():
    global trader_instance
    
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
