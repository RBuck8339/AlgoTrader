import asyncio
import json
import requests
import websockets
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from utils import KrakenUtils

class KrakenScraper():
    def __init__(self, ticker, bar_queue=None, trade_queue=None, api_key=None, api_secret=None):
        self.ticker = ticker  
        self.data_api_key = api_key
        self.data_api_secret = api_secret
        
        # Reference the deques passed from your main runner
        self.bar_queue = bar_queue
        self.trade_queue = trade_queue
        
        self.base_url = "https://api.kraken.com"
        self.latest_ask = 0.0
        self.latest_bid = 0.0

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
                            for candle in data["data"]:
                                streamed_interval = candle.get("interval", 1)
                                
                                self.latest_ask = float(candle.get("close", self.latest_ask))
                                self.latest_bid = float(candle.get("close", self.latest_bid))
                                
                                # Append a structured tuple or dict directly to the queue
                                if self.bar_queue is not None:
                                    self.bar_queue.append({
                                        "type": "bar",
                                        "interval": streamed_interval,
                                        "data": candle
                                    })

                        elif channel == "trade":
                            for tick in data["data"]:
                                tick_price = float(tick["price"])
                                self.latest_ask = tick_price
                                self.latest_bid = tick_price
                                
                                if self.trade_queue is not None:
                                    self.trade_queue.append({
                                        "type": "trade",
                                        "data": tick
                                    })
                                    
                    elif "event" in data and data["event"] == "subscribe":
                        print(f"Subscription confirmed: {data.get('channel')} for {data.get('symbol')}")

            except websockets.ConnectionClosed:
                print("Connection lost! Re-establishing connection in 5 seconds...")
                await asyncio.sleep(5)
                continue