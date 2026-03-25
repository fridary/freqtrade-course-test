
from freqtrade.exchange.fake_exchange import Fake_Exchange



class Forex(Fake_Exchange):
    """
    Forex class для работы с историческими данными акций
    """

    @property
    def name(self) -> str:
        return "Forex"
