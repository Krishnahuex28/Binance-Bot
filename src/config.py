import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    API_KEY: str = os.getenv('BINANCE_API_KEY', '')
    API_SECRET: str = os.getenv('BINANCE_API_SECRET', '')
    TRADE_USDT: float = float(os.getenv('TRADE_USDT', '1'))
    LEVERAGE: int = int(os.getenv('LEVERAGE', '10'))
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    POLL_INTERVAL: int = int(os.getenv('POLL_INTERVAL', '20'))
    ANNOUNCE_MAX_AGE_MINUTES: int = int(os.getenv('ANNOUNCE_MAX_AGE_MINUTES', '120'))
    # Risk controls
    STOP_LOSS_PCT: float = float(os.getenv('STOP_LOSS_PCT', '0.01'))  # 1% below entry
    TRAILING_ACTIVATION_PCT: float = float(os.getenv('TRAILING_ACTIVATION_PCT', '0.10'))  # activate at +10%
    TRAILING_CALLBACK_PCT: float = float(os.getenv('TRAILING_CALLBACK_PCT', '1.0'))  # 1% callback


config = Config()


