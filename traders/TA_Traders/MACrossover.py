# Inspiration https://trendspider.com/learning-center/moving-average-crossover-strategies/ 

from traders.BaseTrader import BaseTrader
from utils.MathUtils import MathUtils
import pandas as pd


class SingleMACrossover(BaseTrader):
     # This algo only relies on candle data (ohlc) so we won't need to consider other data

    def __init__(self, window_size=50):
        super().__init__()
        self.window_size = window_size

        self.holding = False  # We will not let this strategy have multiple holdings at once

    
    def check_signals(self):
        """
        Buy signal: Price closes above the moving average
        Sell signal: Price closes below the moving average
        """
        if len(self.data) < self.window_size + 1:
            return 0  # Need 'window_size' days to compute ma here
        
        # Calculate the moving average(s) for past 'window_size' days (should make function; i have a function to do this on an entire df already)
        ma = MathUtils.sma(self.ohlc_data, self.window_size)
        crossover = MathUtils.crossover(self.ohlc_data["close"], ma)

        last_cross = crossover.iloc[-1]
        last_close = self.ohlc_data["close"].iloc[-1]
        last_ma = ma.iloc[-1]

        # Test for buy
        if not self.holding:
            if last_cross == 1: 
                return 1  # This is a buy signal
        else:
            if last_cross == -1:
                return -1  # This is a sell signal
        return 0  # This is hold/wait signal