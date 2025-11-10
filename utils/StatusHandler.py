# Class to handle status updates for the account
# Note: I would like to set up a websocket service (likely using C#/C++) to handle market data

from dotenv import load_dotenv
import os
import asyncio
from alpaca.trading.stream import TradingStream

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
USING_PAPER = bool(os.getenv("USING_PAPER"))

class StatusHandler():
    def __init__(self):
        self.stream = TradingStream(
            ALPACA_KEY,
            ALPACA_SECRET,
            paper=USING_PAPER,
        )
        
        
    async def update_hander(self, data):
        print(data)  # Need to figure out what I actually want to do with the updates and handle accordingly
    
    
    async def start(self):
        self.stream.subscribe_trade_updates(self.update_hander)
        await self.stream.run()
        
    
        
        
# Use case; can copy over to other classes to call and monitor status updates
if __name__ == "__main__":
    handler = StatusHandler()
    asyncio.run(handler.start())
    # At the end of trading day/window, make sure to stop the stream
    # TODO