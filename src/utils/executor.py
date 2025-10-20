import os
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv

load_dotenv()

class FuturesExecutor:
    def __init__(self):
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        use_testnet = os.getenv('USE_TESTNET', 'True').lower() == 'true'

        self.client = Client(api_key, api_secret, testnet=use_testnet)
        self.trade_usdt = float(os.getenv('TRADE_USDT', 50))

    def set_leverage(self, symbol):
        for lev in [50, 20, 10]:
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=lev)
                print(f'Leverage set to {lev}x for {symbol}')
                return lev
            except Exception as e:
                print(f'Leverage {lev}x failed: {e}')
        return 10

    def open_trade(self, symbol):
        lev = self.set_leverage(symbol)
        price = float(self.client.futures_mark_price(symbol=symbol)['markPrice'])
        qty = round(self.trade_usdt * lev / price, 3)
        print(f'Opening {symbol} LONG with {qty} qty @ {lev}x')
        self.client.futures_create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)

    def run(self):
        # Placeholder: detect new futures listing symbol here
        symbol = 'BTCUSDT'
        self.open_trade(symbol)
