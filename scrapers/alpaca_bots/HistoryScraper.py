"""  
Get a time-frame worth of data, save it to a csv, and then prepare it for backtesting a strategy
"""
import os 
import requests 
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import pandas as pd

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")

class HistoryScraper():
    def __init__(self, stock, start_date, end_date=None):
        self.stock = stock
        self.start_date = start_date
        self.end_date = end_date if end_date else datetime.now(timezone.utc)

        # Uses RFC-3339 format (YYYY-MM-DDThh:mm:ssZ)
        self.time_interval = timedelta(minutes=1)  # Toned down to 1 minute

    def scrape(self):
        # Headers are strictly for authentication
        headers = {
             "APCA-API-KEY-ID": ALPACA_KEY,
             "APCA-API-SECRET-KEY": ALPACA_SECRET,
             "accept": "application/json"
        }
        
        # Params are for your filters (moved from headers)
        params = {
            "limit": 5000 
        }

        """
        Output formats:
            - bars: [{'c', 'h', 'l', 'n', 'o', 't', 'v', 'vw'}]
            - quotes: List of many: [{'ap', 'as', 'ax', 'bp', 'bs', 'bx', 'c', 't', 'z'}, ...]
            - trades: List of many: [{'c', 'i', 'p', 's', 't', 'x', 'z'}, ...]
            - news: List of many: [{'author', 'content', 'created_at', 'headline', 'id', 'images', 'source', 'summary', 'symbols', 'updated_at', 'url'}, ...]
        """
        bars_df = pd.DataFrame(columns=['c', 'h', 'l', 'n', 'o', 't', 'v', 'vw'])
        quotes_df = pd.DataFrame(columns=['ap', 'as', 'ax', 'bp', 'bs', 'bx', 'c', 't', 'z'])
        trades_df = pd.DataFrame(columns=['c', 'i', 'p', 's', 't', 'x', 'z'])
        news_df = pd.DataFrame(columns=['author', 'content', 'created_at', 'headline', 'id', 'images', 'source', 'summary', 'symbols', 'updated_at', 'url'])
        for url, data_stream in [
            (f'https://data.alpaca.markets/v2/stocks/{self.stock}/bars', 'bars'),
            (f'httsps://data.alpaca.markets/v2/stocks/{self.stock}/quotes', 'quotes'),
            (f'https://data.alpaca.markets/v2/stocks/{self.stock}/trades', 'trades'),
            ('https://data.alpaca.markets/v1beta1/news', 'news') # Fixed to correct news endpoint
        ]:
            # Kept your exact logic, just applied it to the 'params' dict instead
            if data_stream == 'bars':
                params["timeframe"] = "1Min"
            else:
                if params.get("timeframe"):  
                    del params["timeframe"]
            if data_stream == 'news':
                params["limit"]  = 5  
            else:
                params["limit"] = 5000   
            
            # NOTE: This will get data from outside of market hours, so some pre data processing is required for backtesting
            curr_start = self.start_date
            curr_end = curr_start + self.time_interval
            
            while curr_start < self.end_date:
                if curr_end > self.end_date:
                    curr_end = self.end_date
                
                # Format to RFC-3339 strings
                start_str = curr_start.strftime('%Y-%m-%dT%H:%M:%SZ')
                end_str = curr_end.strftime('%Y-%m-%dT%H:%M:%SZ')

                # Update params with curr time frame
                params["start"] = start_str
                params["end"] = end_str

                # Pass both headers and params to the request
                response = requests.get(url, headers=headers, params=params)

                if response.status_code == 200:
                    print(f"Success: {data_stream} from {start_str}")
                    print(response.json())
                    
                    # Need to handle cases where 'bars': None or 'news': None, which means no data for that time frame
                    # Duplicate previous row I guess (Or do SMA or smth)
                    if data_stream == 'bars':
                        for item in response.json().get('bars', []):
                            bars_df = pd.concat([bars_df, pd.DataFrame([item])], ignore_index=True)
                    elif data_stream == 'quotes':
                        for item in response.json().get('quotes', []):
                            quotes_df = pd.concat([quotes_df, pd.DataFrame([item])], ignore_index=True)
                    elif data_stream == 'trades':
                        for item in response.json().get('trades', []):
                            trades_df = pd.concat([trades_df, pd.DataFrame([item])], ignore_index=True)
                    elif data_stream == 'news':
                        for item in response.json().get('news', []):
                            news_df = pd.concat([news_df, pd.DataFrame([item])], ignore_index=True)

                else:
                    print(f"Failed to fetch {data_stream} data for {self.stock} between {start_str} and {end_str}: {response.text}")

                curr_start = curr_end
                curr_end += self.time_interval
                
                # Sleep to prevent hitting the 200 requests/min rate limit
                time.sleep(0.5)

    def check_stored(self):
        # Reuse as much data as possible, check existing csv files and merge into one dataframe and take applicable rows
        pass 

if __name__ == "__main__":
    stocks = os.getenv("STOCKS").split(",")
    scraper_storage = {}  # Stores scraped data objects
    for stock in stocks:
        scraper_storage[stock] = HistoryScraper(stock=stock, start_date=datetime(2024, 1, 3, 10, 0, 0,tzinfo=timezone.utc), end_date=datetime(2024, 6, 1, tzinfo=timezone.utc))
        scraper_storage[stock].scrape()