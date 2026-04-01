# Calculate different amounts/columns in the dataframe (all will assume DF input)

import pandas as pd
import numpy as np


class MathUtils:
    # Trend / Moving Averages

    @staticmethod
    def sma(df: pd.DataFrame, period: int, col="close") -> pd.Series:
        """Simple moving average"""
        return df[col].rolling(period).mean()

    @staticmethod
    def ema(df: pd.DataFrame, period: int, col="close") -> pd.Series:
        """Exponential moving average"""
        return df[col].ewm(span=period, adjust=False).mean()

    @staticmethod
    def macd(df: pd.DataFrame, fast=12, slow=26, signal=9, col="close"):
        """
        Returns (macd_line, signal_line, histogram) as a tuple of Series
        """
        ema_fast = MathUtils.ema(df, fast, col)
        ema_slow = MathUtils.ema(df, slow, col)
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    # Momentum / Oscillators

    @staticmethod
    def rsi(df: pd.DataFrame, period=14, col="close") -> pd.Series:
        """Relative Strength Index"""
        delta = df[col].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = -delta.clip(upper=0).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def stochastic(df: pd.DataFrame, k_period=14, d_period=3):
        """
        Stochastic oscillator
        Returns (%K, %D) as a tuple of Series
        """
        low_min = df["low"].rolling(k_period).min()
        high_max = df["high"].rolling(k_period).max()
        k = 100 * (df["close"] - low_min) / (high_max - low_min)
        d = k.rolling(d_period).mean()
        return k, d

    # Volatility

    @staticmethod
    def atr(df: pd.DataFrame, period=14) -> pd.Series:
        """Average True Range"""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"]  - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(period).mean()

    @staticmethod
    def bollinger_bands(df: pd.DataFrame, period=20, std_dev=2, col="close"):
        """
        Returns (upper, middle, lower) as a tuple of Series
        """
        middle = MathUtils.sma(df, period, col)
        std = df[col].rolling(period).std()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        return upper, middle, lower

    # Volume

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """
        Volume Weighted Average Price
        Resets daily — requires intraday data
        """
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        return (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()

    @staticmethod
    def obv(df: pd.DataFrame) -> pd.Series:
        """On Balance Volume"""
        direction = df["close"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        return (direction * df["volume"]).cumsum()

    # Support / Resistance

    @staticmethod
    def rolling_high(df: pd.DataFrame, period=20) -> pd.Series:
        """Rolling resistance — highest high over period"""
        return df["high"].rolling(period).max()

    @staticmethod
    def rolling_low(df: pd.DataFrame, period=20) -> pd.Series:
        """Rolling support — lowest low over period"""
        return df["low"].rolling(period).min()

    # Candlestick helpers

    @staticmethod
    def body_size(df: pd.DataFrame) -> pd.Series:
        """Absolute candle body size"""
        return (df["close"] - df["open"]).abs()

    @staticmethod
    def is_bullish(df: pd.DataFrame) -> pd.Series:
        """True where close > open"""
        return df["close"] > df["open"]

    @staticmethod
    def is_bearish(df: pd.DataFrame) -> pd.Series:
        """True where close < open"""
        return df["close"] < df["open"]

    @staticmethod
    def upper_wick(df: pd.DataFrame) -> pd.Series:
        """Upper wick size"""
        return df["high"] - df[["open", "close"]].max(axis=1)

    @staticmethod
    def lower_wick(df: pd.DataFrame) -> pd.Series:
        """Lower wick size"""
        return df[["open", "close"]].min(axis=1) - df["low"]

    # General stats

    @staticmethod
    def pct_change(df: pd.DataFrame, col="close") -> pd.Series:
        return df[col].pct_change()

    @staticmethod
    def zscore(series: pd.Series, period=20) -> pd.Series:
        """Rolling z-score — useful for mean reversion signals"""
        mean = series.rolling(period).mean()
        std = series.rolling(period).std()
        return (series - mean) / std

    @staticmethod
    def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
        """
        Returns 1 where fast crosses above slow, -1 where fast crosses below, else 0
        Useful for MA crossover signals
        """
        cross = pd.Series(0, index=fast.index)
        cross[(fast > slow) & (fast.shift(1) <= slow.shift(1))] =  1  # bullish cross
        cross[(fast < slow) & (fast.shift(1) >= slow.shift(1))] = -1  # bearish cross
        return cross
    
    # Fair Value Gap 

    @staticmethod
    def fair_value_gap(df: pd.DataFrame) -> pd.Series:
        """
        Identifies Fair Value Gaps (FVG) on a 3-candle structure.

        Bullish FVG  (+1): low of current candle > high of candle 2 bars ago
                        — gap left on the way up, price likely to revisit
        Bearish FVG  (-1): high of current candle < low of candle 2 bars ago
                        — gap left on the way down, price likely to revisit
        No FVG        (0): no gap present

        Returns a Series of -1, 0, or 1
        """
        bullish = df["low"] > df["high"].shift(2)   # candle 3 low > candle 1 high
        bearish = df["high"] < df["low"].shift(2)   # candle 3 high < candle 1 low

        result = pd.Series(0, index=df.index)
        result[bullish] =  1
        result[bearish] = -1
        return result


    @staticmethod
    def fvg_size(df: pd.DataFrame) -> pd.Series:
        """
        Size of the fair value gap in price units.
        Useful for filtering out tiny insignificant gaps.

        Bullish: low of candle 3 - high of candle 1
        Bearish: low of candle 1 - high of candle 3
        Returns 0 where no FVG exists.
        """
        bullish_size = df["low"] - df["high"].shift(2)
        bearish_size = df["low"].shift(2) - df["high"]

        fvg = MathUtils.fair_value_gap(df)

        result = pd.Series(0.0, index=df.index)
        result[fvg ==  1] = bullish_size[fvg ==  1]
        result[fvg == -1] = bearish_size[fvg == -1]
        return result


    @staticmethod
    def fvg_midpoint(df: pd.DataFrame) -> pd.Series:
        """
        Midpoint of the fair value gap — often used as a magnet price level.
        Returns NaN where no FVG exists.
        """
        fvg = MathUtils.fair_value_gap(df)

        bullish_mid = (df["low"] + df["high"].shift(2)) / 2
        bearish_mid = (df["high"] + df["low"].shift(2)) / 2

        result = pd.Series(float("nan"), index=df.index)
        result[fvg ==  1] = bullish_mid[fvg ==  1]
        result[fvg == -1] = bearish_mid[fvg == -1]
        return result