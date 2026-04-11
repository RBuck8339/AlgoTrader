import os

import pandas as pd

from backtesting.CryptoHistoryGrabber import KrakenHistoricalScraper 

INTERVAL_MAP = {
    1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h",
    240: "4h", 1440: "1d", 10080: "1w", 21600: "15d"
}

# I want to use this to inspire my backtesting framework
#   https://www.youtube.com/watch?v=NLBXgSmRBgU
class Backtester: 
    def __init__(self):
        self.data_dir = "backtesting/data"
        self.results_dir = "backtesting/results"
        
        # For storing results of backtests
        self.backtest_results = pd.DataFrame(columns=["date", "time", "portfolio_value", "live_order", "unrealized_pnl", "realized_pnl", "total_pnl"])
        self.historical_data = None

        self.data_dir = 'backtesting/data'

    def test_module(self, module):
        # Provide a class of an algorithm to test for trading (note all my modules will have the same structure as defined in traders/BaseTrader.py)
        pass 
        # IMPLEMENT DIVIDENDS AS A FORM OF REVENUE IF WE TARGET THEM
    
    def run_backtests(self):
        # Run backtests for all algorithms, and store results in a csv/database
        pass


    def load_historical_data(self, data_type, ticker, start_date, end_date, frequency):
        # Load historical data for a given ticker and date range from the data directory
        # This can be used for backtesting and also for training models
        
        # Format for filenames
        interval_label = INTERVAL_MAP.get(frequency, f"{frequency}m")
        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')

        if data_type == "stock":
            data_path_ohlc = os.path.join(
                self.data_dir,
                f"{ticker}_{interval_label}_ohlc_{start_str}_to_{end_str}.csv"
            )
            data_path_trades = os.path.join(
                self.data_dir,
                f"{ticker}_trades_{start_str}_to_{end_str}.csv"
            )
            if not os.path.exists(data_path_ohlc):
                pass  # TODO Implement stock data scraper into here

        elif data_type == "crypto":
            data_path_ohlc = os.path.join(
                self.data_dir, "crypto",
                f"kraken_{ticker}_{interval_label}_ohlc_{start_str}_to_{end_str}.csv"
            )
            data_path_trades = os.path.join(
                self.data_dir, "crypto",
                f"kraken_{ticker}_trades_{start_str}_to_{end_str}.csv"
            )
            if not os.path.exists(data_path_ohlc):
                print(f"OHLC file not found, scraping...")
                KrakenHistoricalScraper(
                    symbol=ticker,
                    data_type="ohlc",
                    interval=frequency,
                    start_date=start_date,
                    end_date=end_date,
                ).fetch()

            if not os.path.exists(data_path_trades):
                print(f"Trades file not found, scraping...")
                KrakenHistoricalScraper(
                    symbol=ticker,
                    data_type="trades",
                    start_date=start_date,
                    end_date=end_date,
                ).fetch()
            self.historical_data = {
                "ohlc": pd.read_csv(data_path_ohlc, parse_dates=["timestamp"], index_col="timestamp"),
                "trades": pd.read_csv(data_path_trades, parse_dates=["timestamp"], index_col="timestamp"),
            }

        else:
            raise ValueError("Unsupported data type. Choose 'stock' or 'crypto'")

        print(f"Loaded {len(self.historical_data['ohlc'])} OHLC bars for {ticker}")
        if self.historical_data["trades"] is not None:
            print(f"Loaded {len(self.historical_data['trades'])} trades for {ticker}")


if __name__ == "__main__":
    # Sample usage for loading historical data
    backtester = Backtester()
    backtester.load_historical_data(
        data_type="crypto",
        ticker="XBTUSD",
        start_date=pd.Timestamp("2023-01-01"),
        end_date=pd.Timestamp("2023-01-10"),
        frequency=60
    )