import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger('executor')


class FuturesExecutor:
    def __init__(self, client: Client):
        self.client = client

    def set_leverage_with_fallback(self, symbol: str, preferred=(50, 20, 10)) -> int:
        for lev in preferred:
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=lev)
                logger.info('Leverage set to %dx for %s', lev, symbol)
                return lev
            except BinanceAPIException as e:
                logger.warning('Failed leverage %dx for %s: %s', lev, symbol, e)
            except Exception as e:
                logger.exception('Unexpected error setting leverage %dx for %s: %s', lev, symbol, e)
        raise RuntimeError(f'Could not set leverage for {symbol}')

    def open_futures_long(self, symbol: str, usdt_capital: float, leverage: int) -> dict | None:
        try:
            try:
                mark = float(self.client.futures_mark_price(symbol=symbol)['markPrice'])
            except Exception:
                mark = float(self.client.get_symbol_ticker(symbol=symbol)['price'])

            notional = usdt_capital * leverage
            qty = round(notional / mark, 6)

            resp = self.client.futures_create_order(
                symbol=symbol,
                side='BUY',
                type='MARKET',
                quantity=qty
            )
            entry_price = float(resp.get('avgPrice') or mark)
            logger.info('Opened LONG: %s qty=%s entry=%.8f', symbol, qty, entry_price)
            return {'qty': qty, 'entry_price': entry_price, 'raw': resp}
        except BinanceAPIException as e:
            logger.error('Futures buy failed: %s', e)
            return None
        except Exception as e:
            logger.exception('Unexpected open error: %s', e)
            return None

    def place_take_profit_limits(self, symbol: str, qty: float, entry_price: float, tp_pcts=(0.03, 0.05)):
        orders = []
        splits = (0.5, 0.5)
        for pct, part in zip(tp_pcts, splits):
            price = round(entry_price * (1 + pct), 8)
            q = round(qty * part, 6)
            try:
                r = self.client.futures_create_order(
                    symbol=symbol,
                    side='SELL',
                    type='LIMIT',
                    timeInForce='GTC',
                    price=str(price),
                    quantity=str(q),
                    reduceOnly='true'
                )
                orders.append(r)
            except Exception as e:
                logger.exception('TP order failed: %s', e)
        return orders

    def place_native_trailing_stop(self, symbol: str, qty: float, callback_rate: float = 1.0):
        try:
            resp = self.client.futures_create_order(
                symbol=symbol,
                side='SELL',
                type='TRAILING_STOP_MARKET',
                quantity=qty,
                callbackRate=str(callback_rate),
                reduceOnly='true'
            )
            logger.info('Placed trailing stop: %s', resp)
            return resp
        except BinanceAPIException as e:
            logger.warning('Trailing stop failed: %s', e)
            return None
        except Exception as e:
            logger.exception('Unexpected trailing stop error: %s', e)
            return None


