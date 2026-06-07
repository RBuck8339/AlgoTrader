import asyncio
import requests
from dotenv import load_dotenv
import os
import pandas as pd
from abc import ABC, abstractmethod
import time 
from collections import defaultdict

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scrapers.stream.KrakenScraper import KrakenScraper
from utils.KrakenUtils import KrakenUtils

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
        
        # Execution variables
        self.execution_mode = "paper"  # Change to "live" when ready to go live
        self.holding = False

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
        
        # Setup (TODO might make htis a function to just return signature with the nonce)
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
        """
        Live order placing through kraken (TODO NEEDS TESTING)
        """
        curr_ask, curr_bid = self.scraper.get_current_price(ticker)
        
        fee_rate = FEE_RATE # Fee is applied on both buy and sell
        
        url_path = "/0/private/AddOrder"
        
        # Setup (TODO might make htis a function to just return signature with the nonce)
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
            coins_to_close = self.paper_trade_targets["volume"]
            
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
            coins_to_close = self.paper_trade_targets["volume"]
            
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
    def check_signals(self, dfs, interval_posted):
        """
        Abstract method to check for trading signals based on strategy
        """
        raise NotImplementedError("Subclasses must implement check_signals(dfs, interval_posted) method for their strategy")
    
    
    # NOTE Retrying with REST
    async def main(self, methods_to_run=[], setting='paper', num_votes=None, intervals=[1, 5, 240]):
        if len(methods_to_run) == 0:
            raise ValueError("[ERROR] At least one method must be provided to run the trader.")
        if num_votes is None:
            num_votes = len(methods_to_run)

        print(f"[INFO] REST Polling Engine activated for intervals: {intervals}")
        url_path = "/0/public/OHLC"
        
        # Track last processed timestamps per interval to guarantee no duplicate rows (could do df.drop_duplicates later if needed)
        self.last_processed_timestamps = {interval: None for interval in intervals}
        
        all_dfs = {}  # Dfs for each interval
        
        print("[INFO INIT] Getting base historical data for active intervals")
        for interval in intervals:
            try:
                params = {"pair": self.ticker, "interval": interval}
                response = requests.get(self.base_url + url_path, params=params)
                data = response.json()
                ticker_key = list(data["result"].keys())[0]
                df = pd.DataFrame(data["result"][ticker_key], columns=[
                    "timestamp", "open", "high", "low", "close", "vwap", "volume", "count"
                ])
                closed_df = df.iloc[:-1].copy()
                for col in ["open", "high", "low", "close", "volume"]:
                    closed_df[col] = closed_df[col].astype(float)
                
                all_dfs[interval] = closed_df
                self.last_processed_timestamps[interval] = int(closed_df.iloc[-1]["timestamp"])
                print(f"[INFO] Baseline loaded for {interval}m cache.")
            except Exception as e:
                print(f"[ERROR] Failed to seed initial baseline for {interval}m: {e}")

        while True:
            await asyncio.sleep(60 - (time.time() % 60))  # Wake up processing each minute to collect the candle
            
            current_minute = int(time.time() // 60)
            
            intervals_processed_this_loop = []

            print("[DEBUG] Attempting to grab data")

            # Poll REST for each interval
            for interval in intervals:
                if current_minute % interval != 0:
                    continue

                try:
                    params = {"pair": self.ticker, "interval": interval}
                    response = requests.get(self.base_url + url_path, params=params)
                    data = response.json()
                    
                    if "error" in data and data["error"]:
                        print(f"[ERROR (NONFATAL)] Kraken API Error for {interval}m: {data['error']}")
                        continue
                        
                    ticker_key = list(data["result"].keys())[0]
                    raw_candles = data["result"][ticker_key]

                    df = pd.DataFrame(raw_candles, columns=[
                        "timestamp", "open", "high", "low", "close", "vwap", "volume", "count"
                    ])
                    
                    closed_df = df.iloc[:-1].copy()  # Last row is an unclosed candle
                    
                    if closed_df.empty:
                        continue
                        
                    latest_closed_ts = int(closed_df.iloc[-1]["timestamp"])
                    
                    # Verify is new candle
                    if self.last_processed_timestamps[interval] == latest_closed_ts:
                        continue
                    
                    for col in ["open", "high", "low", "close", "volume"]:
                        closed_df[col] = closed_df[col].astype(float)

                    # Update memory
                    all_dfs[interval] = closed_df
                    self.last_processed_timestamps[interval] = latest_closed_ts
                    intervals_processed_this_loop.append(interval)
                    
                    print(f"[DEBUG] Processed interval: {interval}")

                except Exception as e:
                    print(f"[ERROR] REST Data Pull Error for {interval}m interval: {e}")

            # Check signals for all methods
            if intervals_processed_this_loop:
                interval_to_process = max(intervals_processed_this_loop)  # Strategies will typically depend on higher candles first
                
                if all(i in all_dfs for i in intervals):
                    print(f"[DEBUG] Checking signals for up to {interval_to_process}m candles")
                    signals = []
                    for method in methods_to_run:
                        signals.append(method.check_signals(dfs=all_dfs, interval_posted=interval_to_process))

                    # Vote buy
                    if not self.holding:
                        trade_budget_usd = self.account_value * 0.10 if self.account_value else 1000.0
                        if signals.count("BUY_LONG") >= num_votes:
                            self.order_placer(amount=trade_budget_usd, ticker=self.ticker, action="BUY_LONG")
                        elif signals.count("BUY_SHORT") >= num_votes:
                            self.order_placer(amount=trade_budget_usd, ticker=self.ticker, action="BUY_SHORT")
                
                
    def setup_trading(self, methods, setting='paper'):
        """
        params:
            methods: List of (method, param dict) tuples to run for setup
        """
        
        # Init each method
        initialized_methods = []
        for method, params in methods:
            initialized_methods.append(method(**params))
            
        self.order_placer = self.place_order_paper if setting == 'paper' else self.place_order_live
        asyncio.run(self.main(methods_to_run=initialized_methods, setting=setting))