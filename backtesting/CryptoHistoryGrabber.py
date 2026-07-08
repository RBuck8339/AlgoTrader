import urllib.request
import urllib.parse
import urllib.error
import json
import csv
import hmac
import hashlib
import base64
import time
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

INTERVAL_MAP = {
    1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h",
    240: "4h", 1440: "1d", 10080: "1w", 21600: "15d"
}

BASE_URL = "https://api.kraken.com/0/public/"
PRIVATE_URL = "https://api.kraken.com/0/private/"


class KrakenHistoricalScraper:
    def __init__(
        self,
        symbol,
        data_type="trades",
        interval=1,
        days=10,
        since=None,
        start_date=None,
        end_date=None,
        output_dir="backtesting/data/crypto",
        sleep_delay=0.67,  
        rate_limit_wait=5,
        batch_size=1000,   
        api_key=None,
        api_secret=None,
    ):
        # Universal clean ticker string for file paths and internal tracking
        self.symbol = symbol.replace("/", "")
        self.data_type = data_type
        self.interval = interval
        self.output_dir = output_dir
        self.sleep_delay = sleep_delay
        self.rate_limit_wait = rate_limit_wait
        self.batch_size = batch_size
        self.api_key = api_key or os.getenv("DATA_API_KEY")
        self.api_secret = api_secret or os.getenv("DATA_API_SECRET")

        if end_date:
            parsed_end = self._parse_date(end_date)
            self.end_date = parsed_end.replace(tzinfo=None)
        else:
            self.end_date = datetime.now(timezone.utc)

        if start_date:
            parsed_start = self._parse_date(start_date)
            localized_start = parsed_start.replace(tzinfo=None)
            self.since = int(localized_start.timestamp())
        elif since:
            self.since = since
        else:
            self.since = int((self.end_date - timedelta(days=days)).timestamp())


    def fetch(self):
        handlers = {
            "trades": self._get_trades,
            "ohlc": self._get_ohlc,
        }
        handler = handlers.get(self.data_type)

        if not handler:
            raise ValueError(f"Invalid data_type '{self.data_type}'.")

        filename = self._build_filename()

        max_history_seconds = 720 * self.interval * 60
        is_too_old = (datetime.now().timestamp() - self.since) > max_history_seconds

        if self.data_type == "ohlc" and is_too_old:
            print(f"!!! Historical gap detected. Kraken OHLC API cannot reach that date.")
            print(f"!!! Switching to trades scraping + local resampling...")

            original_data_type = self.data_type
            self.data_type = "trades"
            trade_filename = self._build_filename()
            self.data_type = original_data_type

            if not os.path.exists(trade_filename):
                self._get_trades(trade_filename)
                self._filter_to_end_date(trade_filename)
            else:
                print(f"   Found existing trades file, skipping scrape.")

            self._resample_trades_to_ohlc(trade_filename, filename)
            return filename

        if os.path.exists(filename):
            os.remove(filename)

        result = handler(filename)
        self._filter_to_end_date(filename)
        return filename

    def _resample_trades_to_ohlc(self, trade_file, ohlc_file):
        print(f"   Generating {self.interval}m bars from trades...")

        df = pd.read_csv(trade_file)

        if df.empty:
            raise RuntimeError(f"Trades file is empty after filtering: {trade_file}. Check your date range — Kraken trade history may not go back that far.")

        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
        df["price"] = df["price"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df = df.set_index("timestamp")
        df = df.sort_index()

        resample_str = f"{self.interval}min"

        ohlc = df["price"].resample(resample_str).ohlc()
        ohlc["volume"] = df["volume"].resample(resample_str).sum()

        price_vol = (df["price"] * df["volume"]).resample(resample_str).sum()
        ohlc["vwap"] = price_vol / ohlc["volume"]
        ohlc["count"] = df["price"].resample(resample_str).count()

        ohlc = ohlc.dropna(subset=["open", "high", "low", "close"])
        ohlc.to_csv(ohlc_file)
        print(f"   Done! Created {len(ohlc)} bars in {ohlc_file}")

    def _get_ohlc(self, filename):
        url = f"{BASE_URL}OHLC"
        current_since = self.since
        total_records = 0
        stop_fetching = False

        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "vwap", "volume", "count"])

            while not stop_fetching:
                params = {"pair": self.symbol, "interval": self.interval}
                if current_since:
                    params["since"] = current_since

                data = self._make_request(url, params, use_auth=False)
                if "error" in data and data["error"]:
                    return {"error": data["error"]}

                batch_count = 0
                for key in data["result"]:
                    if key != "last":
                        candles = data["result"][key]
                        batch_count = len(candles)
                        for candle in candles:
                            ts = datetime.fromtimestamp(float(candle[0]))
                            if ts > self.end_date:
                                stop_fetching = True
                                break
                            writer.writerow([
                                ts, candle[1], candle[2], candle[3], candle[4],
                                candle[5], candle[6], candle[7]
                            ])
                            total_records += 1

                if not stop_fetching and "last" in data["result"] and batch_count == 720:
                    print(f"   Fetched {total_records} records...")
                    current_since = data["result"]["last"]
                    time.sleep(self.sleep_delay)
                else:
                    break

        return {"total_records": total_records}

    def _get_trades(self, filename):
        url = f"{BASE_URL}Trades"
        
        # Ensure we start cleanly using a precise nanosecond timestamp string/int
        current_since_ns = int(self.since * 1_000_000_000)
        total_records = 0
        stop_fetching = False

        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "price", "volume", "buy_sell", "market_limit", "misc"])

            while not stop_fetching:
                params = {"pair": self.symbol}
                if current_since_ns:
                    params["since"] = current_since_ns

                data = self._make_request(url, params, use_auth=False)
                if "error" in data and data["error"]:
                    print(f"Kraken error received: {data['error']}")
                    if data['error'][0] == 'EGeneral:Too many requests':
                        time.sleep(self.rate_limit_wait)
                        continue
                    else: 
                        return {"error": data["error"]}

                if "result" not in data or not data["result"]:
                    print("Empty result dataset from Kraken API.")
                    break

                # FIX: Dynamically identify the data key that isn't named 'last'
                result_keys = [k for k in data["result"].keys() if k != "last"]
                if not result_keys:
                    break
                
                pair_data_key = result_keys[0]
                trades = data["result"][pair_data_key]
                batch_count = len(trades)
                
                if batch_count == 0:
                    print("Reached end of available records (0 rows returned).")
                    break
                    
                for trade in trades:
                    # Kraken public trade timestamp array element index 2 is float seconds
                    ts = datetime.utcfromtimestamp(float(trade[2]))
                    if ts > self.end_date:
                        stop_fetching = True
                        break
                    writer.writerow([
                        ts, trade[0], trade[1], trade[3], trade[4], trade[5]
                    ])
                    total_records += 1

                if stop_fetching:
                    print(f"Target date threshold surpassed. Download complete.")
                    break

                if "last" in data["result"] and batch_count > 0:
                    new_since_ns = int(data["result"]["last"])
                    
                    # Essential anti-infinite-loop guard if pagination stalls
                    if new_since_ns <= current_since_ns:
                        print("Pagination marker stalled. Ending loop collection phase.")
                        break
                        
                    current_since_ns = new_since_ns
                    print(f"   Successfully compiled {total_records} historical trade records...")
                    time.sleep(self.sleep_delay)
                else:
                    break

        return {"total_records": total_records}
    
    def _filter_to_end_date(self, filename):
        print(f"   Cleaning data in {filename}...")

        if not os.path.exists(filename) or os.path.getsize(filename) <= 100:
            return

        df = pd.read_csv(filename)
        if df.empty:
            return
            
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")

        start_dt = pd.Timestamp(datetime.utcfromtimestamp(self.since))
        end_dt = pd.Timestamp(self.end_date)

        mask = (df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)
        df_filtered = df.loc[mask].copy()
        
        df_filtered["timestamp"] = df_filtered["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S.%f")
        df_filtered.to_csv(filename, index=False)

        print(f"   Cleaned! Kept {len(df_filtered)} rows within requested range.")

    def _make_request(self, url, params, use_auth=False, max_retries=3):
        for attempt in range(max_retries):
            try:
                query_str = urllib.parse.urlencode(params) if params else ""
                full_url = f"{url}?{query_str}" if query_str else url

                headers = {}
                body_data = None
                if use_auth and self.api_key and self.api_secret:
                    uri_path = url.replace("https://api.kraken.com", "")
                    headers, body_str = self._auth_headers(uri_path, params)
                    body_data = body_str.encode() if body_str else None

                req = urllib.request.Request(full_url, data=body_data, headers=headers)
                response = urllib.request.urlopen(req)
                data = json.loads(response.read().decode())
                return data

            except urllib.error.HTTPError as e:
                print(f"HTTP Error {e.code}: {e.read().decode()}")
                return {"error": [f"HTTP {e.code}"]}
            except Exception as e:
                print(f"Request failed: {e}")
                time.sleep(self.rate_limit_wait)
                continue

        return {"error": ["Max retries exceeded"]}

    def _parse_date(self, date):
        if isinstance(date, datetime):
            return date
        if isinstance(date, str):
            return datetime.strptime(date, "%Y-%m-%d")
        if isinstance(date, pd.Timestamp):
            return date.to_pydatetime()
        raise ValueError(f"Invalid date format: {date}. Use datetime or 'YYYY-MM-DD'.")

    def _build_filename(self):
        start_dt = datetime.utcfromtimestamp(self.since)
        
        if start_dt.year == 2022 and start_dt.month == 12 and start_dt.day == 31:
            start_str = "20230101"
        else:
            start_str = start_dt.strftime("%Y%m%d")
            
        end_str = self.end_date.strftime("%Y%m%d")
        safe_symbol = self.symbol.replace("/", "_")

        if self.data_type == "ohlc":
            interval_label = INTERVAL_MAP.get(self.interval, f"{self.interval}m")
            return os.path.join(
                self.output_dir,
                f"kraken_{safe_symbol}_{interval_label}_{self.data_type}_{start_str}_to_{end_str}.csv"
            )
            
        return os.path.join(
            self.output_dir,
            f"kraken_{safe_symbol}_{self.data_type}_{start_str}_to_{end_str}.csv"
        )


if __name__ == "__main__":
    scraper = KrakenHistoricalScraper(
        symbol="BTC/USD",
        data_type="ohlc",
        interval=60,
        start_date=pd.Timestamp("2023-01-01"),
        end_date=pd.Timestamp("2023-01-10"),
    )
    scraper.fetch()