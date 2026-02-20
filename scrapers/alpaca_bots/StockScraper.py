from dotenv import load_dotenv
import os
import pandas as pd
from alpaca.data.live import StockDataStream

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")


class StockScraper():
    def __init__(self, stock):
        self.stock = stock
        self.wss_client = StockDataStream(ALPACA_KEY, ALPACA_SECRET)
        self.wss_client.subscribe_bars(self.bar_data_handler, stock)
        self.wss_client.subscribe_quotes(self.quote_data_handler, stock)
        self.wss_client.subscribe_trades(self.trade_data_handler, stock)
        self.wss_client.run()

        # For Aggregation/ML applications
        self.bar_data = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        self.quote_data = pd.DataFrame(columns=["timestamp", "bid_price", "bid_size", "ask_price", "ask_size"])
        self.trade_data = pd.DataFrame(columns=["timestamp", "price", "size"])
    
    
    # TODO: Figure out what I actually want to do with this info (Will come with formation of algorithms)
    async def bar_data_handler(self, data):
        print('Bar Data: ', data)
        
        
    # TODO: Figure out what I actually want to do with this info (Will come with formation of algorithms)
    async def quote_data_handler(self, data):
        print('Quote Data: ', data)
        
        
    # TODO: Figure out what I actually want to do with this info (Will come with formation of algorithms)
    async def trade_data_handler(self, data):
        print('Trade Data: ', data)
        

if __name__ == "__main__":
    stocks = os.getenv("STOCKS").split(",")
    scraper_storage = {}  # Stores scraped data objects
    for stock in stocks:
        scraper_storage[stock] = StockScraper(stock=stock)
    