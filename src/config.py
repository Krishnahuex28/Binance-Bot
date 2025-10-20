import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    API_KEY: str = os.getenv('BINANCE_API_KEY', '')
    API_SECRET: str = os.getenv('BINANCE_API_SECRET', '')
    MODE: str = os.getenv('MODE', 'testnet')
    TRADE_USDT: float = float(os.getenv('TRADE_USDT', '1'))
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    POLL_INTERVAL: int = int(os.getenv('POLL_INTERVAL', '20'))
    ANNOUNCE_MAX_AGE_MINUTES: int = int(os.getenv('ANNOUNCE_MAX_AGE_MINUTES', '120'))

    @property
    def is_testnet(self) -> bool:
        # Respect USE_TESTNET if provided, otherwise fall back to MODE
        use_testnet_env = os.getenv('USE_TESTNET')
        if use_testnet_env is not None:
            return use_testnet_env.lower() == 'true'
        return self.MODE.lower() == 'testnet'


config = Config()


