# Used to mainly make trendlines 
import pandas as pd
import numpy as np
from scipy.signal import arglextrema 
from scipy.stats import linregress 



class LineFormer:
    @staticmethod
    def get_trendline(df):
        df['x_idx'] = np.arange(len(df))
        mid_slope, mid_intercept, _, _, _ = linregress(df['x_idx'], df['close'])
        df['trendline'] = mid_slope * df['x_idx'] + mid_intercept
        return df
    
    
    @staticmethod
    def get_resistance_line(df, order=1):
        df['x_idx'] = np.arange(len(df))
        idx = arglextrema(df['high'].values, np.greater_equal, order=order)[0]
        x_idxs = df['x_idx'].iloc[idx].values
        y_values = df['high'].iloc[idx].values
        slope, intercept, _, _, _ = linregress(x_idxs, y_values) 
        df['resistance_line'] = slope * df['x_idx'] + intercept
        return df
    
    
    @staticmethod
    def get_support_line(df, order=1):
        df['x_idx'] = np.arange(len(df))
        idx = arglextrema(df['low'].values, np.less_equal, order=order)[0]
        x_idxs = df['x_idx'].iloc[idx].values
        y_values = df['low'].iloc[idx].values
        slope, intercept, _, _, _ = linregress(x_idxs, y_values)
        df['support_line'] = slope * df['x_idx'] + intercept
        return df