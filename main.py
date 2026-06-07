from scrapers.stream.KrakenScraper import KrakenScraper
from utils.KrakenUtils import KrakenUtils
import asyncio

# The traders
from traders.Scalpers.Breakout5mScalper import Breakout5mScalper

def main():
    # We choose one instance to act as the primary orchestrator (it doesn't matter which one)
    orchestrator = Breakout5mScalper(target_candle_time='08:00')
    
    methods_config = [
        (Breakout5mScalper, {"target_candle_time": "08:00"}),
    ]
    
    print(f"[INFO] Launching trader with {len(methods_config)} strategies running in parallel")
    
    try:
        orchestrator.setup_trading(methods=methods_config, setting='paper')
    except Exception as e:
        print(f"[ERROR] An error occurred during runtime: {e}")

if __name__ == "__main__":
    main()