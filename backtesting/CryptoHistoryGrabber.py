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
        start_date=None,  # datetime or "YYYY-MM-DD" string
        end_date=None,    # datetime or "YYYY-MM-DD" string — defaults to now
        output_dir="backtesting/data/crypto",
        sleep_delay=0.01,
        rate_limit_wait=5,
        batch_size=5000,
        api_key=None,
        api_secret=None,
    ):
        self.symbol = symbol
        self.data_type = data_type
        self.interval = interval
        self.output_dir = output_dir
        self.sleep_delay = sleep_delay
        self.rate_limit_wait = rate_limit_wait
        self.batch_size = batch_size
        self.api_key = api_key or os.getenv("DATA_API_KEY")
        self.api_secret = api_secret or os.getenv("DATA_API_SECRET")

        # Resolve end date first
        self.end_date = self._parse_date(end_date) if end_date else datetime.now()

        # Resolve start — start_date takes priority, then since, then days
        if start_date:
            self.since = int(self._parse_date(start_date).timestamp())
        elif since:
            self.since = since
        else:
            self.since = int((self.end_date - timedelta(days=days)).timestamp())

        os.makedirs(self.output_dir, exist_ok=True)

    def fetch(self):
        handlers = {
            "trades": self._get_trades,
            "ohlc": self._get_ohlc,
        }
        handler = handlers.get(self.data_type)
        
        if not handler:
            raise ValueError(f"Invalid data_type '{self.data_type}'.")

        filename = self._build_filename()
        
        # Kraken only lets us get last 720 intervals, can't do history like trades apparently
        max_history_seconds = 720 * self.interval * 60
        is_too_old = (datetime.now().timestamp() - self.since) > max_history_seconds

        if self.data_type == "ohlc" and is_too_old:
            print(f"!!! Historical gap detected. Kraken OHLC API cannot reach 2023.")
            print(f"!!! Switching to 'trades' scraping + local resampling...")
            
            # 1. Fetch trades instead
            original_data_type = self.data_type
            self.data_type = "trades"
            trade_filename = self._build_filename()
            self._get_trades(trade_filename)
            self._filter_to_end_date(trade_filename)
            
            # 2. Resample trades into OHLC
            self._resample_trades_to_ohlc(trade_filename, filename)
            self.data_type = original_data_type
            return filename

        # Standard path for recent OHLC or any Trades request
        if os.path.exists(filename):
            os.remove(filename)

        result = handler(filename)
        self._filter_to_end_date(filename)
        return filename

    def test_auth(self):
        """Test if authentication is working"""
        data = self._make_request(f"{PRIVATE_URL}OpenOrders", {}, use_auth=True)
        if "error" in data and data["error"]:
            if any("permission" in str(e).lower() for e in data["error"]):
                print("Auth working but insufficient permissions")
                return True
            print(f"Auth failed: {data['error']}")
            return False
        print("Auth working")
        return True

    def _resample_trades_to_ohlc(self, trade_file, ohlc_file):
        print(f"   Generating {self.interval}m bars from trades...")
        df = pd.read_csv(trade_file, parse_dates=['timestamp'], index_col='timestamp')
        
        resample_str = f"{self.interval}min"
        
        # Create OHLC
        ohlc = df['price'].resample(resample_str).ohlc()
        ohlc['volume'] = df['volume'].resample(resample_str).sum()
        
        # Calculate VWAP (Price * Volume / Total Volume)
        price_vol = (df['price'] * df['volume']).resample(resample_str).sum()
        ohlc['vwap'] = price_vol / ohlc['volume']
        
        # Match the Kraken column format
        ohlc['count'] = df['price'].resample(resample_str).count()
        
        # Save and Cleanup
        ohlc.dropna().to_csv(ohlc_file)
        print(f"   Done! Created {len(ohlc)} bars in {ohlc_file}")

    # TODO DELETE LATER IF NEEDED, SINCE THE KRAKEN API MIGHT BE ACTUALLY ABLE TO HANDLE > 720 INTERVALS
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
        current_since = self.since
        total_records = 0
        stop_fetching = False # Flag to break the outer while loop

        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "price", "volume", "buy_sell", "market_limit", "misc"])

            while not stop_fetching:
                params = {"pair": self.symbol, "count": self.batch_size}
                if current_since:
                    params["since"] = current_since

                data = self._make_request(url, params, use_auth=False) # Auth not needed for public data
                if "error" in data and data["error"]:
                    return {"error": data["error"]}

                batch_count = 0
                for key in data["result"]:
                    if key != "last":
                        trades = data["result"][key]
                        batch_count = len(trades)
                        for trade in trades:
                            ts = datetime.fromtimestamp(float(trade[2]))
                            
                            # Check if we have passed the end date
                            if ts > self.end_date:
                                stop_fetching = True
                                break
                            
                            writer.writerow([
                                ts, trade[0], trade[1], trade[3], trade[4], trade[5]
                            ])
                            total_records += 1

                # Check if we should continue to next batch
                if not stop_fetching and "last" in data["result"] and batch_count == self.batch_size:
                    print(f"   Fetched {total_records} records...")
                    current_since = data["result"]["last"]
                    time.sleep(self.sleep_delay)
                else:
                    break

        return {"total_records": total_records}

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

            except urllib.error.HTTPError as e:
                print(f"HTTP Error {e.code}: {e.read().decode()}")
                return {"error": [f"HTTP {e.code}"]}
            except Exception as e:
                print(f"Request failed: {e}")
                return {"error": ["Request failed"]}

            if "error" in data and any("too many requests" in str(e).lower() for e in data.get("error", [])):
                wait = (2 ** attempt) * self.rate_limit_wait
                print(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            return data

        return {"error": ["Max retries exceeded"]}

    def _auth_headers(self, uri_path, query_params):
        try:
            nonce = str(int(time.time() * 1000))
            query_str = urllib.parse.urlencode(query_params) if query_params else ""
            body = {"nonce": nonce}
            body_str = json.dumps(body)

            combined = nonce + query_str + body_str
            sha256_hash = hashlib.sha256(combined.encode()).digest()
            message = uri_path.encode() + sha256_hash
            signature = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)

            headers = {
                "API-Key": self.api_key,
                "API-Sign": base64.b64encode(signature.digest()).decode(),
                "Content-Type": "application/json",
            }
            return headers, body_str
        except Exception as e:
            print(f"Auth header error: {e}")
            return {}, ""
        
    def _parse_date(self, date):
        """Accept datetime object or YYYY-MM-DD string"""
        if isinstance(date, datetime):
            return date
        if isinstance(date, str):
            return datetime.strptime(date, "%Y-%m-%d")
        raise ValueError(f"Invalid date format: {date}. Use a datetime object or 'YYYY-MM-DD' string.")

    def _build_filename(self):
        # Use UTC to prevent the timezone shift from 20230101 to 20221231
        start_dt = datetime.fromtimestamp(self.since, tz=timezone.utc)
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

    def _filter_to_end_date(self, filename):
        """Clean the CSV to keep ONLY data between self.since and self.end_date"""
        print(f"   Cleaning data in {filename}...")
        
        # Use pandas for robust date parsing and filtering
        df = pd.read_csv(filename)
        
        # 1. Convert timestamp column to datetime objects
        # This handles the '.135206' microsecond issue automatically
        df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
        
        # 2. Define our bounds
        start_dt = pd.to_datetime(self.since, unit='s', utc=True).tz_localize(None)
        end_dt = self.end_date
        
        # 3. Filter the dataframe
        mask = (df['timestamp_dt'] >= start_dt) & (df['timestamp_dt'] <= end_dt)
        df_filtered = df.loc[mask].copy()
        
        # 4. Cleanup and save
        df_filtered = df_filtered.drop(columns=['timestamp_dt'])
        df_filtered.to_csv(filename, index=False)
        
        print(f"   Cleaned! Kept {len(df_filtered)} rows within requested range.")
if __name__ == "__main__":
    # Example
    scraper = KrakenHistoricalScraper(
        symbol="XBTUSD",
        data_type="ohlc",
        interval=60,
        start_date=pd.Timestamp("2023-01-01"),
        end_date=pd.Timestamp("2023-12-31"),
    )
    scraper.fetch()