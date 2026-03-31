import pandas as pd 

# I want to use this to inspire my backtesting framework
#   https://www.youtube.com/watch?v=NLBXgSmRBgU
class Backtester: 
    def __init__(self):
        self.data_dir = "backtesting/data"
        self.results_dir = "backtesting/results"
        
        # For storing results of backtests
        self.backtest_results = pd.DataFrame(columns=["date", "time", "portfolio_value", "live_order", "unrealized_pnl", "realized_pnl", "total_pnl"])
    
    def test_module(self, module):
        # Provide a class of an algorithm to test for trading (note all my modules will have the same structure as defined in traders/BaseTrader.py)
        pass 
        # IMPLEMENT DIVIDENDS AS A FORM OF REVENUE IF WE TARGET THEM
    
    def run_backtests(self):
        # Run backtests for all algorithms, and store results in a csv/database
        pass