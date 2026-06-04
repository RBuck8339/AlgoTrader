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
from utils import KrakenUtils

# ENV Variables
load_dotenv()

FEE_RATE = 0.0026  # Kraken's fee rate for crypto trading (can vary based on volume)

# Minimum purchase amounts based on Kraken's requirements (varies by asset, value represented in terms of coins)
MIN_PURCHASE_AMOUNT = {
    "BTC/USD": 0.0001,  
    "ETH/USD": 0.01,
    "SOL/USD": 0.1,
}

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
        )
        
        # Stream hooks linking scraper updates to BaseTrader
        self.scraper.on_bar = self.on_new_bar
        self.scraper.on_trade = self.on_new_trade
        
        # For API usage
        self.base_url = "https://api.kraken.com"
        self.data_api_secret = os.getenv("KRAKEN_DATA_KEY_PRIVATE")
        self.data_api_key = os.getenv("KRAKEN_DATA_KEY_PUBLIC")
        self.starting_account_value = None
        self.account_value = None
        
        execution_mode = "paper"  # Change to "live" when ready to go live

        self.paper_trade_targets = {}  # trade_id: {"stop_loss": price, "take_profit": price}  (Used to simulate take profit and stop loss)


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
            
            asyncio.run_coroutine_threadsafe(
                self.bar_queue.put(interval), 
                asyncio.get_event_loop()
            )
            
        elif last_ts is None:
            self.last_closed_timestamps[interval] = current_ts
            self.ohlc_history[interval].append(candle)


    def on_new_trade(self, trade_data):
        """Callback for when a new trade is received from the data stream."""
        if self.execution_mode == "paper":
            self.monitor_paper_exits(current_candle=None, ticker=self.ticker)
        


    def get_dataframe(self, interval):
        """Helper to instantly generate a dataframe. Saves memory"""
        df = pd.DataFrame(self.ohlc_history[interval])
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df


    def get_account_value(self):
        url_path = "/0/private/TradeBalance"
        
        # Setup
        nonce = int(time.time() * 1000)
        payload = {
            "nonce": nonce, 
            "asset": "ZUSD"
        }
        signature = KrakenUtils.get_kraken_signature(url_path, payload, self.data_api_secret)
        headers = {
            "API-Key": self.data_api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        response = requests.post(url=self.base_url + url_path, headers=headers, data=payload)
        data = response.json()
        self.starting_account_value = data["result"]["eb"] if self.starting_account_value is None else self.starting_account_value  # Don't overwrite later
        self.account_value = data["result"]["eb"]
        
        return self.account_value


    def place_order_live(self, amount: float, ticker: str, action: str, risk_percent=0.02, risk_ratio=2.0):
        # TODO Implement live order execution endpoints
        pass


    def place_order_paper(self, amount: float, ticker: str, action: str, risk_percent=0.02, risk_ratio=2.0):
        # Place a paper order, default is long order (optional short)
        """
        Since kraken doesn't offer paper trading, we just simulate here
        """
        curr_ask, curr_bid = self.scraper.get_current_price(ticker)
        
        fee_rate = FEE_RATE # Fee is applied on both buy and sell
        
        # To open a position
        if action.split("_")[0] == "BUY" and action in ["BUY_LONG", "BUY_SHORT"]:
            # Set entry prices based on book spread and figure out how many coins to buy
            entry_price = curr_ask if action == "BUY_LONG" else curr_bid
            trade_amount_coins = round(amount / entry_price, 6)
            
            # Guard rail check against Kraken volume minimum constraints
            if trade_amount_coins < MIN_PURCHASE_AMOUNT.get(ticker, 0):
                print(f"\t[DEBUG: Order Rejected] {trade_amount_coins} coins is below minimum required for {ticker}.")
                return
            
            stop_loss_price = 0
            take_profit_price = 0
        
            if action == "BUY_LONG":
                # Entry costs your wallet cash + the taker fee
                total_cost_usd = (trade_amount_coins * entry_price) * (1 + fee_rate)
                self.account_value -= total_cost_usd 
                
                # Setup standard long targets
                stop_loss_price = round(entry_price * (1 - risk_percent * 1), 2)
                take_profit_price = round(entry_price * (1 + risk_percent * risk_ratio), 2)
                print(f"\t[INFO: Open Long] Bought {trade_amount_coins} {ticker} at ${entry_price:.2f}.")

            elif action == "BUY_SHORT":
                # Shorting adds the sold coin revenue to your wallet, minus the fee
                gross_revenue_usd = trade_amount_coins * entry_price
                fee_usd = gross_revenue_usd * fee_rate
                self.account_value += (gross_revenue_usd - fee_usd)
                
                # Setup inverted short targets (Loss is up, Profit is down)
                stop_loss_price = round(entry_price * (1 + risk_percent * 1), 2)
                take_profit_price = round(entry_price * (1 - risk_percent * risk_ratio), 2)
                print(f"\t[INFO: Open Short] Shorted {trade_amount_coins} {ticker} at ${entry_price:.2f}.")
            
            # Place limits on the trade
            print(f"\t[INFO: Set Targets] Stop Loss at ${stop_loss_price:.2f}, Take Profit at ${take_profit_price:.2f}.")
            
            position_type = "LONG" if action == "BUY_LONG" else "SHORT"
            self.place_take_and_stop(
                stop_loss_price=stop_loss_price, 
                take_profit_price=take_profit_price, 
                trade_id="simulated_trade_id", 
                action='paper',
                position_type=position_type,
                volume=trade_amount_coins
            )

        # Allows closing trades
        elif action.split("_")[0] == "SELL" and action in ["SELL_LONG", "SELL_SHORT"]:
            coins_to_close = amount 
            
            if action == "SELL_LONG":
                # Selling your long position instantly hits the BID
                exit_price = curr_bid
                gross_return_usd = coins_to_close * exit_price
                fee_usd = gross_return_usd * fee_rate
                
                # Cash flows back into your wallet minus the transaction fee
                self.account_value += (gross_return_usd - fee_usd)
                print(f"\t[INFO: Close Long] Sold {coins_to_close} {ticker} at Bid ${exit_price:.2f}. Wallet: ${self.account_value:.2f}")
                
            elif action == "SELL_SHORT":
                # Closing a short means buying back the debt instantly at the ASK
                exit_price = curr_ask
                gross_buyback_cost = coins_to_close * exit_price
                fee_usd = gross_buyback_cost * fee_rate
                
                # Cash is stripped from your wallet to pay for the buyback + fee
                self.account_value -= (gross_buyback_cost + fee_usd)
                print(f"\t[INFO: Close Short] Covered {coins_to_close} {ticker} at Ask ${exit_price:.2f}. Wallet: ${self.account_value:.2f}")
        
        else:
            raise ValueError("Invalid action specified for paper trading")


    def place_take_and_stop(self, stop_loss_price, take_profit_price, trade_id, action, position_type=None, volume=0.0, interval_to_monitor=1):
        # Place take profit and stop loss orders based on entry price and desired risk/reward
        if action == 'live':
            pass 
        
        elif action == 'paper':
            self.paper_trade_targets = {
                "stop_loss": stop_loss_price,
                "take_profit": take_profit_price,
                "position_type": position_type,  # "LONG" or "SHORT"
                "volume": volume,                # Total coins held in the trade
                "active": True
            }


    def monitor_paper_exits(self, ticker, current_candle=None):
        """
        Monitors the active trade against real-time book prices on every incoming tick.
        """
        # If there are no open paper trades recorded, skip processing
        if not hasattr(self, 'paper_trade_targets') or not self.paper_trade_targets.get("active"):
            return
            
        curr_ask, curr_bid = self.scraper.get_current_price(ticker)
        
        targets = self.paper_trade_targets
        pos_type = targets["position_type"]
        coins = targets["volume"]
        sl = targets["stop_loss"]
        tp = targets["take_profit"]
        
        # Long Position
        if pos_type == "LONG":
            if curr_bid <= sl:
                print(f"\n[Stop Loss] Long Bid ${curr_bid:.2f} dropped below SL ${sl:.2f}")
                targets["active"] = False # Stop monitoring before running execution
                self.place_order_paper(amount=coins, ticker=ticker, action="SELL_LONG")
                
            elif curr_bid >= tp:
                print(f"\t[Take Profit] Long Bid ${curr_bid:.2f} hit target TP ${tp:.2f}")
                targets["active"] = False
                self.place_order_paper(amount=coins, ticker=ticker, action="SELL_LONG")
                
        # Short Position
        elif pos_type == "SHORT":
            if curr_ask >= sl:
                print(f"\t[Stop Loss] Short Ask ${curr_ask:.2f} pumped above SL ${sl:.2f}")
                targets["active"] = False
                self.place_order_paper(amount=coins, ticker=ticker, action="SELL_SHORT")
                
            elif curr_ask <= tp:
                print(f"\t[INFO: Take Profit] Short Ask ${curr_ask:.2f} hit target TP ${tp:.2f}")
                targets["active"] = False
                self.place_order_paper(amount=coins, ticker=ticker, action="SELL_SHORT")


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


    @abstractmethod
    def check_signals(self):
        """
        Abstract method to check for trading signals based on strategy
        """
        raise NotImplementedError("Subclasses must implement check_signals method for their strategy")
    
    
    async def main(self, methods_to_run=[], setting='paper', num_votes=None, intervals=[1, 5, 240]):
        """
        Main function to run trader
        Capabilities:
            - Start Streaming Data
            - Check for signals from n methods
            - Place orders when ALL signals align
            - Return data for the day at the end of each day
        
        params:
            methods_to_run: List of (method)
            setting: 'paper' or 'live'
        """
        
        # Just in case, should never happen tho
        if len(methods_to_run) == 0:
            raise ValueError("At least one method must be provided to run the trader.")
        
        if num_votes == None:
            num_votes = len(methods_to_run)  # Default to unanimous vote if not specified
        
        # Start streaming data in background
        asyncio.create_task(self.scraper.stream(intervals=intervals))
        
        print(f"[INFO] Data streaming started for intervals: {intervals}")
        print(f"[INFO] Trader started in {setting} mode with {len(methods_to_run)} methods")
        
        # optionally, can run this on a timer (say every minute for minute candles)
        while True:
            interval_posted = await self.bar_queue.get() 
            
            signals = []  # In case we do voting later, this will allow counting how many methods are signaling the same thing
            for method in methods_to_run:
                signals.append(method.check_signals())
                
            # Vote buy
            if (not self.holding) and signals.count(1) >= num_votes:
                self.order_placer(
                    amount=0,
                    ticker=self.ticker,
                    action="BUY_LONG" if self.position_type == "LONG" else "BUY_SHORT",
                    risk_percent=0.02,
                    risk_ratio=2.0
                )
            
            # Vote sell
            elif self.holding and signals.count(-1) >= num_votes:
                self.order_placer(
                    amount=0,
                    ticker=self.ticker,
                    action="SELL_LONG" if self.position_type == "LONG" else "SELL_SHORT",
                    risk_percent=0.02,
                    risk_ratio=2.0
                )
                
            # Take profit and stop losses should automatically be monitored by kraken, so we don't account for it here
                
            self.bar_queue.task_done()
                
                
    def setup(self, methods, setting='paper'):
        """
        params:
            methods: List of (method, param dict) tuples to run for setup
        """
        
        # Init each method
        initialized_methods = []
        for method, params in methods:
            initialized_methods.append(method(**params))
            
        self.order_placer = self.place_order_paper if setting == 'paper' else self.place_order_live
        self.main(methods_to_run=initialized_methods, setting=setting)