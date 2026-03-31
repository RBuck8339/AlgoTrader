import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta
import time

INTERVAL_LIMITS = {
    "15m":  60,
    "30m":  60,
    "1h":   729,
    "1d":   3650,
    "1wk":  3650,
}

KEEP_COLS_YF = ["open", "high", "low", "close", "volume", "dividends", "stock_splits"]


class StockHistoryGrabber:
    def __init__(self, tickers, data_source="yfinance", start=None, end=None):
        self.tickers = tickers
        self.data_source = data_source
        self.start = start
        self.end = end
        self.data_dir = "backtesting/data/stocks"
        os.makedirs(self.data_dir, exist_ok=True)


    def fetch_from_yfinance(self, ticker, interval):
        end = self.end or datetime.today()
        start = self.start or (datetime.today() - timedelta(days=INTERVAL_LIMITS[interval]))

        grabber = yf.Ticker(ticker)
        df = grabber.history(
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            prepost=False,
            actions=True,
        )

        if df.empty:
            print(f"  Warning: no data returned for {ticker} {interval}")
            return pd.DataFrame()

        return self._normalize(df)


    def _single_fetch(self, ticker, interval, start, end):
        try:
            grabber = yf.Ticker(ticker)
            df = grabber.history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                prepost=False,
                actions=True,
            )
            if df.empty:
                return pd.DataFrame()
            return self._normalize(df)
        except Exception as e:
            print(f"  Error fetching {ticker} {interval} ({start.date()} → {end.date()}): {e}")
            return pd.DataFrame()


    def fetch_data(self, ticker, interval):
        if self.data_source == "yfinance":
            return self.fetch_from_yfinance(ticker, interval)
        else:
            raise ValueError(f"Unsupported data source: {self.data_source}")


    def cache(self):
        for ticker in self.tickers:
            for interval in INTERVAL_LIMITS.keys():
                safe_ticker = ticker.replace(".", "-")
                filename = os.path.join(self.data_dir, f"{safe_ticker}_{interval}_{self.start.date()}_to_{self.end.date()}.csv")
                # For the case of repeated backtests
                if os.path.exists(filename):
                    print(f"Already cached {filename}, skipping.")
                    continue
                
                data = self.fetch_data(ticker, interval)

                if data.empty:
                    continue

                data.to_csv(filename)
                print(f"Saved {filename} ({len(data)} bars)")


    def _normalize(self, df):
        df.columns = df.columns.str.lower().str.replace(" ", "_")
        df.index = df.index.tz_localize(None)
        df.index.name = "timestamp"
        df = df.drop(columns=["capital_gains"], errors="ignore")
        df = df[[c for c in KEEP_COLS_YF if c in df.columns]]
        df = df[df["volume"] > 0]
        df = df[df["high"] >= df["low"]]
        df = df[df["close"] > 0]
        df = df[df["high"] >= df["close"]]
        df = df[df["low"] <= df["close"]]
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df
    
if __name__ == "__main__":
    tickers = ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN"]  # Sample ones
    grabber = StockHistoryGrabber(tickers=tickers, start=datetime(2019, 1, 1), end=datetime(2025, 12, 31))
    grabber.cache()