from dotenv import load_dotenv
import os
from alpaca.data.live import StockDataStream

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")


class StockScraper():
    def __init__(self, stocks):
        self.wss_client = StockDataStream(ALPACA_KEY, ALPACA_SECRET)
        self.wss_client.subscribe_bars(self.bar_data_handler, *stocks)
        self.wss_client.subscribe_quotes(self.quote_data_handler, *stocks)
        self.wss_client.subscribe_trades(self.trade_data_handler, *stocks)
        self.wss_client.run()
    
    
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
    scraper = StockScraper(stocks=stocks)
    