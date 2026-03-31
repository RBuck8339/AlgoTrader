import asyncio
import json
import websockets

class KrakenScraper():
    def __init__(self, ticker, api_key=None, api_secret=None, stream_type="ticker"):
        self.ticker = ticker  
        self.api_key = api_key
        self.api_secret = api_secret
        self.stream_type = stream_type

    async def stream(self, interval_amt=1):
        url = "wss://ws.kraken.com/v2"

        async for websocket in websockets.connect(url):
            try:
                sub_params = {
                    "channel": self.stream_type, 
                    "symbol": [self.ticker]
                }
                
                if self.stream_type == "book":
                    sub_params["depth"] = 10
                elif self.stream_type == "ohlc":
                    sub_params["interval"] = interval_amt

                subscribe_msg = {
                    "method": "subscribe",
                    "params": sub_params
                }

                await websocket.send(json.dumps(subscribe_msg))

                async for message in websocket:
                    data = json.loads(message)
                    
                    # Kraken sends an 'ack' and 'heartbeats' which don't have a 'data' key
                    # This check prevents your code from crashing on those messages
                    if "data" in data:
                        print(f"--- New {self.stream_type} Update ---")
                        print(json.dumps(data["data"], indent=2))
                    else:  # Can ignore, but may want to keep for logging and making sure setup works
                        print(f"System Message: {data.get('method') or data.get('channel')}")

            except websockets.ConnectionClosed:
                print("Connection closed, retrying...")
                continue

if __name__ == "__main__":
    scraper = KrakenScraper(ticker="BTC/USD", stream_type="ohlc")  # "ticker", "book", "trade", or "ohlc"
    # Note: ohlc will update the candle on each trade, need to update the row in data

    try:
        asyncio.run(scraper.stream())
    except KeyboardInterrupt:
        print("\nStream stopped by user.")