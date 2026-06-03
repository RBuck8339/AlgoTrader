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
            # on_bar=self.on_new_bar
        )
        
        # For API usage
        self.base_url = "https://api.kraken.com"
        self.data_api_secret = os.getenv("KRAKEN_DATA_KEY_PRIVATE")
        self.data_api_key = os.getenv("KRAKEN_DATA_KEY_PUBLIC")
        self.starting_account_value = None
        self.account_value = None


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
            
            # 📬 PUSH TO QUEUE: Tell the main thread a new bar is officially ready!
            # loop.call_soon_threadsafe is used if your scraper runs on a separate thread
            asyncio.run_coroutine_threadsafe(
                self.bar_queue.put(interval), 
                asyncio.get_event_loop()
            )
            
        elif last_ts is None:
            self.last_closed_timestamps[interval] = current_ts
            self.ohlc_history[interval].append(candle)
            
            
    def get_dataframe(self, interval):
        """Helper to instantly generate an analytical dataframe."""
        df = pd.DataFrame(self.ohlc_history[interval])
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df
            

    def get_account_value(self):
        url_path = "/0/private/TradeBalance"  # Can probably just make this a param for a multi-function function
        
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
        
        
    def verify_account(self):
        # TODO Verify connection to account (Can also be done through get_account_value tbh)
        pass
    
    
    def place_order_live(self, amount: float, ticker: str, action: str, risk_percent=0.02, risk_ratio=2.0):
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
                stop_loss_price = round(entry_price * (1 -risk_percent * 1), 2)
                take_profit_price = round(entry_price * (1 + risk_percent * risk_ratio), 2)
                print(f"\t[INFO: Open Long] Bought {trade_amount_coins} {ticker} at ${entry_price:.2f}.")

                # TODO API CALL HERE
                
            elif action == "BUY_SHORT":
                # Shorting adds the sold coin revenue to your wallet, minus the fee
                gross_revenue_usd = trade_amount_coins * entry_price
                fee_usd = gross_revenue_usd * fee_rate
                self.account_value += (gross_revenue_usd - fee_usd)
                
                # Setup inverted short targets (Loss is up, Profit is down)
                stop_loss_price = round(entry_price * (1 + risk_percent * 1), 2)
                take_profit_price = round(entry_price * (1 - risk_percent * risk_ratio), 2)
                print(f"\t[INFO: Open Short] Shorted {trade_amount_coins} {ticker} at ${entry_price:.2f}.")
            
                # TODO API CALL HERE
            
            # Place limits on the trade
            print(f"\t[INFO: Set Targets] Stop Loss at ${stop_loss_price:.2f}, Take Profit at ${take_profit_price:.2f}.")
            self.place_take_and_stop(stop_loss_price, take_profit_price, trade_id="simulated_trade_id", action='paper')

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
                
                # TODO API CALL HERE
                
            elif action == "SELL_SHORT":
                # Closing a short means buying back the debt instantly at the ASK
                exit_price = curr_ask
                gross_buyback_cost = coins_to_close * exit_price
                fee_usd = gross_buyback_cost * fee_rate
                
                # Cash is stripped from your wallet to pay for the buyback + fee
                self.account_value -= (gross_buyback_cost + fee_usd)
                print(f"\t[INFO: Close Short] Covered {coins_to_close} {ticker} at Ask ${exit_price:.2f}. Wallet: ${self.account_value:.2f}")
        
                # TODO API CALL HERE
        
        else:
            raise ValueError("Invalid action specified for live trading")
    
    
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
                stop_loss_price = round(entry_price * (1 -risk_percent * 1), 2)
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
            self.place_take_and_stop(stop_loss_price, take_profit_price, trade_id="simulated_trade_id", action='paper')

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
        
        
    def place_take_and_stop(self, stop_loss_price, take_profit_price, trade_id, action):
        # Place take profit and stop loss orders based on entry price and desired risk/reward
        if action == 'live':
            pass 
        
        elif action == 'paper':
            self.paper_trade_targets[trade_id] = {
                "stop_loss": stop_loss_price,
                "take_profit": take_profit_price
            }
            # We would now need to monitor and do the sale here while keeping data acquisition alive
        
        
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
        raise NotImplementedError("Subclasses must implement check_signals method for their strategy")
