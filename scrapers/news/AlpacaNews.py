from dotenv import load_dotenv
import os
import pandas as pd
from alpaca.data.live import StockDataStream, NewsDataStream

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")


class StockScraper():
    def __init__(self, stock):
        self.stock = stock
        self.wss_client = NewsDataStream(ALPACA_KEY, ALPACA_SECRET)
        self.wss_client.subscribe_news(self.news_data_handler, stock)
        self.wss_client.run()


    async def news_data_handler(self, data):
        print('News Data: ', data)

if __name__ == "__main__":
    stocks = os.getenv("STOCKS").split(",")
    scraper_storage = {}  # Stores scraped data objects
    for stock in stocks:
        scraper_storage[stock] = StockScraper(stock=stock)