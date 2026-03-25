import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import os
import pandas as pd
import numpy as np
import pickle
from pprint import pprint

from freqtrade.configuration import TimeRange
from freqtrade.constants import Config
from freqtrade.data.btanalysis import (analyze_trade_parallelism, extract_trades_of_period,
                                       load_trades)
from freqtrade.data.converter import trim_dataframe
from freqtrade.data.dataprovider import DataProvider
from freqtrade.data.history import get_timerange, load_data
from freqtrade.data.metrics import (calculate_max_drawdown, calculate_underwater,
                                    combine_dataframes_with_mean, create_cum_profit)
from freqtrade.enums import CandleType
from freqtrade.exceptions import OperationalException
from freqtrade.exchange import timeframe_to_prev_date, timeframe_to_seconds
from freqtrade.misc import pair_to_filename
from freqtrade.plugins.pairlist.pairlist_helpers import expand_pairlist
from freqtrade.resolvers import ExchangeResolver, StrategyResolver
from freqtrade.strategy import IStrategy


logger = logging.getLogger(__name__)


try:
    import plotly.graph_objects as go
    from plotly.offline import plot
    from plotly.subplots import make_subplots
except ImportError:
    logger.exception("Module plotly not found \n Please install using `pip3 install plotly`")
    exit(1)


def init_plotscript(config, markets: List, startup_candles: int = 0):
    """
    Initialize objects needed for plotting
    :return: Dict with candle (OHLCV) data, trades and pairs
    """

    if "pairs" in config:
        pairs = expand_pairlist(config['pairs'], markets)
    else:
        pairs = expand_pairlist(config['exchange']['pair_whitelist'], markets)

    # Set timerange to use
    timerange = TimeRange.parse_timerange(config.get('timerange'))

    data = load_data(
        datadir=config.get('datadir'),
        pairs=pairs,
        timeframe=config['timeframe'],
        timerange=timerange,
        startup_candles=startup_candles,
        data_format=config.get('dataformat_ohlcv', 'json'),
        candle_type=config.get('candle_type_def', CandleType.SPOT),
        fill_up_missing=False if config['exchange']['name'] in config.get('exchanges_not_fill_missing',[]) else True,
    )

    if startup_candles and data:
        min_date, max_date = get_timerange(data)
        logger.info(f"Loading data from {min_date} to {max_date}")
        timerange.adjust_start_if_necessary(timeframe_to_seconds(config['timeframe']),
                                            startup_candles, min_date)

    no_trades = False
    filename = config.get("exportfilename")
    if config.get("no_trades", False):
        no_trades = True
    elif config['trade_source'] == 'file':
        if not filename.is_dir() and not filename.is_file():
            logger.warning("Backtest file is missing skipping trades.")
            no_trades = True
    try:
        trades = load_trades(
            config['trade_source'],
            db_url=config.get('db_url'),
            exportfilename=filename,
            no_trades=no_trades,
            strategy=config.get('strategy'),
        )
    except ValueError as e:
        raise OperationalException(e) from e
    if not trades.empty:
        print('trades in init_plotscript():')
        print(trades)
        # trades = trim_dataframe(trades, timerange, df_date_col='open_date')

    return {"ohlcv": data,
            "trades": trades,
            "pairs": pairs,
            "timerange": timerange,
            }


