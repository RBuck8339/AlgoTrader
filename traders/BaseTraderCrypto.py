import asyncio

import requests
from dotenv import load_dotenv
import os
import pandas as pd
from abc import ABC, abstractmethod
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from scrapers.stream.KrakenScraper import KrakenScraper
import time 
from collections import defaultdict

import hashlib
import hmac
import base64


# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
USING_PAPER = os.getenv("USING_PAPER")


class BaseTrader(ABC):
    """
    An abstract class with the goal of using this to build various trading strategies
    
    Capabilities:
        - Connect to account
        - Place and manage orders
        - Collect and analyze trading data
    """
    def __init__(self, ticker="BTC/USD"):
        self.ticker = ticker
        self.ohlc_history = defaultdict(list)
        self.last_closed_timestamps = {}  # int: None by default
        
        self.bar_queue = asyncio.Queue()
        
        # Initialize
        self.scraper = KrakenScraper(
            ticker=self.ticker,
            stream_type="ohlc",
            api_secret=os.getenv("KRAKEN_DATA_KEY_PRIVATE"),
            api_key=os.getenv("KRAKEN_DATA_KEY_PUBLIC"),
            # on_bar=self.on_new_bar
        )
        
        # For API usage
        self.base_url = "https://api.kraken.com"
        self.data_api_secret = os.getenv("KRAKEN_DATA_KEY_PRIVATE")
        self.data_api_key = os.getenv("KRAKEN_DATA_KEY_PUBLIC")
        self.starting_portfolio_value = None
        self.portfolio_value = None


    def on_new_bar(self, candle, interval):
        """Background network function tracking incoming ticks."""
        if interval not in self.ohlc_history:
            return

        current_ts = candle.get("timestamp")
        last_ts = self.last_closed_timestamps.get(interval)
        
        if last_ts is not None and current_ts != last_ts:
            self.last_closed_timestamps[interval] = current_ts
            
            # Append the finalized candle to history
            self.ohlc_history[interval].append(candle)
            if len(self.ohlc_history[interval]) > 200:
                self.ohlc_history[interval].pop(0)
            
            # 📬 PUSH TO QUEUE: Tell the main thread a new bar is officially ready!
            # loop.call_soon_threadsafe is used if your scraper runs on a separate thread
            asyncio.run_coroutine_threadsafe(
                self.bar_queue.put(interval), 
                asyncio.get_event_loop()
            )
            
        elif last_ts is None:
            self.last_closed_timestamps[interval] = current_ts
            self.ohlc_history[interval].append(candle)

    def get_dataframe(self, interval):
        """Helper to instantly generate an analytical dataframe."""
        df = pd.DataFrame(self.ohlc_history[interval])
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df
            
    
    @staticmethod
    def get_kraken_signature(url_path, data, secret):
        # For actually interacting with Kraken API, this is necessary
        postdata = requests.compat.urlencode(data)  # Standardized to web-link text format
        encoded = (str(data['nonce']) + postdata).encode()  # Add timestamp to front
        message_hash = hashlib.sha256(encoded).digest()  # SHA256 hash of the above
        message = url_path.encode() + message_hash
        mac_key = base64.b64decode(secret)
        mac = hmac.new(mac_key, message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return sigdigest.decode()
            

    def get_account_value(self):
        url_path = "/0/private/TradeBalance"  # Can probably just make this a param for a multi-function function
        
        # Setup
        nonce = int(time.time() * 1000)
        payload = {
            "nonce": nonce, 
            "asset": "ZUSD"
        }
        signature = BaseTrader.get_kraken_signature(url_path, payload, self.data_api_secret)
        headers = {
            "API-Key": self.data_api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        response = requests.post(url=self.base_url + url_path, headers=headers, data=payload)
        data = response.json()
        self.starting_portfolio_value = data["result"]["eb"] if self.starting_portfolio_value is None else self.starting_portfolio_value  # Don't overwrite later
        self.portfolio_value = data["result"]["eb"]
        
        return self.portfolio_value
        
        
    def verify_account(self):
        # TODO Verify connection to account (Can also be done through get_account_value tbh)
        pass
    
    
    def place_order(self, type='long'):
        # Place an order, default is long order (optional short)
        pass 
        
        
    def results_for_day(self):
        """
        Get the results for the day; optionally send to a csv/database
        """
        pass 
    

    def shutdown(self):
        """ 
        If we have lost too much money for the day, invoke this function and shutdown for the day
        Log so that I can fix it
        """
        # Need to stop data stream safely
        pass

    
    async def main(self):
        raise NotImplementedError("Subclasses must implement check_signals method for their strategy")
