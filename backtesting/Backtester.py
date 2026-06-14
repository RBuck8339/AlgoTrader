import os
import sys
from datetime import datetime

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


    def test_module(self, module, risk_percent=0.02, pl_ratio=2.0):
        if not self.historical_data:
            raise RuntimeError("No historical data loaded. Call load_historical_data() first.")

        backtest_results = pd.DataFrame(columns=["date", "time", "portfolio_value", "live_order", "unrealized_pnl", "realized_pnl", "total_pnl", "trade_made"])

        portfolio_value_realized = 100000.0
        holding = False
        stop_loss_price = -1.0
        num_shares_held = 0.0
        buy_amt = 0.0
        curr_price = 0.0
        entry_bar = 0
        bar_idx = 0
        trade_pnl_list = []
        trade_duration_list = []

        df_1m_base = self.historical_data[1]["ohlc"]
        trade_data = self.historical_data[1]["trades"]

        print(f"\n[INFO] Backtest starting")

        for curr_time, row_1m in df_1m_base.iterrows():
            bar_idx += 1
            
            # Create the dynamic timeframe cache dictionary, just like our live engine
            all_dfs = {}
            
            # Slice historical segments up to the current simulated minute to prevent lookahead leaks
            for interval in self.required_intervals:
                full_df = self.historical_data[interval]["ohlc"]
                # Filter down to bars where the bar completion time is <= our current time position
                historical_slice = full_df.loc[full_df.index <= curr_time].copy()
                
                # Convert price types to float to match live data casting steps
                for col in ["open", "high", "low", "close", "volume"]:
                    historical_slice[col] = historical_slice[col].astype(float)
                
                all_dfs[interval] = historical_slice

            # Determine whether a 5-minute bar has closed to match live time synchronization checks
            current_timestamp_seconds = int(curr_time.timestamp())
            is_5m_rollover = (current_timestamp_seconds % 300 == 0)
            interval_posted = 5 if is_5m_rollover else 1

            # Isolate matching high-frequency trade updates within this 1-minute block
            end_time = curr_time + pd.Timedelta(minutes=1)
            current_block_trades = trade_data.loc[
                (trade_data.index >= curr_time) & (trade_data.index < end_time)
            ].sort_index()

            trade_made = False
            pnl = None
            duration = None

            # Process transaction executions at the tick level if requested
            for idx_trade, row_trade in current_block_trades.iterrows():
                curr_price = float(row_trade["price"])

                if module.signal_on == "tick":
                    signal = module.check_signals(dfs=all_dfs, interval_posted=interval_posted)
                    holding, portfolio_value_realized, num_shares_held, stop_loss_price, buy_amt, trade_made, pnl, duration, entry_bar = self._execute_signal(
                        signal, curr_price, holding, portfolio_value_realized,
                        num_shares_held, stop_loss_price, buy_amt, risk_percent,
                        bar_idx=bar_idx, entry_bar=entry_bar
                    )
                    if trade_made and pnl is not None:
                        trade_pnl_list.append(pnl)
                        trade_duration_list.append(duration)

            close_price = float(row_1m["close"])
            curr_price = close_price if curr_price == 0.0 else curr_price

            # Process standard block candle closures (ensuring 5m strat only checks on true rollovers)
            if module.signal_on == "candle":
                if interval_posted == 5:
                    signal = module.check_signals(dfs=all_dfs, interval_posted=interval_posted)
                    holding, portfolio_value_realized, num_shares_held, stop_loss_price, buy_amt, trade_made, pnl, duration, entry_bar = self._execute_signal(
                        signal, close_price, holding, portfolio_value_realized,
                        num_shares_held, stop_loss_price, buy_amt, risk_percent,
                        bar_idx=bar_idx, entry_bar=entry_bar
                    )
                    if trade_made and pnl is not None:
                        trade_pnl_list.append(pnl)
                        trade_duration_list.append(duration)
            else:
                if module.signal_on != "tick":
                    trade_made = False

            portfolio_value_unrealized = portfolio_value_realized + (close_price * num_shares_held)

            backtest_results.loc[curr_time] = {
                "date": curr_time.date(),
                "time": curr_time.time(),
                "portfolio_value": portfolio_value_unrealized,
                "live_order": holding,
                "unrealized_pnl": portfolio_value_unrealized - portfolio_value_realized,
                "realized_pnl": portfolio_value_realized - 100000.0,
                "total_pnl": portfolio_value_unrealized - 100000.0,
                "trade_made": trade_made,
            }

        final_value = portfolio_value_realized + (curr_price * num_shares_held)
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
                "num_trades": len(res[res["trade_made"] == True]),
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
            data_path_ohlc = os.path.join(
                self.data_dir,
                f"{safe_ticker}_{interval_label}_ohlc_{start_str}_to_{end_str}.csv"
            )
            data_path_trades = os.path.join(
                self.data_dir,
                f"{safe_ticker}_trades_{start_str}_to_{end_str}.csv"
            )
            if not os.path.exists(data_path_ohlc):
                raise FileNotFoundError(f"Stock OHLC data not found: {data_path_ohlc}. Run StockHistoryGrabber.cache() first.")

            self.historical_data = {
                "ohlc": pd.read_csv(data_path_ohlc, parse_dates=["timestamp"], index_col="timestamp"),
                "trades": None,
            }

        elif data_type == "crypto":
            data_path_ohlc = os.path.join(
                self.data_dir, "crypto",
                f"kraken_{safe_ticker}_{interval_label}_ohlc_{start_str}_to_{end_str}.csv"
            )
            data_path_trades = os.path.join(
                self.data_dir, "crypto",
                f"kraken_{safe_ticker}_trades_{start_str}_to_{end_str}.csv"
            )

            if not os.path.exists(data_path_ohlc):
                print(f"OHLC file not found, scraping...")
                KrakenHistoricalScraper(
                    symbol=ticker,
                    data_type="ohlc",
                    interval=frequency,
                    start_date=start_date,
                    end_date=end_date,
                ).fetch()

            if not os.path.exists(data_path_trades):
                print(f"Trades file not found, scraping...")
                KrakenHistoricalScraper(
                    symbol=ticker,
                    data_type="trades",
                    start_date=start_date,
                    end_date=end_date,
                ).fetch()

            self.historical_data[frequency] = {
                "ohlc": pd.read_csv(data_path_ohlc, parse_dates=["timestamp"], index_col="timestamp"),
                "trades": pd.read_csv(data_path_trades, parse_dates=["timestamp"], index_col="timestamp"),
            }

        else:
            raise ValueError("Unsupported data type. Choose 'stock' or 'crypto'")

        print(f"Loaded {len(self.historical_data[frequency]['ohlc'])} OHLC bars for {ticker}")
        if self.historical_data[frequency]["trades"] is not None:
            print(f"Loaded {len(self.historical_data[frequency]['trades'])} trades for {ticker}")


    def display_results(self, ticker, strategy_name, viz_data, asset_type="crypto"):
        os.makedirs(self.results_dir, exist_ok=True)

        for i, res in enumerate(self.backtest_results_overall):
            res.to_csv(os.path.join(self.results_dir, f"backtest_{i}.csv"))

        self.backtest_summary.to_csv(os.path.join(self.results_dir, "summary.csv"))
        print(f"Results saved to {self.results_dir}")

        Visualizer.generate_plots(ticker, strategy_name, viz_data, asset_type=asset_type)


    def _execute_signal(self, signal, curr_price, holding, portfolio_value_realized,
                        num_shares_held, stop_loss_price, buy_amt, risk_percent, bar_idx=0, entry_bar=0):
        trade_made = False
        pnl = None
        duration = None

        if signal == 1 and not holding:
            buy_amt = portfolio_value_realized * risk_percent
            num_shares_held = buy_amt / curr_price
            stop_loss_price = curr_price * (1 - risk_percent)
            portfolio_value_realized -= buy_amt
            holding = True
            entry_bar = bar_idx
            trade_made = True
            print(f"  BUY  @ {curr_price:.2f} | shares={num_shares_held:.4f} | stop={stop_loss_price:.2f}")

        elif holding and (signal == -1 or curr_price <= stop_loss_price):
            sell_amt = num_shares_held * curr_price
            pnl = sell_amt - buy_amt
            duration = bar_idx - entry_bar
            portfolio_value_realized += sell_amt
            holding = False
            num_shares_held = 0.0
            stop_loss_price = -1.0
            buy_amt = 0.0
            trade_made = True
            print(f"  SELL @ {curr_price:.2f} | pnl={pnl:.2f}")

        return holding, portfolio_value_realized, num_shares_held, stop_loss_price, buy_amt, trade_made, pnl, duration, entry_bar


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
        backtester.run_backtests()
    except Exception as e:
        print(f"[ERROR] data did not line up or backtest failed. Error: {e}")