def add_indicators(fig, row, indicators: Dict[str, Dict], data: pd.DataFrame) -> make_subplots:
    """
    Generate all the indicators selected by the user for a specific row, based on the configuration
    :param fig: Plot figure to append to
    :param row: row number for this plot
    :param indicators: Dict of Indicators with configuration options.
                       Dict key must correspond to dataframe column.
    :param data: candlestick DataFrame
    """
    plot_kinds = {
        'scatter': go.Scatter,
        'bar': go.Bar,
    }

    # if 'big_trades' in data:
    #     sizes = [10, 40]
    #     colors = {'cluster_bid': 'rgba(233,30,99,.99)', 'cluster_ask': 'rgba(88,120,20,.99)', 'cluster_sum': 'rgba(255,0,255,.99)'}
    #     first = {'cluster_bid': True, 'cluster_ask': True, 'cluster_sum': True}
    #     dfn = data.to_dict(orient="records")
    #     for i, _row in enumerate(dfn):
    #         cl = 'big_trades'
    #         if pd.isnull(_row[cl]): continue
    #         for price, qty in eval(_row[cl]).items():
    #             min_ = indicators['cluster_range'][cl]['min']
    #             if indicators['cluster_range'][cl]['max'] == indicators['cluster_range'][cl]['min']: min_ = 0
    #             qty_ = qty if type(qty) != str else float(qty.split('|')[0])
    #             fig.add_trace(go.Scatter(
    #                     x = [i],
    #                     y = [price], 
    #                     mode='markers',
    #                     name=cl,
    #                     text=qty if type(qty) == str else round(qty, 2),
    #                     showlegend=True if first[cl] else False,
    #                     visible='legendonly' if 1 or cl == 'cluster_sum' else True,
    #                     legendgroup=cl,
    #                     marker=dict(
    #                         symbol='square',
    #                         color=colors[cl].replace('.99', '.25'),
    #                         size=int((100 * (qty_ - min_) / (indicators['cluster_range'][cl]['max'] - min_)) * (sizes[1] - sizes[0]) / 100 + sizes[0]),
    #                         line=dict(color=colors[cl],width=2)
    #                     ),
    #                 ), row=row, col=1)
    #             first[cl] = False

    if 'time_delta' in data  and row == 1:
        sizes = [10, 40]
        colors = {'cluster_bid': 'rgba(233,30,99,.99)', 'cluster_ask': 'rgba(88,120,20,.99)', 'cluster_sum': 'rgba(255,0,255,.99)'}
        colors_big_trades = {'sell': 'rgba(247,150,70,.99)', 'buy': 'rgba(76,172,198,.99)'}

        show_all = False

        exchanges = indicators['cluster_range'].keys()
        first, first_big_trades = {}, {}
        for ex in exchanges:
            first[ex] = {'cluster_bid': True, 'cluster_ask': True, 'cluster_sum': True}
            first_big_trades[ex] = {'sell': True, 'buy': True}

        dfn = data.to_dict(orient="records")
        for i, _row in enumerate(dfn):

            for ex in exchanges:

                


                if ex not in ('binance', 'binance_futures', 'bybit', 'bybit_futures', 'CME',' CBOT', 'NYMEX', 'COMEX'):
                    continue

                if 0 and f'big_trades_{ex}' in _row and not pd.isnull(_row[f'big_trades_{ex}']):
                    for bt in eval(_row[f'big_trades_{ex}']):
                        cl = "big_tr_" + ("bid" if bt['side'] == 'sell' else "ask")
                        cl = f'{cl}_{ex}'.replace('big_tr', 'bgtr').replace('_futures', '_fut').replace('binance', 'bin').replace('bybit', 'byb')
                        side = 'sell' if bt['side'] == 'sell' else 'buy'
                        min_ = indicators['big_trades_range'][ex][side]['min']
                        if indicators['big_trades_range'][ex][side]['max'] == indicators['big_trades_range'][ex][side]['min']: min_ = 0
                        # print('......')
                        # print(_row['date'])
                        # print(ex)
                        # print(bt)
                        # print(bt['qty'], min_, indicators['big_trades_range'][ex][side]['max'], )
                        fig.add_trace(go.Scatter(
                                x = [i],
                                y = [bt['price']], 
                                mode='markers',
                                name=cl,
                                text="qty=" + (bt['qty'] if type(bt['qty']) == str else str(round(bt['qty'], 2))) + f", bt_average={round(bt['bt_average'], 2)}, ex={ex}",
                                showlegend=True if first_big_trades[ex][side] else False,
                                visible=True if indicators['show_clusters'] and show_all else 'legendonly',
                                legendgroup=cl,
                                marker=dict(
                                    symbol='diamond',
                                    color=colors_big_trades[side].replace('.99', '.25'),
                                    size=int((100 * (bt['qty'] - min_) / (indicators['big_trades_range'][ex][side]['max'] - min_)) * (sizes[1] - sizes[0]) / 100 + sizes[0]),
                                    line=dict(color=colors_big_trades[side],width=2)
                                ),
                            ), row=row, col=1)
                        first_big_trades[ex][side] = False


                continue
            
                #if ex not in ('binance_futures', 'CME',' CBOT', 'NYMEX', 'COMEX'): continue
                
                if ex not in ('binance', 'binance_futures', 'bybit', 'bybit_futures', 'CME',' CBOT', 'NYMEX', 'COMEX'):
                    continue

                for cl in [f'cluster_bid', f'cluster_ask', f'cluster_sum']:
                    cl_ex = f'{cl}_{ex}'
                    if cl_ex not in _row or pd.isnull(_row[cl_ex]): continue
                    for bt in eval(_row[cl_ex]):
                        cl_name = cl_ex.replace('cluster', 'cl').replace('_futures', '_fut').replace('binance', 'bin').replace('bybit', 'byb')
                        min_ = indicators['cluster_range'][ex][cl]['min']
                        if indicators['cluster_range'][ex][cl]['max'] == indicators['cluster_range'][ex][cl]['min']: min_ = 0
                        fig.add_trace(go.Scatter(
                                x = [i],
                                y = [bt['price']], 
                                mode='markers',
                                name=cl_name,
                                text="qty=" + (bt['qty'] if type(bt['qty']) == str else str(round(bt['qty'], 2))) + f", cl_average={round(bt['cl_average'], 2)}, ex={ex}",
                                showlegend=True if first[ex][cl] else False,
                                visible=True if indicators['show_clusters'] and show_all else 'legendonly',
                                legendgroup=cl_name,
                                marker=dict(
                                        symbol='square',
                                        color=colors[cl].replace('.99', '.25'),
                                        size=int((100 * (bt['qty'] - min_) / (indicators['cluster_range'][ex][cl]['max'] - min_)) * (sizes[1] - sizes[0]) / 100 + sizes[0]),
                                        line=dict(color=colors[cl],width=2)
                                ),
                            ), row=row, col=1)
                        first[ex][cl] = False


    for indicator, conf in indicators.items():
        logger.debug(f"indicator {indicator} with config {conf}")
        if indicator == 'levels' and conf:
            levels = pd.DataFrame(conf)
            levels = levels.loc[levels['date'] >= data.iloc[0]['date']]
            # levels = levels[levels['active'] == False]
            levels.loc[levels['active'] == True, 'end_date'] = data.iloc[-1]['date']
            if len(levels) == 0:
                continue
            mask = (levels['type'] == 'volume') | (levels['type'] == 'delta')
            levels.loc[mask, 'desc'] = levels.loc[mask].apply(
                lambda row: f"volume: {round(row['volume'], 3)}, vol avg: {round(row['volume_average'], 2)}" + 
                f"<br>delta: {int(row['delta'])}, delta avg: {int(row['delta_average'])}" +
                f"<br>exchange: {row['exchange']}" +
                '<br>{:%Y-%m-%d %H:%M:%S}'.format(row['date']) + f", dur: {(row['end_date'] - row['date']).total_seconds() // 60} min",
                axis=1)
            mask = (levels['type'] == 'ml_volume') | (levels['type'] == 'ml_delta')
            levels.loc[mask, 'desc'] = levels.loc[mask].apply(
                lambda row: f"levels count: {int(row['group_count'])}" + 
                f"<br>volume: {round(row['volume'], 3)}, delta: {round(row['delta'], 3)}" +
                f"<br>green_levels: {int(row['green_levels'])}, red_levels: {int(row['red_levels'])}" +
                f"<br>levels delta: {int(row['green_levels'] - row['red_levels'])}" +
                #f"<br>type: {row['type']}" +
                '<br>{:%Y-%m-%d %H:%M:%S}'.format(row['date']) + f", dur: {(row['end_date'] - row['date']).total_seconds() // 60} min",
                axis=1)
            levels['end_date_X'] = levels['end_date']
            levels['end_date_X'] = pd.to_datetime(levels['end_date'], utc=True, format='mixed')
            data['end_date_X'] = data['date']
            data['i_open'] = data['i']
            data['i_close'] = data['i']
            #levels['i_open'] = pd.to_datetime(trades['open_timestamp'], unit='ms', utc=True)
            #trades['close_date_X'] = pd.to_datetime(trades['close_timestamp'], unit='ms', utc=True)
            op_ = pd.merge(levels, data[['date', 'i_open']], how='inner', on='date')
            # print(levels)
            # print(levels[['end_date_X']].info())
            # print(data[['end_date_X', 'i_close']])
            # print(data[['end_date_X', 'i_close']].info())
            cl_ = pd.merge(levels, data[['end_date_X', 'i_close']], how='inner', on='end_date_X')

            #assert len(op_) == len(cl_)
            if len(op_) != len(cl_):
                print(f"    (!) len(op_) != len(cl_)")

            x = pd.merge(op_, cl_[['i', 'price', 'type', 'i_close']], how='inner', on=['i', 'price', 'type'])


            show_all = False

            wich_show_deltas = []
            wich_show_volumes = []

            for ii, ex in enumerate(x['exchange'].unique()):
                x_ = x.loc[x['exchange'] == ex]
                ex_name = ex.replace('_futures', '_fut').replace('binance', 'binc')
                name_volume = 'vo{}|{}'.format(len(x_.loc[x_['type'] == 'volume']), ex_name)
                name_delta = 'de{}|{}'.format(len(x_.loc[x_['type'] == 'delta']), ex_name)
                name_ml_volume = 'mlvo{}'.format(len(x_.loc[x_['type'] == 'ml_volume']))
                name_ml_delta = 'mlde{}'.format(len(x_.loc[x_['type'] == 'ml_delta']))
                flag_volume, flag_delta, flag_ml_volume, flag_ml_delta = True, True, True, True
                for i, row_ in enumerate(x_.to_dict(orient="records")):
                    color = 'rgba(153,153,153,0.9)'
                    if row_['type'] == 'delta' and row_['delta_color'] == 'red': color = 'rgba(255,0,0,0.7)'
                    if row_['type'] == 'delta' and row_['delta_color'] == 'green': color = 'rgba(0,128,0,0.7)'
                    if row_['type'] == 'ml_volume': color = 'rgba(0,0,255,1)'
                    if row_['type'] == 'ml_delta': color = 'orange'
                    showlegend = False
                    if flag_volume and row_['type'] == 'volume' or flag_delta and row_['type'] == 'delta' or flag_ml_volume and row_['type'] == 'ml_volume' or flag_ml_delta and row_['type'] == 'ml_delta': showlegend = True
                    if row_['type'] == 'volume': name = name_volume
                    if row_['type'] == 'delta': name = name_delta
                    if row_['type'] == 'ml_volume': name = name_ml_volume
                    if row_['type'] == 'ml_delta': name = name_ml_delta
                    fig.add_trace(go.Scatter(
                        x=[row_["i_open"], row_["i_close"]],
                        y=[row_["price"], row_["price"]],
                        name=name,
                        text=row_["desc"],
                        showlegend=showlegend,
                        #visible=True if row_['type'] == 'delta' else 'legendonly',
                        visible=True if row_['type'] in ['ml_volume', 'ml_delta'] or ((ex in wich_show_volumes or wich_show_volumes == ['all']) and row_['type'] == 'volume') or ((ex in wich_show_deltas or wich_show_deltas == ['all']) and row_['type'] == 'delta') or ex == 'binance_futures' and row_['type'] == 'delta' and show_all or show_all else 'legendonly',
                        legendgroup='l_' + row_['type'] + ex,
                        #legendgroup='l_' + row_['type'],
                        mode='lines',
                        line=dict(color=color, dash='dot' if ex == 'binance_futures' else 'dot', width=2),
                        # mode='lines+markers',
                        # marker=dict(color=color, symbol='square', size=2),
                    ), 1, 1)
                    if row_['type'] == 'volume': flag_volume = False
                    if row_['type'] == 'delta': flag_delta = False
                    if row_['type'] == 'ml_volume': flag_ml_volume = False
                    if row_['type'] == 'ml_delta': flag_ml_delta = False

            continue
        if indicator in data:
            kwargs = {'x': list(range(len(data))),
                      #'x': data['date'],
                      'y': data[indicator].values,
                      'name': indicator.replace('_futures', '_fut').replace('binance', 'binc')
                      }
            if indicator in ('marker', 'marker2', 'marker3', 'marker_green', 'marker_yellow', 'marker_blue', 'marker_red', 'marker_orange', 'marker_gray', 'marker_pink'):
                kwargs['text'] = data.apply(
                    lambda row: '{:%Y-%m-%d %H:%M:%S}<br>'.format(row['date']) \
                        + ("{}<br>".format(row[indicator][1]) if isinstance(row[indicator], tuple) and row[indicator][1] != None else ''),
                    axis=1)
                kwargs['y'] = data.apply(lambda row: row[indicator][0] if isinstance(row[indicator], tuple) else row[indicator], axis=1)
            
            # if indicator in ('peaks','troughs'):
            #     print('here', indicator)
            #     print(row)
            #     kwargs['text'] = "KKKK"

            plot_type = conf.get('type', 'scatter')
            color = conf.get('color')
            if plot_type == 'bar':
                kwargs.update({'marker_color': color or 'DarkSlateGrey',
                               'marker_line_color': color or 'DarkSlateGrey'})
            else:
                if color:
                    kwargs.update({'line': {'color': color}})
                kwargs['mode'] = 'lines'
                if plot_type != 'scatter':
                    logger.warning(f'Indicator {indicator} has unknown plot trace kind {plot_type}'
                                   f', assuming "scatter".')

            kwargs.update(conf.get('plotly', {}))
            trace = plot_kinds[plot_type](**kwargs)
            fig.add_trace(trace, row, 1)
        else:
            logger.info(
                'Indicator "%s" ignored. Reason: This indicator is not found '
                'in your strategy.',
                indicator
            )

    return fig


