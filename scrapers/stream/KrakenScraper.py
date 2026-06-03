import asyncio
import json
import requests
import websockets
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from utils import KrakenUtils

class KrakenScraper():
    def __init__(self, ticker, api_key=None, api_secret=None, stream_type="ohlc"):
        self.ticker = ticker  
        self.data_api_key = api_key
        self.data_api_secret = api_secret
        self.stream_type = stream_type
        
        self.base_url = "https://api.kraken.com"
        
        # For processing bars and trades
        self.on_bar = None
        self.on_trade = None
        
        self.latest_ask = 0.0
        self.latest_bid = 0.0


    def get_current_price(self, ticker):
        if self.latest_ask > 0 and self.latest_bid > 0:
            return self.latest_ask, self.latest_bid
            
        try:
            url_path = "/0/public/Ticker"  
            params = {"pair": ticker}
            response = requests.get(url=self.base_url + url_path, params=params)
            data = response.json()
            ticker_key = list(data["result"].keys())[0]
            self.latest_ask = float(data["result"][ticker_key]["a"][0])
            self.latest_bid = float(data["result"][ticker_key]["b"][0])
            return self.latest_ask, self.latest_bid
        except Exception as e:
            print(f"Ticker REST fallback error: {e}")
            return 0.0, 0.0


    async def stream(self, intervals=[1, 5, 240]):
        url = "wss://ws.kraken.com/v2"

        async for websocket in websockets.connect(url):
            try:
                print(f"Connected to Kraken. Subscribing to channels...")

                for interval in intervals:
                    subscribe_ohlc = {
                        "method": "subscribe",
                        "params": {
                            "channel": "ohlc", 
                            "symbol": [self.ticker],
                            "interval": interval
                        }
                    }
                    await websocket.send(json.dumps(subscribe_ohlc))
                
                subscribe_trade = {
                    "method": "subscribe",
                    "params": {
                        "channel": "trade",
                        "symbol": [self.ticker]
                    }
                }
                await websocket.send(json.dumps(subscribe_trade))

                async for message in websocket:
                    data = json.loads(message)
                    
                    if "data" in data:
                        channel = data.get("channel")
                        
                        if channel == "ohlc":
                            streamed_interval = data.get("params", {}).get("interval")
                            for candle in data["data"]:
                                self.latest_ask = float(candle.get("close", self.latest_ask))
                                self.latest_bid = float(candle.get("close", self.latest_bid))
                                
                                if self.on_bar:
                                    self.on_bar(candle, streamed_interval)

                        elif channel == "trade":
                            for tick in data["data"]:
                                tick_price = float(tick["price"])
                                self.latest_ask = tick_price
                                self.latest_bid = tick_price
                                
                                if self.on_trade:
                                    self.on_trade(tick)

            except websockets.ConnectionClosed:
                print("Connection lost! Re-establishing connection in 5 seconds...")
                await asyncio.sleep(5)
                continue