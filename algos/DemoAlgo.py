# A demonstration of how to implement an algorithmic trading strategy
# This will just place one buy and sell order automatically, but use signal logic

import sys
import os 

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from traders.BaseTrader import BaseTrader


class DemoAlgo(BaseTrader):
    def __init__(self):
        super().__init__()
        

    def check_signals(self):
        pass 
    
    
# A sample of how to place an order, will need to be implemented alongside check_signals()
if __name__ == "__main__":
    trader = DemoAlgo()
    trader.verify_account()
    
    buy_order = trader.place_trade_order(
        order_type='market',
        symbol='AAPL',
        qty=1,
        side='buy',
        time_in_force='day'
    )
    print("Buy order submitted:", buy_order)
