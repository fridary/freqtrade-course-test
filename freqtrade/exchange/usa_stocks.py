
from freqtrade.exchange.fake_exchange import Fake_Exchange



class USA_Stocks(Fake_Exchange):
    """
    USA_Stocks Exchange class для работы с историческими данными акций
    """

    @property
    def name(self) -> str:
        return "USA_Stocks"
