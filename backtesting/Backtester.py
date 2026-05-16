import os
import sys
from datetime import datetime 

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd

from backtesting.CryptoHistoryGrabber import KrakenHistoricalScraper
from traders.TA_Traders.MACrossover import SingleMACrossover
from backtesting.Visualizer import Visualizer

INTERVAL_MAP = {
    1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h",
    240: "4h", 1440: "1d", 10080: "1w", 21600: "15d"
}


class Backtester:
    def __init__(self):
        self.data_dir = "backtesting/data"
        self.results_dir = "backtesting/results"
        self.backtest_results_overall = []
        self.backtest_summary = pd.DataFrame(columns=["module_name", "portfolio_value", "num_trades", "realized_pnl", "total_pnl"])
        self.historical_data = None


    def test_module(self, module, interval=60, risk_percent=0.02, pl_ratio=2.0):
        if self.historical_data is None:
            raise RuntimeError("No historical data loaded. Call load_historical_data() first.")

        ohlc_data = self.historical_data["ohlc"]
        trade_data = self.historical_data["trades"]

        curr_data_ohlc = pd.DataFrame(columns=ohlc_data.columns)
        curr_data_trades = pd.DataFrame(columns=trade_data.columns)
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

        for idx_ohlc, row_ohlc in ohlc_data.iterrows():
            curr_data_ohlc.loc[idx_ohlc] = row_ohlc
            curr_time = idx_ohlc
            end_time = curr_time + pd.Timedelta(minutes=interval)
            bar_idx += 1

            current_block_trades = trade_data.loc[
                (trade_data.index >= curr_time) & (trade_data.index < end_time)
            ].sort_index()

            for idx_trade, row_trade in current_block_trades.iterrows():
                curr_data_trades.loc[idx_trade] = row_trade
                curr_price = float(curr_data_trades["price"].iloc[-1])

                if module.signal_on == "tick":
                    module.data = curr_data_ohlc.copy()
                    signal = module.check_signals()
                    holding, portfolio_value_realized, num_shares_held, stop_loss_price, buy_amt, trade_made, pnl, duration, entry_bar = self._execute_signal(
                        signal, curr_price, holding, portfolio_value_realized,
                        num_shares_held, stop_loss_price, buy_amt, risk_percent,
                        bar_idx=bar_idx, entry_bar=entry_bar
                    )
                    if trade_made and pnl is not None:
                        trade_pnl_list.append(pnl)
                        trade_duration_list.append(duration)

            close_price = float(row_ohlc["close"])
            curr_price = close_price if curr_price == 0.0 else curr_price

            if module.signal_on == "candle":
                module.data = curr_data_ohlc.copy()
                signal = module.check_signals()
                holding, portfolio_value_realized, num_shares_held, stop_loss_price, buy_amt, trade_made, pnl, duration, entry_bar = self._execute_signal(
                    signal, close_price, holding, portfolio_value_realized,
                    num_shares_held, stop_loss_price, buy_amt, risk_percent,
                    bar_idx=bar_idx, entry_bar=entry_bar
                )
                if trade_made and pnl is not None:
                    trade_pnl_list.append(pnl)
                    trade_duration_list.append(duration)
            else:
                trade_made = False

            portfolio_value_unrealized = portfolio_value_realized + (close_price * num_shares_held)

            backtest_results.loc[idx_ohlc] = {
                "date": idx_ohlc.date(),
                "time": idx_ohlc.time(),
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
            (SingleMACrossover, "candle", {}),
        ]

        for module, signal_on, param_dict in modules:
            # Run a Bayesian Optimization/Grid Search style loop here to get parameters
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

        # Eventually, goal is to compare multiple methods in the same plots


    def load_historical_data(self, data_type, ticker, start_date, end_date, frequency):
        interval_label = INTERVAL_MAP.get(frequency, f"{frequency}m")
        
        safe_ticker = ticker.replace("/", "")
        since_ts = int(start_date.timestamp())
        start_dt_normalized = datetime.fromtimestamp(since_ts)
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

            self.historical_data = {
                "ohlc": pd.read_csv(data_path_ohlc, parse_dates=["timestamp"], index_col="timestamp"),
                "trades": pd.read_csv(data_path_trades, parse_dates=["timestamp"], index_col="timestamp"),
            }

        else:
            raise ValueError("Unsupported data type. Choose 'stock' or 'crypto'")

        print(f"Loaded {len(self.historical_data['ohlc'])} OHLC bars for {ticker}")
        if self.historical_data["trades"] is not None:
            print(f"Loaded {len(self.historical_data['trades'])} trades for {ticker}")


    def display_results(self, ticker, strategy_name, viz_data, asset_type="crypto"):
        os.makedirs(self.results_dir, exist_ok=True)

        for i, res in enumerate(self.backtest_results_overall):
            res.to_csv(os.path.join(self.results_dir, f"backtest_{i}.csv"))

        self.backtest_summary.to_csv(os.path.join(self.results_dir, "summary.csv"))
        print(f"Results saved to {self.results_dir}")

        Visualizer.generate_plots(ticker, strategy_name, viz_data, asset_type=asset_type)


    def _execute_signal(self, signal, curr_price, holding, portfolio_value_realized,
                        num_shares_held, stop_loss_price, buy_amt, risk_percent, bar_idx=0, entry_bar=0):
        # Used for a lot of my visualization stats
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


if __name__ == "__main__":
    backtester = Backtester()
    backtester.load_historical_data(
        data_type="crypto",
        ticker="XBT/USD",
        start_date=pd.Timestamp("2023-01-01"),
        end_date=pd.Timestamp("2023-01-07"),
        frequency=60  # Needs tuning based on the model, 60 works for now
    )
    backtester.run_backtests()