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

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
USING_PAPER = os.getenv("USING_PAPER")


class BaseTrader(ABC):
    """
    An abstract class with the goal of using this to build various trading strategies
    
    Capabilities:
        - Connect to Alpaca account
        - Place and manage orders
        - Collect and analyze trading data
    """
    def __init__(self):
        self.trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=USING_PAPER)
        self.headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": "YOUR_API_KEY_ID",
            "APCA-API-SECRET-KEY": "YOUR_API_SECRET_KEY"
        }

        # Need to adjust the data based on what kind of commodity we are trading
        self.ohlc_data = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap", "timestamp"])
        self.trade_data = pd.DataFrame(columns=["side", "price", "qty", "timestamp", "trade_id"])  # Might want to change format and aggregate by day or smth

        data_type = 'crypto'  # Using only crypto for now
        if data_type == 'crypto':
            self.scraper = KrakenScraper(
                ticker="BTC/USD",
                stream_type="ohlc",
                api_secret=os.getenv("DATA_API_SECRET"),
                api_key=os.getenv("DATA_API_KEY"),
                on_bar=self.on_new_bar,
                on_trade=self.on_new_trade
            )

    def get_account_value(self):
        # TODO Retrieve these values
        self.starting_portfolio_value = 0
        self.portfolio_value = self.starting_portfolio_value
        
        
    def verify_account(self):
        """
        Verify connection to Alpaca account
        """
        if USING_PAPER:
            url = "https://paper-api.alpaca.markets/v2/account"
        else:
            url = "https://api.alpaca.markets/v2/account"  # Verify this
            
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            print(response.text)
        else:
            raise ConnectionError("Failed to connect to Alpaca account")
    
    
    @abstractmethod
    def check_signals(self):
        """
        Abstract method to check for trading signals based on strategy
        """
        raise NotImplementedError("Subclasses must implement check_signals method for their strategy")
        
        
    def place_order(self):
        pass 


    def place_short(self):
        pass 


    def calculate_stop_loss(self, buy_amt, tolerance, pl_ratio):
        stop_loss = (buy_amt - tolerance) / pl_ratio  # Assuming tolerance is not worked out to be per-share
        return stop_loss 
        
        
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
        """
        The actual logic for a trading day 
        """
        asyncio.create_task(self.scraper.stream()) 

        self.portfolio_stop_value = -1  # Need to set up
        while True:
            # Make sure we are still able to trade for the day
            if self.portfolio_stop_value <= self.portfolio_value:
                self.shutdown()

            res = self.check_signals()  # 'BUY', 'SELL', 'HOLD', 'WAIT'
            # 'HOLD' vs 'WAIT' is mainly for debugging and logging, but serve similar purposes

            

            if res == 'BUY' or res == 'SELL':
                # Information for making the trade
                stop_loss = self.calculate_stop_loss(buy_amt=0, tolerance=0, pl_ratio=self.pl_ratio)  # Need to set up buy_amt and tolerance


                #self.place_order(res)
            await asyncio.sleep(1)
            # In other cases we do nothing (else eats up time)


    def on_new_bar(self, bar_data):
        """
        Callback for when a new bar (candle) is received from the data stream
        """
        # Convert bar_data to a DataFrame row and append to ohlc_data
        new_row = pd.DataFrame([bar_data])
        self.ohlc_data = pd.concat([self.ohlc_data, new_row], ignore_index=True)
        print(f"Received new bar: {bar_data}")  # DEBUG
    
    def on_new_trade(self, trade_data):
        """
        Callback for when a new trade is received from the data stream
        """
        new_row = pd.DataFrame([trade_data])
        self.trade_data = pd.concat([self.trade_data, new_row], ignore_index=True)
        print(f"Received new trade: {trade_data}")  # DEBUG