def add_profit(fig, row, data: pd.DataFrame, column: str, name: str) -> make_subplots:
    """
    Add profit-plot
    :param fig: Plot figure to append to
    :param row: row number for this plot
    :param data: candlestick DataFrame
    :param column: Column to use for plot
    :param name: Name to use
    :return: fig with added profit plot
    """
    profit = go.Scatter(
        x=data.index,
        y=data[column],
        name=name,
    )
    fig.add_trace(profit, row, 1)

    return fig


def add_max_drawdown(fig, row, trades: pd.DataFrame, df_comb: pd.DataFrame,
                     timeframe: str, starting_balance: float) -> make_subplots:
    """
    Add scatter points indicating max drawdown
    """
    try:
        _, highdate, lowdate, _, _, max_drawdown = calculate_max_drawdown(
            trades,
            starting_balance=starting_balance
        )

        drawdown = go.Scatter(
            x=[highdate, lowdate],
            y=[
                df_comb.loc[timeframe_to_prev_date(timeframe, highdate), 'cum_profit'],
                df_comb.loc[timeframe_to_prev_date(timeframe, lowdate), 'cum_profit'],
            ],
            mode='markers',
            name=f"Max drawdown {max_drawdown:.2%}",
            text=f"Max drawdown {max_drawdown:.2%}",
            marker=dict(
                symbol='square-open',
                size=9,
                line=dict(width=2),
                color='green'

            )
        )
        fig.add_trace(drawdown, row, 1)
    except ValueError:
        logger.warning("No trades found - not plotting max drawdown.")
    return fig


def add_underwater(fig, row, trades: pd.DataFrame, starting_balance: float) -> make_subplots:
    """
    Add underwater plots
    """
    try:
        underwater = calculate_underwater(
            trades,
            value_col="profit_abs",
            starting_balance=starting_balance
        )

        underwater_plot = go.Scatter(
            x=underwater['date'],
            y=underwater['drawdown'],
            name="Underwater Plot",
            fill='tozeroy',
            fillcolor='#cc362b',
            line={'color': '#cc362b'}
        )

        underwater_plot_relative = go.Scatter(
            x=underwater['date'],
            y=(-underwater['drawdown_relative']),
            name="Underwater Plot (%)",
            fill='tozeroy',
            fillcolor='green',
            line={'color': 'green'}
        )

        fig.add_trace(underwater_plot, row, 1)
        fig.add_trace(underwater_plot_relative, row + 1, 1)
    except ValueError:
        logger.warning("No trades found - not plotting underwater plot")
    return fig


def add_parallelism(fig, row, trades: pd.DataFrame, timeframe: str) -> make_subplots:
    """
    Add Chart showing trade parallelism
    """
    try:
        result = analyze_trade_parallelism(trades, timeframe)

        drawdown = go.Scatter(
            x=result.index,
            y=result['open_trades'],
            name="Parallel trades",
            fill='tozeroy',
            fillcolor='#242222',
            line={'color': '#242222'},
        )
        fig.add_trace(drawdown, row, 1)
    except ValueError:
        logger.warning("No trades found - not plotting Parallelism.")
    return fig


