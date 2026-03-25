import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
import ccxt
import requests
import time

from freqtrade.exchange import Exchange
from freqtrade.exceptions import OperationalException
from freqtrade.constants import DEFAULT_DATAFRAME_COLUMNS
from freqtrade.enums import CandleType
from freqtrade.data.converter import ohlcv_to_dataframe

logger = logging.getLogger(__name__)


class Fake_Exchange(Exchange):
    """
    Fake_Exchange Exchange class для работы с историческими данными активов
    """
    
    _ft_has: Dict = {
        "stoploss_on_exchange": False,
        "order_time_in_force": ['gtc'],
        "time_in_force_parameter": "timeInForce",
        "ohlcv_candle_limit": 1000,
        "trades_pagination": "id",
        "trades_pagination_arg": "fromId",
        "l2_limit_range": [5, 10, 20, 50, 100, 500, 1000],
        "ohlcv_has_history": True,  # ВАЖНО: указываем что есть исторические данные
    }

    def __init__(self, config: dict, validate: bool = True) -> None:
        """
        Инициализация exchange
        """        
        # Вызываем родительский __init__ для полной совместимости
        try:
            super().__init__(config, validate=False)
        except Exception as e:
            logger.warning(f"Failed to initialize parent Exchange: {e}")
            # Если не удалось, инициализируем базовые атрибуты вручную
            self._config = {}
            self._config.update(config)
            self._markets = {}
            self._trading_fees = {}
            self._leverage_tiers = {}
            self._api = None
            self._api_async = None
        
        # Теперь переопределяем нужные атрибуты для нашей кастомной биржи
        self._config.update(config)  # Обновляем конфиг нашими данными
        
        # Создаем наш фиктивный API
        self._api = self._create_fake_api()
        self._api_async = self._create_fake_api()  # Тоже нужен для некоторых методов
        
        # Путь к данным
        datadir = config.get('datadir')
        if datadir:
            self.data_path = Path(datadir)
        else:
            exit('no data dir')

        

        
        self.known_symbols = [
            # stocks
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'BRK.B', 'LLY', 'UNH',
            'XOM', 'V', 'JPM', 'JNJ', 'WMT', 'PG', 'MA', 'ORCL', 'CVX', 'HD', 'MRK', 'KO',
            'PEP', 'COST', 'ABBV', 'BAC', 'ADBE', 'CRM', 'TMO', 'AVGO', 'NFLX', 'AMD', 'DIS',
            'ACN', 'NKE', 'TXN', 'DHR', 'VZ', 'COP', 'PFE', 'CMCSA', 'QCOM', 'WFC', 'NEE',
            'PM', 'INTC', 'LIN', 'RTX', 'T', 'UNP', 'LOW', 'IBM', 'SPGI', 'CAT', 'INTU',
            'GS', 'MDT', 'BKNG', 'GILD', 'AXP', 'HON', 'SYK', 'DE', 'ISRG', 'NOW', 'BLK',
            'GE', 'AMT', 'ELV', 'VRTX', 'CI', 'SLB', 'MMC', 'PLD', 'C', 'SO', 'ZTS', 'MDLZ',
            'MO', 'CB', 'REGN', 'DUK', 'FDX', 'PGR', 'AON', 'EMR', 'BSX', 'ITW', 'EOG',
            'CSX', 'CL', 'GM', 'MCD', 'USB', 'NSC', 'MMM', 'APD', 'SBUX', 'TGT', 'PSA', 'ADI',

            # fx
            'EURUSD', 'USDJPY', 'GBPUSD', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD',
            'EURJPY', 'EURGBP', 'GBPJPY', 'EURCHF', 'EURCAD', 'EURAUD', 'GBPCHF',
            'GBPCAD', 'GBPAUD', 'AUDJPY', 'AUDCAD', 'AUDCHF', 'CADJPY', 'CHFJPY',
            'NZDJPY', 'NZDCAD', 'NZDCHF', 'AUDNZD', 'EURNZD', 'GBPNZD', 'USDSEK',
            'USDNOK', 'USDDKK', 'USDSGD', 'USDHKD', 'USDMXN', 'USDZAR', 'USDPLN',
            'USDCZK', 'USDHUF', 'USDTRY', 'USDRUB', 'USDCNH', 'USDKRW', 'USDINR',
            'EURSEK', 'EURNOK', 'EURDKK', 'EURPLN', 'EURCZK', 'EURHUF', 'EURTRY',
            'USDTHB', 'CADCHF', 'USDILS', 'USDRON', 'GBPSGD',

            # futures
            'ES', 'NQ', 'YM', 'RTY', 'CL', 'GC', 'SI', 'NG', 'ZB', 'ZN', 'ZF', 'ZT',
            '6E', '6J', '6B', '6C', '6A', '6N', '6S', 'HG', 'PL', 'PA', 'HO', 'RB',
            'ZC', 'ZS', 'ZW', 'ZM', 'ZL', 'ZO', 'ZR', 'LE', 'GF', 'HE', 'KC', 'SB',
            'CC', 'CT', 'OJ', 'DX', 'VX', 'BZ', 'MGC', 'SIL', 'MES', 'MNQ', 'LBS',
            'DJT', 'FEI', 'FNG',

            # futures GC
            "GCN5","GCQ5","GCU5","GCV5","GCX5","GCZ5","GCF6","GCG6","GCH6","GCJ6","GCK6","GCM6","GCN6","GCQ6","GCU6","GCV6","GCX6","GCZ6","GCF7","GCG7","GCH7","GCJ7","GCK7","GCM7","GCN7","GCQ7","GCZ7","GCM8","GCZ8","GCM9","GCZ9","GCM0","GCZ0","GCM1",
        ]

        
        # Инициализируем наши данные
        self._available_pairs: List[str] = []
        self._init_available_pairs()
        self._init_markets()
        
        logger.info(f"Exchange initialized with data path: {self.data_path}")
        # logger.info(f"Available pairs: {self._available_pairs}")

    def _init_available_pairs(self) -> None:
        """
        Инициализирует список доступных пар на основе известных символов
        """
        for symbol in self.known_symbols:
            pair_name = f"{symbol}/USD"
            self._available_pairs.append(pair_name)
        
        logger.info(f"Initialized {len(self._available_pairs)} available pairs")

    def _create_fake_api(self):
        """
        Создает фиктивный API объект для совместимости с ccxt
        """
        _name = self.name
        class FakeAPI:
            def __init__(self):
                self.markets = {}
                self.timeframes = {
                    '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', 
                    '30m': '30m', '1h': '1h', '2h': '2h', '4h': '4h', 
                    '6h': '6h', '8h': '8h', '12h': '12h', '1d': '1d'
                }
                self.id = _name.lower()
                self.name = _name
                self.precisionMode = 2  # TICK_SIZE
                self.paddingMode = 0    # NO_PADDING
                self.has = {
                    'fetchOHLCV': True,
                    'spot': True,
                }
                
                self.features = {
                    'spot': {},
                    'margin': {},
                    'swap': {
                        'linear': {},
                        'inverse': {}
                    },
                    'future': {},
                    'option': {}
                }
                
            def calculate_fee(self, symbol: str, type: str, side: str, 
                            amount: float, price: float, takerOrMaker: str = 'taker') -> dict:
                """
                Возвращает фиксированную комиссию
                """
                fee_rate = 0.001  # 0.1% комиссия
                return {
                    'rate': fee_rate,
                    'cost': amount * price * fee_rate,
                    'currency': 'USD'
                }
                
        return FakeAPI()

    def _init_markets(self) -> None:
        """
        Инициализирует markets на основе доступных пар
        """
        for pair in self._available_pairs:
            symbol = pair.split('/')[0]
            self._markets[pair] = {
                'id': symbol,
                'symbol': pair,
                'base': symbol,
                'quote': 'USD',
                'active': True,
                'type': 'spot',
                'spot': True,
                'margin': False,
                'future': False,
                'percentage': True,
                'tierBased': False,
                'taker': 0.001,
                'maker': 0.001,
                'precision': {
                    'amount': 8,
                    'price': 8,
                },
                'limits': {
                    'amount': {'min': 0.001, 'max': None},
                    'price': {'min': 0.01, 'max': None},
                    'cost': {'min': 10, 'max': None},
                },
                'info': {}
            }
        
        # Обновляем markets в fake API
        if hasattr(self._api, 'markets'):
            self._api.markets = self._markets.copy()

    def market_is_tradable(self, market: dict[str, Any]) -> bool:
        """
        Check if the market symbol is tradable by Freqtrade.
        """
        return True

    def get_fee(self, symbol: str, type: str = '', side: str = '', amount: float = 1,
                price: float = 1, taker_or_maker: str = 'maker') -> float:
        """
        Возвращает фиксированную комиссию
        """
        return 0.001  # 0.1% комиссия

    def ohlcv_candle_limit(self, timeframe: str, candle_type: str = '', since_ms: Optional[int] = None) -> int:
        """
        Возвращает лимит свечей для OHLCV запроса
        """
        return self._ft_has.get("ohlcv_candle_limit", 1000)

    def features(self, candle_type: str = '') -> Dict[str, Any]:
        """
        Возвращает features для биржи
        """
        return {
            'spot': {},
            'margin': {},
            'swap': {
                'linear': {},
                'inverse': {}
            },
            'future': {},
            'option': {}
        }

    def _get_parquet_filename(self, pair: str, timeframe: str) -> Path:
        """
        Возвращает путь к parquet файлу для пары и таймфрейма
        """
        symbol = pair.replace('/', '_')  # AAPL/USD -> AAPL_USD
        filename = f"{symbol}-{timeframe}.parquet"
        return self.data_path / filename

    def _download_stock_data_yahoo(self, symbol: str, timeframe: str, days_back: int = 365) -> pd.DataFrame:
        """
        Загружает данные акций с Yahoo Finance (бесплатное API)
        """
        try:
            # Определяем интервал для Yahoo Finance
            interval_map = {
                '1m': '1m',
                '5m': '5m', 
                '15m': '15m',
                '30m': '30m',
                '1h': '1h',
                '1d': '1d'
            }
            
            yahoo_interval = interval_map.get(timeframe, '1d')
            
            # Рассчитываем период
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            # Для внутридневных данных Yahoo ограничивает историю
            if yahoo_interval in ['1m', '5m', '15m', '30m']:
                days_back = min(days_back, 30)  # Максимум 30 дней для минутных данных
                start_date = end_date - timedelta(days=days_back)
            
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())
            
            # URL для Yahoo Finance
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            params = {
                'period1': start_timestamp,
                'period2': end_timestamp,
                'interval': yahoo_interval,
                'includePrePost': 'false',
                'events': 'div,splits'
            }
            
            logger.info(f"Downloading {symbol} data from Yahoo Finance for {timeframe}")
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if 'chart' not in data or not data['chart']['result']:
                logger.error(f"No data returned for {symbol}")
                return pd.DataFrame()
            
            result = data['chart']['result'][0]
            timestamps = result['timestamp']
            quotes = result['indicators']['quote'][0]
            
            # Создаем DataFrame
            df_data = []
            for i, ts in enumerate(timestamps):
                if (quotes['open'][i] is not None and 
                    quotes['high'][i] is not None and 
                    quotes['low'][i] is not None and 
                    quotes['close'][i] is not None and 
                    quotes['volume'][i] is not None):
                    
                    df_data.append({
                        'date': pd.to_datetime(ts, unit='s', utc=True),
                        'open': float(quotes['open'][i]),
                        'high': float(quotes['high'][i]),
                        'low': float(quotes['low'][i]),
                        'close': float(quotes['close'][i]),
                        'volume': float(quotes['volume'][i])
                    })
            
            df = pd.DataFrame(df_data)
            
            if df.empty:
                logger.warning(f"No valid data found for {symbol}")
                return df
            
            df = df.sort_values('date')
            logger.info(f"Downloaded {len(df)} candles for {symbol}")
            
            return df
            
        except Exception as e:
            logger.error(f"Error downloading data for {symbol}: {e}")
            return pd.DataFrame()

    def _load_parquet_data(self, pair: str, timeframe: str, since_ms: Optional[int] = None) -> pd.DataFrame:
        """
        Загружает данные из parquet файла
        """
        filename = self._get_parquet_filename(pair, timeframe)
        
        if not filename.exists():
            logger.warning(f"Parquet file not found: {filename}")
            return pd.DataFrame()
        
        try:
            df = pd.read_parquet(filename)
            
            # Убеждаемся что колонка date имеет правильный тип
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], utc=True)
            
            # Фильтруем по времени если указано
            if since_ms and 'date' in df.columns:
                since_datetime = pd.to_datetime(since_ms, unit='ms', utc=True)
                df = df[df['date'] >= since_datetime]
            
            logger.info(f"Loaded {len(df)} candles from {filename}")
            return df
            
        except Exception as e:
            logger.error(f"Error loading parquet file {filename}: {e}")
            return pd.DataFrame()

    def _save_parquet_data(self, df: pd.DataFrame, pair: str, timeframe: str) -> None:
        """
        Сохраняет данные в parquet файл
        """
        if df.empty:
            logger.warning(f"No data to save for {pair} {timeframe}")
            return
        
        filename = self._get_parquet_filename(pair, timeframe)
        
        try:
            # Убеждаемся что у нас правильные колонки
            required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df = df[required_columns].copy()
            
            # Сортируем по дате
            df = df.sort_values('date')
            
            # Убираем дубликаты
            df = df.drop_duplicates(subset=['date'])
            
            # Сохраняем
            df.to_parquet(filename, index=False)
            logger.info(f"Saved {len(df)} candles to {filename}")
            
        except Exception as e:
            logger.error(f"Error saving parquet file {filename}: {e}")

    def get_historic_ohlcv(self, pair: str, timeframe: str,
                          since_ms: int,
                          candle_type: CandleType,
                          is_new_pair: bool = False,
                          until_ms: int | None = None) -> pd.DataFrame:
        """
        Переопределенный метод для загрузки исторических данных
        Сначала проверяет локальные файлы, затем загружает из Yahoo Finance
        """
        logger.info(f"get_historic_ohlcv called for {pair} {timeframe}")
        
        symbol = pair.split('/')[0]
        
        # Сначала пытаемся загрузить из локального parquet файла
        df = self._load_parquet_data(pair, timeframe, since_ms)
        
        # Если данных нет или они устарели, загружаем из интернета
        should_download = False
        
        if df.empty:
            logger.info(f"No local data found for {pair}, downloading...")
            should_download = True
        else:
            # Проверяем свежесть данных (если последняя запись старше 1 дня)
            last_date = df['date'].max()
            now = pd.Timestamp.now(tz='UTC')
            if (now - last_date).days > 1:
                logger.info(f"Local data for {pair} is outdated, updating...")
                should_download = True
        
        if should_download:
            # Загружаем данные с Yahoo Finance
            new_df = self._download_stock_data_yahoo(symbol, timeframe)
            
            if not new_df.empty:
                # Объединяем с существующими данными если они есть
                if not df.empty:
                    # Объединяем и убираем дубликаты
                    combined_df = pd.concat([df, new_df], ignore_index=True)
                    combined_df = combined_df.drop_duplicates(subset=['date'])
                    combined_df = combined_df.sort_values('date')
                    df = combined_df
                else:
                    df = new_df
                
                # Сохраняем обновленные данные
                self._save_parquet_data(df, pair, timeframe)
        
        # Фильтруем по временному диапазону если нужно
        if since_ms and not df.empty:
            since_datetime = pd.to_datetime(since_ms, unit='ms', utc=True)
            df = df[df['date'] >= since_datetime]
        
        if until_ms and not df.empty:
            until_datetime = pd.to_datetime(until_ms, unit='ms', utc=True)
            df = df[df['date'] <= until_datetime]
        
        logger.info(f"Returning {len(df)} candles for {pair} {timeframe}")
        return df

    def refresh_latest_ohlcv(self, pair_list: List[Tuple[str, str, str]],
                           since_ms: Optional[int] = None,
                           cache: bool = True) -> Dict[Tuple[str, str, str], pd.DataFrame]:
        """
        Обновляет OHLCV данные для списка пар
        """
        results = {}
        
        logger.info(f"Refreshing OHLCV for {len(pair_list)} pairs")
        
        for pair, timeframe, candle_type in pair_list:
            logger.info(f"Processing {pair} {timeframe} {candle_type}")
            
            # Используем get_historic_ohlcv для получения данных
            df = self.get_historic_ohlcv(
                pair=pair,
                timeframe=timeframe, 
                since_ms=since_ms or 0,
                candle_type=CandleType(candle_type) if candle_type else CandleType.SPOT
            )
            
            if not df.empty:
                # Устанавливаем date как индекс
                df = df.set_index('date')
                results[(pair, timeframe, candle_type)] = df
                logger.info(f"Successfully loaded {len(df)} candles for {pair}")
            else:
                logger.warning(f"No data found for {pair} {timeframe}")
                
        return results

    # Методы для торговли (заглушки)
    def create_order(self, pair: str, ordertype: str, side: str, amount: float,
                    rate: float, params: dict = {}) -> Dict:
        raise OperationalException("Trading is not supported historical data")

    def cancel_order(self, order_id: str, pair: str) -> Dict:
        raise OperationalException("Trading is not supported historical data")

    def get_order(self, order_id: str, pair: str) -> Dict:
        raise OperationalException("Trading is not supported historical data")
    
    async def close(self):
        """
        Пустой async метод-заглушка для совместимости с Freqtrade Exchange.__del__
        """
        pass