import requests
from dotenv import load_dotenv
import os
import datetime
import time
from abc import ABC, abstractmethod
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, StopOrderRequest, StopLimitOrderRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# ENV Variables
load_dotenv()
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
USING_PAPER = bool(os.getenv("USING_PAPER"))


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
            "APCA-API-KEY-ID": ALPACA_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET
        }
        
        # Get the trading hours
        self.trade_start = os.getenv("TRADE_START", "09:30")
        self.trade_end = os.getenv("TRADE_END", "16:00")
        self.trade_start = datetime.datetime.strptime(self.trade_start, "%H:%M").time()
        self.trade_end = datetime.datetime.strptime(self.trade_end, "%H:%M").time()
        
        
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
        
        
    def place_trade_order(self, order_type, symbol, qty, side, time_in_force, stop_price=None, limit_price=None, extended_hours=False, stop_loss=None):
        """
        params:
            order_type (str): The order type to make ['market', 'limit', 'stop', 'stop_limit']
            symbol (str): The stock symbol to trade
            qty (float/int): The number of shares (fractional allowed for market orders)
            side (str): 'buy' or 'sell'
            time_in_foce (str): 'day' or 'gtc'
            stop_price (float): The stop price for stop or stop-limit orders
            limit_price (float): The limit price for limit or stop-limit orders
            extended_hours (bool): Whether to allow extended hours trading
            stop_loss (float): The stop loss price (will likely implement serpate logic for the strategy itself)
            
        """
        # Shouldn't need the lower, but to be safe for later development
        side_enum = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
        time_in_force_enum = TimeInForce.DAY if time_in_force.lower() == 'day' else TimeInForce.GTC
        
        if order_type == 'market':
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,  # Choosing to use qty instead of notional
                side=side_enum,
                time_in_force=time_in_force_enum,
                extended_hours=extended_hours,
            )
        # Instead of using StopLossRequest() likely a good idea to place a limit order with stop loss logic
        elif order_type == 'limit':
            if limit_price is None:
                raise ValueError("limit_price is required for limit orders")
            order_data = LimitOrderRequest(
                symbol=symbol,
                qty=qty,  # Choosing to use qty instead of notional
                side=side_enum,
                time_in_force=time_in_force_enum,
                extended_hours=extended_hours,
                limit_price=limit_price
            ) 
        elif order_type == 'stop': 
            if stop_price is None:
                raise ValueError("stop_price is required for stop orders")
            order_data = StopOrderRequest(
                symbol=symbol,
                qty=qty,  # Choosing to use qty instead of notional
                side=side_enum,
                time_in_force=time_in_force_enum,
                extended_hours=extended_hours,
                stop_price=stop_price
            ) 
        elif order_type == 'stop_limit':
            if limit_price is None or stop_price is None:
                raise ValueError("Both limit_price and stop_price are required for stop-limit orders")
            order_data = StopLimitOrderRequest(
                symbol=symbol,
                qty=qty,  # Choosing to use qty instead of notional
                side=side_enum,
                time_in_force=time_in_force_enum,
                extended_hours=extended_hours,
                stop_price=stop_price,
                limit_price=limit_price
            ) 
        else:
            raise ValueError("Invalid order type specified")
        
        
        res = self.trading_client.submit_order(order_data)
        return res
        # Decide what to do with this information
        
    
    def place_option_order(self):
        pass 
    
        
    def results_for_day(self):
        """
        Get the results for the day; optionally send to a csv/database
        """
        pass 
    
    
    def run(self):
        print(f"Trading window: {self.trade_start} → {self.trade_end}")

        while True:
            now = datetime.datetime.now().time()

            # Before market opens
            if now < self.trade_start:
                print("Market not open yet — waiting...")
                time.sleep(60)
                continue

            # After market closes
            if now >= self.trade_end:
                print("Market closed — stopping trading.")
                break

            # Main trading logic
            self.check_signals()

        self.results_for_day()