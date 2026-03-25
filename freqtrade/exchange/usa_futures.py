
from freqtrade.exchange.fake_exchange import Fake_Exchange



class USA_Futures(Fake_Exchange):
    """
    USA_Futures Exchange class для работы с историческими данными акций
    """

    @property
    def name(self) -> str:
        return "USA_Futures"
