import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    API_KEY: str = os.getenv('BINANCE_API_KEY', '')
    API_SECRET: str = os.getenv('BINANCE_API_SECRET', '')
    MODE: str = os.getenv('MODE', 'testnet')
    TRADE_USDT: float = float(os.getenv('TRADE_USDT', '50'))
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    @property
    def is_testnet(self) -> bool:
        # Respect USE_TESTNET if provided, otherwise fall back to MODE
        use_testnet_env = os.getenv('USE_TESTNET')
        if use_testnet_env is not None:
            return use_testnet_env.lower() == 'true'
        return self.MODE.lower() == 'testnet'


config = Config()


