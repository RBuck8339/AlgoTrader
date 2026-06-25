import os
import sys
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd

from backtesting.CryptoHistoryGrabber import KrakenHistoricalScraper
from backtesting.Visualizer import Visualizer
from traders.Scalpers.Breakout5mScalper import Breakout5mScalper

INTERVAL_MAP = {
    1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h",
    240: "4h", 1440: "1d", 10080: "1w", 21600: "15d"
}


class Backtester:
    def __init__(self, required_intervals=[1, 5, 240]):
        self.data_dir = "backtesting/data"
        self.results_dir = "backtesting/results"
        self.backtest_results_overall = []
        self.backtest_summary = pd.DataFrame(columns=["module_name", "portfolio_value", "num_trades", "realized_pnl", "total_pnl"])
        self.historical_data = {}
        self.required_intervals = required_intervals
        self.trade_num = 0  
        self.active_positions = {}


    def test_module(self, module, risk_percent=0.02, pl_ratio=3.0):
        if not self.historical_data:
            raise RuntimeError("No historical data loaded. Call load_historical_data() first.")

        backtest_results = pd.DataFrame(columns=["date", "time", "portfolio_value", "live_order", "unrealized_pnl", "realized_pnl", "total_pnl", "trade_made"])

        portfolio_value_realized = 100000.0
        bar_idx = 0
        trade_pnl_list = []
        trade_duration_list = []
        self.active_positions.clear()
        self.trade_num = 0

        df_1m_base = self.historical_data[1]["ohlc"]
        trade_data = self.historical_data[1]["trades"]

        print(f"\n[INFO] Backtest starting")
        
        historical_ticks_list = []
        
        for curr_time, row_1m in df_1m_base.iterrows():
            print(curr_time)  
            bar_idx += 1
            
            all_dfs = {}
            for interval in self.required_intervals:
                full_df = self.historical_data[interval]["ohlc"]
                historical_slice = full_df.loc[full_df.index <= curr_time].copy()
                
                for col in ["open", "high", "low", "close", "volume"]:
                    historical_slice[col] = historical_slice[col].astype(float)
                
                all_dfs[interval] = historical_slice

            current_timestamp_seconds = int(curr_time.timestamp())
            intervals_posted = []
            for interval in self.required_intervals:
                if current_timestamp_seconds % (interval * 60) == 0:
                    intervals_posted.append(interval)

            end_time = curr_time + pd.Timedelta(minutes=1)
            current_block_trades = trade_data.loc[
                (trade_data.index >= curr_time) & (trade_data.index < end_time)
            ].sort_index()

            trade_made = False

            for idx_trade, row_trade in current_block_trades.iterrows():
                historical_ticks_list.append(row_trade.to_dict())
                curr_price = float(row_trade["price"])

                portfolio_value_realized = self._manage_brackets_risk(curr_price, portfolio_value_realized, bar_idx, trade_pnl_list, trade_duration_list)

                if module.signal_on == "tick":
                    trades_df = pd.DataFrame(historical_ticks_list)
                    signal = module.check_signals(dfs=all_dfs, intervals_posted=intervals_posted, curr_time=curr_time, trades=trades_df)
                    
                    position_to_sell = None 
                    if type(signal) == tuple:
                        signal, position_to_sell = signal 
                    
                    new_order_data = {
                        "risk_percent": risk_percent,
                        "ratio": pl_ratio,
                        "bar_idx": bar_idx,
                        "signal": signal,
                    }
                    
                    portfolio_value_realized = self._execute_signal(
                        curr_price, portfolio_value_realized, new_order_data=new_order_data, 
                        positions_to_sell=[] if position_to_sell is None else position_to_sell,
                        bar_idx=bar_idx, pnl_list=trade_pnl_list, duration_list=trade_duration_list
                    )

            close_price = float(row_1m["close"])
            curr_price = close_price if curr_price == 0.0 else curr_price

            portfolio_value_realized = self._manage_brackets_risk(close_price, portfolio_value_realized, bar_idx, trade_pnl_list, trade_duration_list)

            if module.signal_on == "candle":
                if any(i in intervals_posted for i in self.required_intervals if i != 1):
                    signal = module.check_signals(dfs=all_dfs, intervals_posted=intervals_posted, curr_time=curr_time)
                    
                    position_to_sell = None
                    if type(signal) == tuple:
                        signal, position_to_sell = signal 
                    
                    new_order_data = {
                        "risk_percent": risk_percent,
                        "ratio": pl_ratio,
                        "bar_idx": bar_idx,
                        "signal": signal,
                    }

                    portfolio_value_realized = self._execute_signal(
                        close_price, portfolio_value_realized, new_order_data=new_order_data, 
                        positions_to_sell=[] if position_to_sell is None else position_to_sell,
                        bar_idx=bar_idx, pnl_list=trade_pnl_list, duration_list=trade_duration_list
                    )
            
            portfolio_value_unrealized = portfolio_value_realized
            for key, pos in self.active_positions.items():
                if pos["position_type"] == "LONG":
                    portfolio_value_unrealized += (close_price * pos["shares_held"])
                elif pos["position_type"] == "SHORT":
                    portfolio_value_unrealized += (pos["entry_value"] - (close_price * pos["shares_held"]))

            trade_made = len(trade_pnl_list) > 0

            backtest_results.loc[curr_time] = {
                "date": curr_time.date(),
                "time": curr_time.time(),
                "portfolio_value": portfolio_value_unrealized,
                "live_order": len(self.active_positions) > 0,
                "unrealized_pnl": portfolio_value_unrealized - portfolio_value_realized,
                "realized_pnl": portfolio_value_realized - 100000.0,
                "total_pnl": portfolio_value_unrealized - 100000.0,
                "trade_made": trade_made,
            }

        final_value = portfolio_value_realized
        for key, pos in self.active_positions.items():
            if pos["position_type"] == "LONG":
                final_value += (close_price * pos["shares_held"])
            elif pos["position_type"] == "SHORT":
                final_value += (pos["entry_value"] - (close_price * pos["shares_held"]))

        total_pnl = final_value - 100000.0
        print(f"\nBacktest complete. Final portfolio: ${final_value:,.2f}")
        print(f"Total P&L: ${total_pnl:,.2f}")

        portfolio_series = backtest_results["portfolio_value"]
        viz_data = {
            "portfolio_value": portfolio_series,
            "trade_pnl": pd.Series(trade_pnl_list),
            "daily_returns": portfolio_series.pct_change().dropna(),
            "trade_duration": pd.Series(trade_duration_list),
        }

        return backtest_results, final_value, total_pnl, viz_data


    def _manage_brackets_risk(self, current_price, cash, bar_idx, pnl_list, duration_list):
        closed_keys = []
        
        for key, pos in self.active_positions.items():
            sold = False
            pnl_val = 0.0
            
            if pos["position_type"] == "LONG":
                if current_price <= pos["stop_loss_price"]:
                    pnl_val = (pos["shares_held"] * current_price) - pos["entry_value"]
                    cash += (pos["shares_held"] * current_price)
                    sold = True
                    print(f"   [STOP LONG #{key}] @ {current_price:.2f} | pnl={pnl_val:.2f}")
                elif current_price >= pos["take_profit_price"]:
                    pnl_val = (pos["shares_held"] * current_price) - pos["entry_value"]
                    cash += (pos["shares_held"] * current_price)
                    sold = True
                    print(f"   [TAKE LONG #{key}] @ {current_price:.2f} | pnl={pnl_val:.2f}")
                    
            elif pos["position_type"] == "SHORT":
                if current_price >= pos["stop_loss_price"]:
                    pnl_val = pos["entry_value"] - (pos["shares_held"] * current_price)
                    cash -= (pos["shares_held"] * current_price)
                    sold = True
                    print(f"   [STOP SHORT #{key}] @ {current_price:.2f} | pnl={pnl_val:.2f}")
                elif current_price <= pos["take_profit_price"]:
                    pnl_val = pos["entry_value"] - (pos["shares_held"] * current_price)
                    cash -= (pos["shares_held"] * current_price)
                    sold = True
                    print(f"   [TAKE SHORT #{key}] @ {current_price:.2f} | pnl={pnl_val:.2f}")
            
            if sold:
                pnl_list.append(pnl_val)
                duration_list.append(bar_idx - pos["entry_bar"])
                closed_keys.append(key)

        for k in closed_keys:
            del self.active_positions[k]
            
        return cash


    def _execute_signal(self, curr_price, portfolio_value_realized, new_order_data=None, positions_to_sell=[], bar_idx=0, pnl_list=[], duration_list=[]):
        if new_order_data is not None and new_order_data["signal"] in ["BUY_LONG", "BUY_SHORT"]:
            signal = new_order_data["signal"]
            allocated_capital = portfolio_value_realized * new_order_data["risk_percent"]
            num_shares_held = allocated_capital / curr_price
            
            if signal == "BUY_LONG":
                stop_loss_price = curr_price * (1 - new_order_data["risk_percent"])
                take_profit_price = curr_price * (1 + new_order_data["risk_percent"] * new_order_data["ratio"])
                portfolio_value_realized -= allocated_capital
                print(f"   BUY_LONG   @ {curr_price:.2f} | shares={num_shares_held:.4f} | stop={stop_loss_price:.2f}")
                
            elif signal == "BUY_SHORT":
                stop_loss_price = curr_price * (1 + new_order_data["risk_percent"]) 
                take_profit_price = curr_price * (1 - new_order_data["risk_percent"] * new_order_data["ratio"])
                portfolio_value_realized += allocated_capital 
                print(f"   BUY_SHORT  @ {curr_price:.2f} | shares={num_shares_held:.4f} | stop={stop_loss_price:.2f}")
             
            self.trade_num += 1
            self.active_positions[self.trade_num] = {
                "position_type": signal.split("_")[-1],  
                "shares_held": num_shares_held,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
                "entry_value": allocated_capital,
                "entry_bar": bar_idx
            } 

        if positions_to_sell:
            closed_override_keys = []
            for key in positions_to_sell:
                if key in self.active_positions:
                    pos = self.active_positions[key]
                    pnl_val = 0.0
                    
                    if pos["position_type"] == "LONG":
                        pnl_val = (pos["shares_held"] * curr_price) - pos["entry_value"]
                        portfolio_value_realized += (pos["shares_held"] * curr_price)
                        print(f"   SELL_LONG  @ {curr_price:.2f} | pnl={pnl_val:.2f}")
                    elif pos["position_type"] == "SHORT":
                        pnl_val = pos["entry_value"] - (pos["shares_held"] * curr_price)
                        portfolio_value_realized -= (pos["shares_held"] * curr_price)
                        print(f"   SELL_SHORT @ {curr_price:.2f} | pnl={pnl_val:.2f}")
                        
                    pnl_list.append(pnl_val)
                    duration_list.append(bar_idx - pos["entry_bar"])
                    closed_override_keys.append(key)
                    
            for k in closed_override_keys:
                del self.active_positions[k]

        return portfolio_value_realized


    def run_backtests(self):
        modules = [
            (Breakout5mScalper, "candle", {}),
        ]

        for module, signal_on, param_dict in modules:
            curr_instance = module()
            curr_instance.signal_on = signal_on
            res, final_value, total_pnl, viz_data = self.test_module(curr_instance)

            self.backtest_results_overall.append(res)

            curr_agg_data = {
                "module_name": curr_instance.__class__.__name__,
                "portfolio_value": final_value,
                "num_trades": len(viz_data["trade_pnl"]),
                "realized_pnl": res.iloc[-1]["realized_pnl"],
                "total_pnl": total_pnl,
            }
            self.backtest_summary.loc[len(self.backtest_summary)] = curr_agg_data


    def load_historical_data(self, data_type, ticker, start_date, end_date, frequency):
        interval_label = INTERVAL_MAP.get(frequency, f"{frequency}m")
        safe_ticker = ticker.replace("/", "")
        since_ts = int(start_date.timestamp())
        
        start_dt_normalized = datetime.utcfromtimestamp(since_ts)
        if start_dt_normalized.year == 2022 and start_dt_normalized.month == 12 and start_dt_normalized.day == 31:
            start_str = "20230101"
        else:
            start_str = start_dt_normalized.strftime('%Y%m%d')
            
        end_str = end_date.strftime('%Y%m%d')

        if data_type == "stock":
            data_path_ohlc = os.path.join(self.data_dir, f"{safe_ticker}_{interval_label}_ohlc_{start_str}_to_{end_str}.csv")
            data_path_trades = os.path.join(self.data_dir, f"{safe_ticker}_trades_{start_str}_to_{end_str}.csv")
            if not os.path.exists(data_path_ohlc):
                raise FileNotFoundError(f"Stock OHLC data not found: {data_path_ohlc}.")

            self.historical_data = {
                "ohlc": pd.read_csv(data_path_ohlc, parse_dates=["timestamp"], index_col="timestamp"),
                "trades": None,
            }

        elif data_type == "crypto":
            data_path_ohlc = os.path.join(self.data_dir, "crypto", f"kraken_{safe_ticker}_{interval_label}_ohlc_{start_str}_to_{end_str}.csv")
            data_path_trades = os.path.join(self.data_dir, "crypto", f"kraken_{safe_ticker}_trades_{start_str}_to_{end_str}.csv")

            self.historical_data[frequency] = {
                "ohlc": pd.read_csv(data_path_ohlc, parse_dates=["timestamp"], index_col="timestamp"),
                "trades": pd.read_csv(data_path_trades, parse_dates=["timestamp"], index_col="timestamp"),
            }

    def validate_data(self):
        data_failed = False 
        base_interval = self.required_intervals[0]
        
        start_time = self.historical_data[base_interval]["ohlc"].index[0]
        end_time = self.historical_data[base_interval]["ohlc"].index[-1]
        
        for interval in self.required_intervals[1:]:
            curr_start = self.historical_data[interval]["ohlc"].index[0]
            if abs((curr_start - start_time).total_seconds()) > (interval * 60):
                print(f"[ERROR] Start time doesn't line up between interval {base_interval} and {interval}: {start_time} vs {curr_start}")
                data_failed = True

            curr_end = self.historical_data[interval]["ohlc"].index[-1]
            if abs((curr_end - end_time).total_seconds()) > (interval * 60):
                print(f"[ERROR] End time doesn't line up between interval {base_interval} and {interval}: {end_time} vs {curr_end}")
                data_failed = True
                    
        if data_failed:
            raise ValueError("Historical context alignment checks failed. Verify target data drops.")

    def display_results(self, ticker, strategy_name, viz_data, asset_type="crypto"):
        os.makedirs(self.results_dir, exist_ok=True)

        for i, res in enumerate(self.backtest_results_overall):
            res.to_csv(os.path.join(self.results_dir, f"backtest_{i}.csv"))

        self.backtest_summary.to_csv(os.path.join(self.results_dir, "summary.csv"))
        print(f"Results saved to {self.results_dir}")

        Visualizer.generate_plots(
            ticker=ticker, 
            strategy_name=strategy_name, 
            data=viz_data, 
            save=True, 
            asset_type=asset_type
        )


if __name__ == "__main__":
    intervals = [1, 5, 240]  
    backtester = Backtester(required_intervals=intervals)
    for interval in intervals:
        backtester.load_historical_data(
            data_type="crypto",
            ticker="XBT/USD",
            start_date=pd.Timestamp("2023-01-01"),
            end_date=pd.Timestamp("2026-06-01"),
            frequency=interval  
        )
    try:
        backtester.validate_data()
        for module, signal_on, param_dict in [ (Breakout5mScalper, "candle", {}) ]:
            curr_instance = module()
            curr_instance.signal_on = signal_on
            
            res, final_value, total_pnl, viz_data = backtester.test_module(curr_instance, risk_percent=0.02, pl_ratio=3.0)
            
            backtester.display_results(
                ticker="XBTUSD", 
                strategy_name="Breakout5mScalper", 
                viz_data=viz_data, 
                asset_type="crypto"
            )
    except Exception as e:
        print(f"[ERROR] data did not line up or backtest failed. Error: {e}")