def plot_trades(fig, data: pd.DataFrame, trades: pd.DataFrame, config: {}) -> make_subplots:
    """
    Add trades to "fig" with correct date matching and filtering trades outside the data range
    """
    # Trades can be empty
    if trades is None or len(trades) == 0:
        logger.warning("No trades found.")
        return fig
    
    # Get data timerange boundaries
    data_start_date = data['date'].min()
    data_end_date = data['date'].max()
    
    # Make copy to avoid modifying original dataframe
    trades_copy = trades.copy()
    
    # Ensure open_date and close_date are datetime objects
    if not pd.api.types.is_datetime64_any_dtype(trades_copy['open_date']):
        trades_copy['open_date'] = pd.to_datetime(trades_copy['open_date'], utc=True)
    if not pd.api.types.is_datetime64_any_dtype(trades_copy['close_date']):
        trades_copy['close_date'] = pd.to_datetime(trades_copy['close_date'], utc=True)
    
    # Filter out trades that are outside the data timerange
    trades_in_range = trades_copy[(trades_copy['open_date'] >= data_start_date) & 
                                 (trades_copy['open_date'] <= data_end_date)]
    
    # Log how many trades were filtered out
    filtered_count = len(trades_copy) - len(trades_in_range)
    if filtered_count > 0:
        logger.warning(f"Filtered out {filtered_count} trades that were outside the displayed timerange.")
    
    if len(trades_in_range) == 0:
        logger.warning("No trades found within the displayed timerange.")
        return fig
        
    # Create descriptions for the trades
    trades_in_range['desc'] = trades_in_range.apply(
        lambda row: f"{row['profit_ratio']:.2%}, " +
        (f"{row['enter_tag']}, " if row['enter_tag'] is not None else "") +
        f"{row['exit_reason']}, " +
        f"{row['trade_duration']} min" + 
        (f"<br>{row['enter_descr']}" if 'enter_descr' in row and row['enter_descr'] is not None else ""),
        axis=1)
        
    trades_in_range['desc_close'] = trades_in_range.apply(
        lambda row: f"{row['profit_ratio']:.2%} ({round(row['profit_abs'],2)}$), " +
        (f"{row['enter_tag']}, " if row['enter_tag'] is not None and row['enter_tag'] != '' else "") +
        (f"{row['exit_reason']}, " if 'exit_reason' in row else "") +
        f"{row['trade_duration']} min",
        axis=1)
    
    # Create temporary columns for merging
    data['date_str'] = data['date'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
    trades_in_range['open_date_str'] = trades_in_range['open_date'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')

    # Merge to get 'i' values for trade entries
    entries_data = pd.merge(
        trades_in_range, 
        data[[col for col in ['date_str', 'i', 'enter_level'] if col in data.columns]], 
        how='left', 
        left_on='open_date_str', 
        right_on='date_str'
    )
    
    # Handle entries with no exact match by finding the closest date
    missing_entries = entries_data[entries_data['i'].isna()]
    if len(missing_entries) > 0:
        logger.info(f"Finding closest candle for {len(missing_entries)} trade entries without exact timestamp match.")
        
        for idx, trade in missing_entries.iterrows():
            # Find the closest candle timestamp for each missing entry
            closest_idx = abs(data['date'] - trade['open_date']).idxmin()
            entries_data.loc[idx, 'i'] = data.loc[closest_idx, 'i']
    
    # Now filter close dates that are within the data range
    exits_in_range = trades_in_range[(trades_in_range['close_date'] >= data_start_date) & 
                                    (trades_in_range['close_date'] <= data_end_date)]
    
    # Log how many exits were filtered out
    filtered_exits = len(trades_in_range) - len(exits_in_range)
    if filtered_exits > 0:
        logger.info(f"{filtered_exits} trade exits were outside the displayed timerange and won't be shown.")
    
    if len(exits_in_range) > 0:
        # Process exit data only if there are exits in range
        exits_in_range['close_date_str'] = exits_in_range['close_date'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
        
        # Merge to get 'i' values for trade exits
        exits_data = pd.merge(
            exits_in_range, 
            data[['date_str', 'i']], 
            how='left', 
            left_on='close_date_str', 
            right_on='date_str'
        )
        
        # Handle exits with no exact match by finding the closest date
        missing_exits = exits_data[exits_data['i'].isna()]
        if len(missing_exits) > 0:
            logger.info(f"Finding closest candle for {len(missing_exits)} trade exits without exact timestamp match.")
            
            for idx, trade in missing_exits.iterrows():
                # Find the closest candle timestamp for each missing exit
                closest_idx = abs(data['date'] - trade['close_date']).idxmin()
                exits_data.loc[idx, 'i'] = data.loc[closest_idx, 'i']
    else:
        exits_data = pd.DataFrame()  # Empty DataFrame if no exits in range

    # print(entries_data)
    # print(entries_data.columns.to_list())
    # exit()
    
    # Create trade entry markers
    entries_long = entries_data[entries_data['is_short'] != 1]
    trade_entries = go.Scatter(
        x=entries_long["i"],
        y=entries_long["open_rate"],
        mode='markers',
        name=f'Trade long ({len(entries_long)})',
        #text=entries_long["desc"],
        text=entries_long.apply(
            lambda row: 
                '{:%Y-%m-%d %H:%M:%S}{}<br>'.format(row['open_date'], row['open_date'].strftime('%z')[:3] + ':' + row['open_date'].strftime('%z')[3:] if config['exchange']['name'] == "USA_Stocks" else "") + \
                (f"direction={'short' if row['is_short'] else 'long'}<br>") + \
                (f"stake_amount={round(row['stake_amount'],2)}$<br>") + \
                (f"enter_level={row['enter_level']}<br>" if 'enter_level' in row and not np.isnan(row['enter_level']) else '') + \
                (f"{row['desc']}"),
            axis=1),
        marker=dict(
            symbol='triangle-up',
            size=18,
            line=dict(width=1, color='#333'),
            color='#4fea74'
        )
    )
    fig.add_trace(trade_entries, 1, 1)

    entries_short = entries_data[entries_data['is_short'] == 1]
    trade_entries = go.Scatter(
        x=entries_short["i"],
        y=entries_short["open_rate"],
        mode='markers',
        name=f'Trade short ({len(entries_short)})',
        #text=entries_short["desc"],
        text=entries_short.apply(
            lambda row: 
                '{:%Y-%m-%d %H:%M:%S}{}<br>'.format(row['open_date'], row['open_date'].strftime('%z')[:3] + ':' + row['open_date'].strftime('%z')[3:] if config['exchange']['name'] == "USA_Stocks" else "") + \
                (f"direction={'short' if row['is_short'] else 'long'}<br>") + \
                (f"stake_amount={round(row['stake_amount'],2)}$<br>") + \
                (f"enter_level={row['enter_level']}<br>" if 'enter_level' in row and not np.isnan(row['enter_level']) else '') + \
                (f"{row['desc']}"),
            axis=1),
        marker=dict(
            symbol='triangle-down',
            size=18,
            line=dict(width=1, color='#333'),
            color='red'
        )
    )
    fig.add_trace(trade_entries, 1, 1)



    # Create exit profit markers if there are any
    if not exits_data.empty and any(exits_data['profit_ratio'] > 0):
        profitable_exits = exits_data[exits_data['profit_ratio'] > 0]
        trade_exits = go.Scatter(
            x=profitable_exits["i"],
            y=profitable_exits["close_rate"],
            #text=profitable_exits["desc_close"],
            text=profitable_exits.apply(
                lambda row: 
                    '{:%Y-%m-%d %H:%M:%S}{}<br>'.format(row['close_date'], row['close_date'].strftime('%z')[:3] + ':' + row['close_date'].strftime('%z')[3:] if config['exchange']['name'] == "USA_Stocks" else "") + \
                    (f"direction={'short' if row['is_short'] else 'long'}<br>") + \
                    (f"{row['desc_close']}"),
                axis=1),
            mode='markers',
            name=f'Exit - Profit ({len(profitable_exits)})',
            marker=dict(
                symbol='square-open',
                size=18,
                line=dict(width=4),
                color='#10c5f5'
            )
        )
        fig.add_trace(trade_exits, 1, 1)
    
    # Create exit loss markers if there are any
    if not exits_data.empty and any(exits_data['profit_ratio'] <= 0):
        loss_exits = exits_data[exits_data['profit_ratio'] <= 0]
        trade_exits_loss = go.Scatter(
            x=loss_exits["i"],
            y=loss_exits["close_rate"],
            #text=loss_exits["desc_close"],
            text=loss_exits.apply(
                lambda row: 
                    '{:%Y-%m-%d %H:%M:%S}{}<br>'.format(row['close_date'], row['close_date'].strftime('%z')[:3] + ':' + row['close_date'].strftime('%z')[3:] if config['exchange']['name'] == "USA_Stocks" else "") + \
                    (f"direction={'short' if row['is_short'] else 'long'}<br>") + \
                    (f"{row['desc_close']}"),
                axis=1),
            mode='markers',
            name=f'Exit - Loss ({len(loss_exits)})',
            marker=dict(
                symbol='square-open',
                size=18,
                line=dict(width=4),
                color='#9d0fdf'
            )
        )
        fig.add_trace(trade_exits_loss, 1, 1)
    
    logger.info(f"Added {len(entries_data)} trade entries and {len(exits_data) if not exits_data.empty else 0} trade exits to the plot")
    
    return fig

def create_plotconfig(indicators1: List[str], indicators2: List[str],
                      plot_config: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Combines indicators 1 and indicators 2 into plot_config if necessary
    :param indicators1: List containing Main plot indicators
    :param indicators2: List containing Sub plot indicators
    :param plot_config: Dict of Dicts containing advanced plot configuration
    :return: plot_config - eventually with indicators 1 and 2
    """

    if plot_config:
        if indicators1:
            plot_config['main_plot'] = {ind: {} for ind in indicators1}
        if indicators2:
            plot_config['subplots'] = {'Other': {ind: {} for ind in indicators2}}

    if not plot_config:
        # If no indicators and no plot-config given, use defaults.
        if not indicators1:
            indicators1 = ['sma', 'ema3', 'ema5']
        if not indicators2:
            indicators2 = ['macd', 'macdsignal']

        # Create subplot configuration if plot_config is not available.
        plot_config = {
            'main_plot': {ind: {} for ind in indicators1},
            'subplots': {'Other': {ind: {} for ind in indicators2}},
        }
    if 'main_plot' not in plot_config:
        plot_config['main_plot'] = {}

    if 'subplots' not in plot_config:
        plot_config['subplots'] = {}
    return plot_config


def plot_area(fig, row: int, data: pd.DataFrame, indicator_a: str,
              indicator_b: str, label: str = "",
              fill_color: str = "rgba(0,176,246,0.2)",
              plotly: dict = {}) -> make_subplots:
    """ Creates a plot for the area between two traces and adds it to fig.
    :param fig: Plot figure to append to
    :param row: row number for this plot
    :param data: candlestick DataFrame
    :param indicator_a: indicator name as populated in strategy
    :param indicator_b: indicator name as populated in strategy
    :param label: label for the filled area
    :param fill_color: color to be used for the filled area
    :return: fig with added  filled_traces plot
    """
    if indicator_a in data and indicator_b in data:
        # make lines invisible to get the area plotted, only.
        line = {'color': 'rgba(255,255,255,0)'}
        # TODO: Figure out why scattergl causes problems plotly/plotly.js#2284
        trace_a = go.Scatter(x=list(range(len(data))), y=data[indicator_a],
        #trace_a = go.Scatter(x=data.date, y=data[indicator_a],
                             showlegend=False,
                             line=line)
        trace_b = go.Scatter(x=list(range(len(data))), y=data[indicator_b], name=label,
        #trace_b = go.Scatter(x=data.date, y=data[indicator_b], name=label,
                             fill="tonexty", fillcolor=fill_color,
                             line=line, **plotly)
        fig.add_trace(trace_a, row, 1)
        fig.add_trace(trace_b, row, 1)
    return fig


def add_areas(fig, row: int, data: pd.DataFrame, indicators) -> make_subplots:
    """ Adds all area plots (specified in plot_config) to fig.
    :param fig: Plot figure to append to
    :param row: row number for this plot
    :param data: candlestick DataFrame
    :param indicators: dict with indicators. ie.: plot_config['main_plot'] or
                            plot_config['subplots'][subplot_label]
    :return: fig with added  filled_traces plot
    """
    for indicator, ind_conf in indicators.items():
        if indicator in ('show_clusters'):
            continue
        if ind_conf and 'fill_to' in ind_conf:
            indicator_b = ind_conf['fill_to']
            if indicator in data and indicator_b in data:
                label = ind_conf.get('fill_label',
                                     f'{indicator}<>{indicator_b}')
                fill_color = ind_conf.get('fill_color', 'rgba(0,176,246,0.2)')
                fig = plot_area(fig, row, data, indicator, indicator_b,
                                label=label, fill_color=fill_color, plotly=ind_conf.get('plotly'))
            elif indicator not in data:
                logger.info(
                    'Indicator "%s" ignored. Reason: This indicator is not '
                    'found in your strategy.', indicator
                )
            elif indicator_b not in data:
                logger.info(
                    'fill_to: "%s" ignored. Reason: This indicator is not '
                    'in your strategy.', indicator_b
                )
    return fig


def create_scatter(
    data,
    column_name,
    color,
    direction
) -> Optional[go.Scatter]:

    if column_name in data.columns:
        df_short = data[data[column_name] == 1]
        if len(df_short) > 0:
            shorts = go.Scatter(
                #x=df_short.date,
                x=df_short.i,
                y=df_short.close,
                mode='markers',
                text=df_short.apply(
                    lambda row: '{:%Y-%m-%d %H:%M:%S}'.format(row['date']) + \
                        (f"<br>{row['enter_tag']}" if 'enter_tag' in row and type(row['enter_tag']) == str and row['enter_tag'] != '' else '') + \
                        (f"<br>{row['exit_tag']}" if 'exit_tag' in row and type(row['exit_tag']) == str and row['exit_tag'] != '' else '') + \
                        (f"<br>{row['enter_descr']}" if column_name in ['enter_long','enter_short'] and 'enter_descr' in row and row['enter_descr'] is not None else ""),
                    axis=1),
                name='{}({})'.format(column_name, len(df_short)),
                marker=dict(
                    symbol=f"triangle-{direction}-dot",
                    size=9,
                    line=dict(width=1),
                    color=color,
                )
            )
            return shorts
        else:
            logger.warning(f"No {column_name}-signals found.")

    return None


def generate_candlestick_graph(pair: str, data: pd.DataFrame, trades: pd.DataFrame = None, *,
                               indicators1: List[str] = [],
                               indicators2: List[str] = [],
                               plot_config: Dict[str, Dict] = {},
                               config = {}
                               ) -> go.Figure:
    """
    Generate the graph from the data generated by Backtesting or from DB
    Volume will always be ploted in row2, so Row 1 and 3 are to our disposal for custom indicators
    :param pair: Pair to Display on the graph
    :param data: OHLCV DataFrame containing indicators and entry/exit signals
    :param trades: All trades created
    :param indicators1: List containing Main plot indicators
    :param indicators2: List containing Sub plot indicators
    :param plot_config: Dict of Dicts containing advanced plot configuration
    :return: Plotly figure
    """

    data['i'] = range(len(data))

    if 'subplots' in plot_config:
        for i, label in enumerate(list(plot_config['subplots'])[:]):
            sub_config = plot_config['subplots'][label]
            found = False
            for k, v in sub_config.items():
                if k in data.columns:
                    found = True
                    break
            if not found:
                del plot_config['subplots'][label]

    plot_config = create_plotconfig(indicators1, indicators2, plot_config)
    rows = 1 + len(plot_config['subplots'])
    #row_widths = [1 for _ in plot_config['subplots']]
    row_widths = []
    for key in reversed(plot_config['subplots'].keys()):
        if key == 'ADX+DI': row_widths.append(1.0)
        elif 'Heik' in key: row_widths.append(0.50)
        elif 'Cum delta' in key: row_widths.append(2.0)
        elif 'Z1' in key or 'Z2' in key or 'Z3' in key or 'Z4' in key or 'Z5' in key or 'Z6' in key or 'Z7' in key or 'Z8' in key or 'Z9' in key: row_widths.append(0.35)
        elif 'liq' in key or 'liq_' in key: row_widths.append(0.35)
        elif key in ['vol','Volume','bi','bi.f','by','by.f','okx','okx.f','coin']: row_widths.append(0.45)
        elif 'corr' in key: row_widths.append(0.35)
        elif key in ['Time', 'Trades', 't_ema']: row_widths.append(0.50)
        else: row_widths.append(1.0)
    # Define the graph
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        #row_width=row_widths + [1, 4],
        #row_width=row_widths + [0.5,5],
        row_width=row_widths + [5],
        vertical_spacing=0.0001,
    )
    fig['layout'].update(title=pair)
    fig['layout']['yaxis1'].update(title='Price')
    #fig['layout']['yaxis2'].update(title='Volume')
    for i, name in enumerate(plot_config['subplots']):
        fig['layout'][f'yaxis{2 + i}'].update(title=name)
    fig['layout']['xaxis']['rangeslider'].update(visible=False)
    fig.update_layout(modebar_add=["v1hovermode", "toggleSpikeLines"])

    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), dragmode='pan', spikedistance=-1, xaxis_rangeslider_visible=False)
    fig.update_xaxes(showspikes=True, showticklabels=False, spikemode='across', spikesnap='cursor', showline=True, showgrid=True, spikethickness=1, spikecolor='#333')
    ##fig.update_xaxes(row=2, col=1)
    #fig.update_layout(hovermode="x")
    fig.update_yaxes(showspikes=True, spikemode='across', spikesnap='cursor', showline=True, showgrid=True, spikethickness=1, spikecolor='#333')
    ##fig.update_yaxes(automargin=True)

    dfn = data.to_dict(orient="records")

    # Common information
    candles = go.Candlestick(
        #x=data.date,
        x=list(range(len(data))),
        open=data.open,
        high=data.high,
        low=data.low,
        close=data.close,
        text=data.apply(lambda row: f"volume={human_format(row['volume'])}<br>" + "{:%Y-%m-%d %H:%M:%S}".format(row['date']), axis=1),
        name='Price'
    )
    fig.add_trace(candles, 1, 1)


    # # Add Bollinger Bands
    # fig = plot_area(fig, 1, data, 'bb_lowerband', 'bb_upperband',
    #                 label="Bollinger Band")
    # # prevent bb_lower and bb_upper from plotting
    # try:
    #     del plot_config['main_plot']['bb_lowerband']
    #     del plot_config['main_plot']['bb_upperband']
    # except KeyError:
    #     pass

    if 'stoploss' in data.columns:
        stoploss = go.Scatter(
            #x=data["date"],
            x=list(range(len(data))),
            #y=data["stoploss"],
            y=data.apply(lambda row: row['stoploss'][0] if isinstance(row['stoploss'], tuple) else row['stoploss'], axis=1),
            mode='markers',
            name='stoploss',
            #marker_line_color="midnightblue", marker_color="lightskyblue",
            text=data.apply(lambda row: f"{-1 * abs(1 - row['close'] * 1 / (row['stoploss'][0] if isinstance(row['stoploss'], tuple) else row['stoploss'])):.2%}" \
                    + ("<br>{}".format(row['stoploss'][1]) if isinstance(row['stoploss'], tuple) and row['stoploss'][1] != None else '') \
                    + "<br>{:%Y-%m-%d %H:%M:%S}".format(row['date']) \
                    if isinstance(row['stoploss'], tuple) and row['stoploss'][0] != None else None, axis=1),
            marker=dict(
                symbol='x',
                size=8,
                line=dict(color='midnightblue', width=1),
                color='lightskyblue'

            )
        )
        fig.add_trace(stoploss, 1, 1)
    
    if 'copy_traders' in data.columns:
        flag = True
        dfn = data.to_dict(orient="records")
        for i, row in enumerate(dfn):
            if not row['copy_traders']:
                continue
            for tr in row['copy_traders']:
                fig.add_trace(go.Scatter(
                    x=[row['i']],
                    #y=[tr['p']],
                    y=[row['open']],
                    mode='markers',
                    name='copy_trade',
                    text=[str(tr['o']) + '<br>' + str(tr['id'])],
                    marker=dict(
                        symbol=f"triangle-{'up' if tr['s'] == 'long' else 'down'}-dot",
                        size=9,
                        line=dict(width=1),
                        color='green' if tr['s'] == 'long' else 'red',
                    ),
                    showlegend=True if flag else False,
                ), 1, 1)
                fig.add_trace(go.Scatter(
                    x=[row['i']],
                    y=[row['low']],
                    mode='text',
                    text=str(tr['id'])[-4:],
                    marker=dict(color="brown", size=6),
                    showlegend=True if flag else False,
                    visible=True,
                    #visible='legendonly',
                    name='label_tr',
                    legendgroup='label_tr',
                ), 1, 1)
                flag = False

    if 'reward' in data.columns:
        flags = [False, False, False]
        for i, row in enumerate(dfn):
            #if type(row['reward']) != str: continue
            #name = 'reward'
            if row['reward'] < 0: name = 'reward -'
            if row['reward'] == 0: name = 'reward 0'
            if row['reward'] > 0: name = 'reward +'
            fig.add_trace(go.Scatter(
                x = [i],
                y = [row['low']],
                mode='text',
                text=row['reward'] if not np.isnan(row['reward']) else '',
                marker=dict(color="brown", size=6),
                showlegend=True if row['reward'] < 0 and not flags[0] or row['reward'] == 0 and not flags[1] or row['reward'] > 0 and not flags[2] else False,
                #showlegend=True if i == 0 else False,
                visible='legendonly' if row['reward'] > 0 else 'legendonly',
                name=name,
                legendgroup=name,
            ), 1, 1)
            if row['reward'] < 0: flags[0] = True
            if row['reward'] == 0: flags[1] = True
            if row['reward'] > 0: flags[2] = True
            #f'pivotlow_{self.buy_pivot_period.value}': {'plotly': {'mode': 'text', 'marker': dict(color="brown", size=6), 'text': 'L', 'legendgroup': 'pivots', 'showlegend': False}}

    if 'label' in data.columns:
        flag = False
        for i, row in enumerate(dfn):
            if not pd.isnull(row['label']):
                fig.add_trace(go.Scatter(
                    x = [i],
                    y = [row['low']],
                    mode='text',
                    text=row['label'],
                    marker=dict(color="brown", size=6),
                    showlegend=True if not flag else False,
                    #visible=True,
                    visible='legendonly',
                    name='label',
                    legendgroup='label',
                ), 1, 1)
                flag = True

    # main plot goes to row 1
    fig = add_areas(fig, 1, data, plot_config['main_plot'])
    fig = add_indicators(fig=fig, row=1, indicators=plot_config['main_plot'], data=data)


    fig = plot_trades(fig, data, trades, config)

    # sub plot: Volume goes to row 2
    # volume = go.Bar(
    #     #x=data['date'],
    #     x=list(range(len(data))),
    #     y=data['volume'],
    #     name='Volume',
    #     showlegend=False,
    #     marker_color='DarkSlateGrey',
    #     marker_line_color='DarkSlateGrey'
    # )
    # fig.add_trace(volume, 2, 1)
    
    # add each sub plot to a separate row
    for i, label in enumerate(plot_config['subplots']):
        sub_config = plot_config['subplots'][label]
        row = 2 + i
        fig = add_indicators(fig=fig, row=row, indicators=sub_config,
                             data=data)
        # fill area between indicators ( 'fill_to': 'other_indicator')
        fig = add_areas(fig, row, data, sub_config)
    

    longs = create_scatter(data, 'enter_long', '#f6ff08', 'up')
    exit_longs = create_scatter(data, 'exit_long', '#ff79fe', 'down')
    shorts = create_scatter(data, 'enter_short', 'blue', 'down')
    exit_shorts = create_scatter(data, 'exit_short', 'red', 'up')

    for scatter in [longs, exit_longs, shorts, exit_shorts]:
        if scatter:
            fig.add_trace(scatter, 1, 1)
    


    fig.update_traces(xaxis="x1")

    # if config.get('timerange', None):
    #     timerange = config.get('timerange').split('-')
    #     if timerange[1] != '':
    #         t1 = timerange[0][:6] + '-' + timerange[0][6:]
    #         t1 = t1[:4] + '-' + t1[4:]
    #         t2 = timerange[1][:6] + '-' + timerange[1][6:]
    #         t2 = t2[:4] + '-' + t2[4:]
    #         fig.update_xaxes(type="date", range=[t1, t2])

    # if config['timeframe'] != '1d':
    #     for d in data[(data['date'].dt.hour == 0) & (data['date'].dt.minute == 0)]['date']:
    #         fig.add_vline(x=d, line_width=1, line_dash="dash", line_color="#000", opacity=0.35)


    # vertical lines
    if config['timeframe'] not in ['1d', '4h']:
        for i, row in enumerate(dfn):
            if i == 0: continue
            if row['date'].strftime('%Y-%m-%d') != dfn[i - 1]['date'].strftime('%Y-%m-%d'):
                fig.add_vline(x=i, line_width=1, line_dash="dash", line_color="#000", opacity=0.35)
    elif config['timeframe'] == '1d':
        for i, row in enumerate(dfn):
            if i == 0: continue
            if row['date'].strftime('%Y-%m') != dfn[i - 1]['date'].strftime('%Y-%m'):
                fig.add_vline(x=i, line_width=1, line_dash="dash", line_color="#000", opacity=0.35)
        
    # fig.update_layout(legend=dict(
    #     orientation="h",
    #     yanchor="bottom",
    #     y=1.02,
    #     xanchor="right",
    #     x=1
    # ))

    if 0:
        fig.update_layout(
            legend=dict(
                # x=0,
                # y=1,
                traceorder="reversed",
                font=dict(
                    size=12,
                ),
            )
        )

    if 'legend_title' in plot_config['main_plot']:
        fig.update_layout(legend_title_text=plot_config['main_plot']['legend_title'])
        #fig.update_layout(legend_title_text='test')

    if 0:
        file_path = '/Users/sirjay/Downloads/adjust_trade_position.pkl'
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                martingale = pickle.load(f)

            martingale = pd.DataFrame(martingale)
            martingale = martingale.loc[(martingale['current_time'] >= dfn[0]['date']) & (martingale['current_time'] <= dfn[-1]['date'])]
            if len(martingale):
                print()
                print('martingale:')
                print(martingale)
                print()
                martingale.rename(columns={'current_time': 'date'}, inplace=True)
                ma = pd.merge(martingale, data[['date', 'i']], how='inner', on='date')
                ma['desc'] = ma.apply(
                        lambda row: f"#{row['count_of_entries']}, " +
                        #f"total_profit={round(row['current_profit']*100,2)}%, " +
                        f"profit_from_start={round(row['profit_from_start'],2)}%, " +
                        f"profit_from_last_order={round(row['profit_from_last_order'],2)}%, " +
                        f"stake_amount={round(row['stake_amount'],2)}",
                        axis=1)
                fig.add_trace(go.Scatter(
                    x = ma['i'],
                    y = ma['current_rate'],
                    text=ma['desc'],
                    mode='markers',
                    marker=dict(color="#e845f9", size=8, line=dict(color="#fff", width=2)),
                    showlegend=True,
                    visible=True,
                    name='martingale',
                    legendgroup='martingale',
                ), 1, 1)


    return fig

def generate_profit_graph(pairs: str, data: Dict[str, pd.DataFrame],
                          trades: pd.DataFrame, timeframe: str, stake_currency: str,
                          starting_balance: float) -> go.Figure:
    # Combine close-values for all pairs, rename columns to "pair"
    try:
        df_comb = combine_dataframes_with_mean(data, "close")
    except ValueError:
        raise OperationalException(
            "No data found. Please make sure that data is available for "
            "the timerange and pairs selected.")

    # Trim trades to available OHLCV data
    trades = extract_trades_of_period(df_comb, trades, date_index=True)
    if len(trades) == 0:
        raise OperationalException('No trades found in selected timerange.')

    # Add combined cumulative profit
    df_comb = create_cum_profit(df_comb, trades, 'cum_profit', timeframe)

    # Plot the pairs average close prices, and total profit growth
    avgclose = go.Scatter(
        x=df_comb.index,
        y=df_comb['mean'],
        name='Avg close price',
    )

    fig = make_subplots(rows=6, cols=1, shared_xaxes=True,
                        row_heights=[1, 1, 1, 0.5, 0.75, 0.75],
                        vertical_spacing=0.05,
                        subplot_titles=[
                            "AVG Close Price",
                            "Combined Profit",
                            "Profit per pair",
                            "Parallelism",
                            "Underwater",
                            "Relative Drawdown",
                        ])
    fig['layout'].update(title="Freqtrade Profit plot")
    fig['layout']['yaxis1'].update(title='Price')
    fig['layout']['yaxis2'].update(title=f'Profit {stake_currency}')
    fig['layout']['yaxis3'].update(title=f'Profit {stake_currency}')
    fig['layout']['yaxis4'].update(title='Trade count')
    fig['layout']['yaxis5'].update(title='Underwater Plot')
    fig['layout']['yaxis6'].update(title='Underwater Plot Relative (%)', tickformat=',.2%')
    fig['layout']['xaxis']['rangeslider'].update(visible=False)
    fig.update_layout(modebar_add=["v1hovermode", "toggleSpikeLines"])

    fig.add_trace(avgclose, 1, 1)
    fig = add_profit(fig, 2, df_comb, 'cum_profit', 'Profit')
    fig = add_max_drawdown(fig, 2, trades, df_comb, timeframe, starting_balance)
    fig = add_parallelism(fig, 4, trades, timeframe)
    # Two rows consumed
    fig = add_underwater(fig, 5, trades, starting_balance)

    for pair in pairs:
        profit_col = f'cum_profit_{pair}'
        try:
            df_comb = create_cum_profit(df_comb, trades[trades['pair'] == pair], profit_col,
                                        timeframe)
            fig = add_profit(fig, 3, df_comb, profit_col, f"Profit {pair}")
        except ValueError:
            pass
    return fig


def generate_plot_filename(pair: str, timeframe: str) -> str:
    """
    Generate filenames per pair/timeframe to be used for storing plots
    """
    pair_s = pair_to_filename(pair)
    file_name = 'freqtrade-plot-' + pair_s + '-' + timeframe + '.html'

    logger.info('Generate plot file for %s', pair)

    return file_name


def store_plot_file(fig, filename: str, directory: Path, auto_open: bool = False) -> None:
    """
    Generate a plot html file from pre populated fig plotly object
    :param fig: Plotly Figure to plot
    :param filename: Name to store the file as
    :param directory: Directory to store the file in
    :param auto_open: Automatically open files saved
    :return: None
    """
    directory.mkdir(parents=True, exist_ok=True)

    _filename = directory.joinpath(filename)
    plot(fig, filename=str(_filename),
         auto_open=auto_open, config=dict({'scrollZoom': True, 'responsive': True}))
    logger.info(f"Stored plot as {_filename}")


def load_and_plot_trades(config: Dict[str, Any]):
    """
    From configuration provided
    - Initializes plot-script
    - Get candle (OHLCV) data
    - Generate Dafaframes populated with indicators and signals based on configured strategy
    - Load trades executed during the selected period
    - Generate Plotly plot objects
    - Generate plot files
    :return: None
    """
    strategy = StrategyResolver.load_strategy(config)

    exchange = ExchangeResolver.load_exchange(config)
    IStrategy.dp = DataProvider(config, exchange)
    strategy.ft_bot_start()
    strategy.bot_loop_start(datetime.now(timezone.utc))
    plot_elements = init_plotscript(config, list(exchange.markets), strategy.startup_candle_count)
    timerange = plot_elements['timerange']
    trades = plot_elements['trades']
    pair_counter = 0
    for pair, data in plot_elements["ohlcv"].items():
        pair_counter += 1
        logger.info("analyse pair %s", pair)

        df_analyzed = strategy.analyze_ticker(data, {'pair': pair})

        # print(f"plotting.py df_analyzed before trim (timerange={timerange}):")
        # print(df_analyzed)

        print('trades:')
        print(trades)

        #
        df_analyzed = trim_dataframe(df_analyzed, timerange)
        df_analyzed = df_analyzed.iloc[0:1200]

        print('plotting.py df_analyzed:')
        print(df_analyzed)

        if not trades.empty:
            trades_pair = trades.loc[trades['pair'] == pair]
            #
            trades_pair = extract_trades_of_period(df_analyzed, trades_pair)
        else:
            trades_pair = trades

        fig = generate_candlestick_graph(
            pair=pair,
            data=df_analyzed,
            trades=trades_pair,
            indicators1=config.get('indicators1', []),
            indicators2=config.get('indicators2', []),
            plot_config=strategy.plot_config if hasattr(strategy, 'plot_config') else {},
            config=config
        )


        store_plot_file(fig, filename=generate_plot_filename(pair, config['timeframe']),
                        directory=config['user_data_dir'] / 'plot', auto_open=config.get('plot_auto_open', False))

    logger.info('End of plotting process. %s plots generated', pair_counter)


def plot_profit(config: Dict[str, Any]) -> None:
    """
    Plots the total profit for all pairs.
    Note, the profit calculation isn't realistic.
    But should be somewhat proportional, and therefor useful
    in helping out to find a good algorithm.
    """
    if 'timeframe' not in config:
        raise OperationalException('Timeframe must be set in either config or via --timeframe.')

    exchange = ExchangeResolver.load_exchange(config)
    plot_elements = init_plotscript(config, list(exchange.markets))
    trades = plot_elements['trades']
    # Filter trades to relevant pairs
    # Remove open pairs - we don't know the profit yet so can't calculate profit for these.
    # Also, If only one open pair is left, then the profit-generation would fail.
    trades = trades[(trades['pair'].isin(plot_elements['pairs']))
                    & (~trades['close_date'].isnull())
                    ]
    if len(trades) == 0:
        raise OperationalException("No trades found, cannot generate Profit-plot without "
                                   "trades from either Backtest result or database.")

    # Create an average close price of all the pairs that were involved.
    # this could be useful to gauge the overall market trend
    fig = generate_profit_graph(plot_elements['pairs'], plot_elements['ohlcv'],
                                trades, config['timeframe'],
                                config.get('stake_currency', ''),
                                config.get('available_capital', config['dry_run_wallet']))
    store_plot_file(fig, filename='freqtrade-profit-plot.html',
                    directory=config['user_data_dir'] / 'plot',
                    auto_open=config.get('plot_auto_open', False))


def human_format(num):
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'k', 'm', 'B', 'T'][magnitude])