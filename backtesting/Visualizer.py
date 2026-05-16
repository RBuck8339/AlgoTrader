import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import pandas as pd
import numpy as np
import os


class Visualizer:

    OUTPUT_DIR = "backtesting/plots"

    @staticmethod
    def plot_portfolio_value(ax, data, ticker, strategy_name):
        equity = data["portfolio_value"]
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max * 100

        ax.plot(equity.index, equity, color="#1D9E75", linewidth=1.5, label="Portfolio value")
        ax.fill_between(equity.index, equity, equity.min(), alpha=0.08, color="#1D9E75")

        ax2 = ax.twinx()
        ax2.fill_between(drawdown.index, drawdown, 0, alpha=0.2, color="#E24B4A", label="Drawdown %")
        ax2.set_ylabel("Drawdown %", fontsize=9, color="#E24B4A")
        ax2.tick_params(axis="y", labelcolor="#E24B4A")
        ax2.set_ylim(drawdown.min() * 2, 5)

        ax.set_title(f"{ticker} | {strategy_name} — Equity curve", fontsize=11)
        ax.set_ylabel("Portfolio value ($)")
        ax.legend(loc="upper left", fontsize=9)

    @staticmethod
    def plot_trades(ax, data, ticker, strategy_name):
        pnl = data["trade_pnl"].dropna()
        if pnl.empty:
            ax.text(0.5, 0.5, "No trades", transform=ax.transAxes, ha="center")
            return

        wins = pnl[pnl >= 0]
        losses = pnl[pnl < 0]

        bins = np.linspace(pnl.min(), pnl.max(), 40)
        ax.hist(wins, bins=bins, color="#1D9E75", alpha=0.7, label=f"Wins ({len(wins)})")
        ax.hist(losses, bins=bins, color="#E24B4A", alpha=0.7, label=f"Losses ({len(losses)})")
        ax.axvline(0, color="gray", linewidth=0.8, linestyle="--")
        ax.axvline(pnl.mean(), color="orange", linewidth=1.2, linestyle="--", label=f"Mean P&L: ${pnl.mean():.2f}")

        ax.set_title(f"{ticker} | {strategy_name} — Trade P&L distribution", fontsize=11)
        ax.set_xlabel("P&L ($)")
        ax.set_ylabel("Count")
        ax.legend(fontsize=9)

    @staticmethod
    def plot_returns_distribution(ax, data, ticker, strategy_name):
        returns = data["daily_returns"].dropna()

        sns.histplot(returns, kde=True, ax=ax, color="#534AB7", alpha=0.6, stat="density")

        mu, std = returns.mean(), returns.std()
        x = np.linspace(returns.min(), returns.max(), 200)
        normal = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mu) / std) ** 2)
        ax.plot(x, normal, color="orange", linewidth=1.2, linestyle="--", label="Normal dist")

        ax.axvline(0, color="gray", linewidth=0.8, linestyle="--")
        ax.set_title(f"{ticker} | {strategy_name} — Returns distribution", fontsize=11)
        ax.set_xlabel("Daily return")
        ax.set_ylabel("Density")
        ax.legend(fontsize=9)

    @staticmethod
    def plot_rolling_sharpe(ax, data, ticker, strategy_name, window=30, trading_days=365):
        returns = data["daily_returns"].dropna()
        rolling_sharpe = (
            returns.rolling(window).mean() /
            returns.rolling(window).std()
        ) * np.sqrt(trading_days)

        ax.plot(rolling_sharpe.index, rolling_sharpe, color="#378ADD", linewidth=1.2)
        ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
        ax.axhline(1.0, color="#1D9E75", linewidth=0.8, linestyle="--", label="Sharpe = 1.0")
        ax.fill_between(rolling_sharpe.index, rolling_sharpe, 0,
                        where=(rolling_sharpe >= 0), alpha=0.1, color="#1D9E75")
        ax.fill_between(rolling_sharpe.index, rolling_sharpe, 0,
                        where=(rolling_sharpe < 0), alpha=0.1, color="#E24B4A")

        ax.set_title(f"{ticker} | {strategy_name} — Rolling {window}d Sharpe", fontsize=11)
        ax.set_ylabel("Sharpe ratio")
        ax.legend(fontsize=9)

    @staticmethod
    def plot_win_rate_over_time(ax, data, ticker, strategy_name, window=20):
        pnl = data["trade_pnl"].dropna()
        if pnl.empty:
            ax.text(0.5, 0.5, "No trades", transform=ax.transAxes, ha="center")
            return

        wins = (pnl >= 0).astype(int)
        rolling_wr = wins.rolling(window).mean() * 100

        ax.plot(rolling_wr.index, rolling_wr, color="#EF9F27", linewidth=1.2)
        ax.axhline(50, color="gray", linewidth=0.8, linestyle="--", label="50% baseline")
        ax.fill_between(rolling_wr.index, rolling_wr, 50,
                        where=(rolling_wr >= 50), alpha=0.15, color="#1D9E75")
        ax.fill_between(rolling_wr.index, rolling_wr, 50,
                        where=(rolling_wr < 50), alpha=0.15, color="#E24B4A")

        ax.set_title(f"{ticker} | {strategy_name} — Rolling {window}-trade win rate", fontsize=11)
        ax.set_ylabel("Win rate (%)")
        ax.set_ylim(0, 100)
        ax.legend(fontsize=9)

    @staticmethod
    def plot_drawdown(ax, data, ticker, strategy_name):
        equity = data["portfolio_value"]
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max * 100

        ax.fill_between(drawdown.index, drawdown, 0, color="#E24B4A", alpha=0.4)
        ax.plot(drawdown.index, drawdown, color="#E24B4A", linewidth=0.8)
        ax.axhline(0, color="gray", linewidth=0.5)

        max_dd_idx = drawdown.idxmin()
        max_dd_val = drawdown.min()
        ax.annotate(
            f"Max DD: {max_dd_val:.1f}%",
            xy=(max_dd_idx, max_dd_val),
            xytext=(max_dd_idx, max_dd_val - 3),
            fontsize=8,
            color="#E24B4A",
            arrowprops=dict(arrowstyle="->", color="#E24B4A", lw=0.8)
        )

        ax.set_title(f"{ticker} | {strategy_name} — Drawdown", fontsize=11)
        ax.set_ylabel("Drawdown (%)")

    @staticmethod
    def plot_monthly_returns_heatmap(ax, data, ticker, strategy_name):
        returns = data["daily_returns"].dropna()
        returns.index = pd.to_datetime(returns.index)

        monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1) * 100
        pivot = monthly.to_frame("return")
        pivot["year"] = pivot.index.year
        pivot["month"] = pivot.index.month

        heatmap_data = pivot.pivot(index="year", columns="month", values="return")
        heatmap_data.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        sns.heatmap(
            heatmap_data,
            ax=ax,
            cmap="RdYlGn",
            center=0,
            annot=True,
            fmt=".1f",
            linewidths=0.5,
            cbar_kws={"label": "Return (%)"},
            annot_kws={"size": 8}
        )
        ax.set_title(f"{ticker} | {strategy_name} — Monthly returns (%)", fontsize=11)
        ax.set_xlabel("")

    @staticmethod
    def plot_trade_duration(ax, data, ticker, strategy_name):
        durations = data["trade_duration"].dropna()
        if durations.empty:
            ax.text(0.5, 0.5, "No trades", transform=ax.transAxes, ha="center")
            return

        ax.hist(durations, bins=30, color="#534AB7", alpha=0.7, edgecolor="white", linewidth=0.3)
        ax.axvline(durations.mean(), color="orange", linewidth=1.2,
                   linestyle="--", label=f"Mean: {durations.mean():.1f} bars")
        ax.axvline(durations.median(), color="#1D9E75", linewidth=1.2,
                   linestyle="--", label=f"Median: {durations.median():.1f} bars")

        ax.set_title(f"{ticker} | {strategy_name} — Trade duration", fontsize=11)
        ax.set_xlabel("Bars held")
        ax.set_ylabel("Count")
        ax.legend(fontsize=9)

    @staticmethod
    def plot_summary_stats(ax, data, ticker, strategy_name, trading_days=365):
        pnl = data["trade_pnl"].dropna()
        equity = data["portfolio_value"]
        returns = data["daily_returns"].dropna()

        total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
        sharpe = (returns.mean() / returns.std()) * np.sqrt(trading_days) if returns.std() > 0 else 0
        max_dd = ((equity - equity.cummax()) / equity.cummax()).min() * 100
        win_rate = (pnl >= 0).mean() * 100 if not pnl.empty else 0
        avg_win = pnl[pnl >= 0].mean() if not pnl[pnl >= 0].empty else 0
        avg_loss = pnl[pnl < 0].mean() if not pnl[pnl < 0].empty else 0
        profit_factor = abs(pnl[pnl >= 0].sum() / pnl[pnl < 0].sum()) if pnl[pnl < 0].sum() != 0 else float("inf")

        stats = [
            ("Total return", f"{total_return:.2f}%"),
            ("Sharpe ratio", f"{sharpe:.2f}"),
            ("Max drawdown", f"{max_dd:.2f}%"),
            ("Win rate", f"{win_rate:.1f}%"),
            ("Avg win", f"${avg_win:.2f}"),
            ("Avg loss", f"${avg_loss:.2f}"),
            ("Profit factor", f"{profit_factor:.2f}"),
            ("Total trades", f"{len(pnl)}"),
        ]

        ax.axis("off")
        ax.set_title(f"{ticker} | {strategy_name} — Summary", fontsize=11)

        for i, (label, value) in enumerate(stats):
            y = 0.9 - i * 0.11
            ax.text(0.1, y, label, transform=ax.transAxes, fontsize=10, color="gray")
            ax.text(0.65, y, value, transform=ax.transAxes, fontsize=10, fontweight="bold",
                    color="#1D9E75" if not value.startswith("-") else "#E24B4A")

    @staticmethod
    def generate_plots(ticker, strategy_name, data, save=True, asset_type="crypto"):
        os.makedirs(Visualizer.OUTPUT_DIR, exist_ok=True)

        trading_days = 365 if asset_type == "crypto" else 252

        groups = [
            ("equity_curve", lambda ax, d, t, s: Visualizer.plot_portfolio_value(ax, d, t, s)),
            ("trade_pnl", lambda ax, d, t, s: Visualizer.plot_trades(ax, d, t, s)),
            ("returns_distribution", lambda ax, d, t, s: Visualizer.plot_returns_distribution(ax, d, t, s)),
            ("rolling_sharpe", lambda ax, d, t, s: Visualizer.plot_rolling_sharpe(ax, d, t, s, trading_days=trading_days)),
            ("win_rate", lambda ax, d, t, s: Visualizer.plot_win_rate_over_time(ax, d, t, s)),
            ("drawdown", lambda ax, d, t, s: Visualizer.plot_drawdown(ax, d, t, s)),
            ("monthly_heatmap", lambda ax, d, t, s: Visualizer.plot_monthly_returns_heatmap(ax, d, t, s)),
            ("trade_duration", lambda ax, d, t, s: Visualizer.plot_trade_duration(ax, d, t, s)),
            ("summary", lambda ax, d, t, s: Visualizer.plot_summary_stats(ax, d, t, s, trading_days=trading_days)),
        ]

        for plot_name, plot_fn in groups:
            fig, ax = plt.subplots(figsize=(12, 5))
            fig.patch.set_facecolor("white")

            try:
                plot_fn(ax, data, ticker, strategy_name)
            except Exception as e:
                print(f"  Warning: could not render {plot_name} — {e}")
                plt.close(fig)
                continue

            plt.tight_layout()

            if save:
                path = os.path.join(
                    Visualizer.OUTPUT_DIR,
                    f"{ticker}_{strategy_name}_{plot_name}.png"
                )
                fig.savefig(path, dpi=150, bbox_inches="tight")
                print(f"Saved {path}")

            plt.close(fig)

    @staticmethod
    def compare_methods(ticker, methods, asset_type="crypto"):
        os.makedirs(Visualizer.OUTPUT_DIR, exist_ok=True)
        trading_days = 365 if asset_type == "crypto" else 252

        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle(f"{ticker} — Strategy comparison", fontsize=13)

        equity_ax, sharpe_ax, wr_ax, summary_ax = axes.flat

        colors = ["#1D9E75", "#534AB7", "#EF9F27", "#E24B4A", "#378ADD"]

        for i, method in enumerate(methods):
            name = method["name"]
            data = method["data"]
            color = colors[i % len(colors)]
            equity = data["portfolio_value"]
            returns = data["daily_returns"].dropna()

            equity_ax.plot(equity.index, equity, color=color, linewidth=1.2, label=name)

            rolling_sharpe = (
                returns.rolling(30).mean() / returns.rolling(30).std()
            ) * np.sqrt(trading_days)
            sharpe_ax.plot(rolling_sharpe.index, rolling_sharpe, color=color, linewidth=1.0, label=name)

            pnl = data["trade_pnl"].dropna()
            if not pnl.empty:
                wins = (pnl >= 0).astype(int)
                rolling_wr = wins.rolling(20).mean() * 100
                wr_ax.plot(rolling_wr.index, rolling_wr, color=color, linewidth=1.0, label=name)

        equity_ax.set_title("Equity curves")
        equity_ax.set_ylabel("Portfolio value ($)")
        equity_ax.legend(fontsize=8)

        sharpe_ax.axhline(0, color="gray", linewidth=0.6, linestyle="--")
        sharpe_ax.axhline(1.0, color="gray", linewidth=0.6, linestyle=":")
        sharpe_ax.set_title("Rolling Sharpe (30-bar)")
        sharpe_ax.legend(fontsize=8)

        wr_ax.axhline(50, color="gray", linewidth=0.6, linestyle="--")
        wr_ax.set_title("Rolling win rate (20-trade)")
        wr_ax.set_ylim(0, 100)
        wr_ax.legend(fontsize=8)

        summary_ax.axis("off")
        summary_ax.set_title("Summary")
        headers = ["Strategy", "Total return", "Sharpe", "Win rate", "Trades"]
        col_x = [0.0, 0.25, 0.45, 0.62, 0.82]
        y = 0.92

        for j, h in enumerate(headers):
            summary_ax.text(col_x[j], y, h, transform=summary_ax.transAxes,
                            fontsize=9, fontweight="bold", color="gray")
        y -= 0.1

        for i, method in enumerate(methods):
            name = method["name"]
            data = method["data"]
            color = colors[i % len(colors)]
            equity = data["portfolio_value"]
            returns = data["daily_returns"].dropna()
            pnl = data["trade_pnl"].dropna()

            total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
            sharpe = (returns.mean() / returns.std()) * np.sqrt(trading_days) if returns.std() > 0 else 0
            win_rate = (pnl >= 0).mean() * 100 if not pnl.empty else 0
            n_trades = len(pnl)

            row = [name, f"{total_return:.1f}%", f"{sharpe:.2f}", f"{win_rate:.1f}%", str(n_trades)]
            for j, val in enumerate(row):
                summary_ax.text(col_x[j], y, val, transform=summary_ax.transAxes,
                                fontsize=9, color=color)
            y -= 0.1

        plt.tight_layout()
        path = os.path.join(Visualizer.OUTPUT_DIR, f"{ticker}_strategy_comparison.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"Saved {path}")
        plt.close(fig)