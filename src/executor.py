import logging
from decimal import Decimal, ROUND_DOWN
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger('executor')


class FuturesExecutor:
    def __init__(self, client: Client):
        self.client = client

    def is_hedge_mode(self) -> bool:
        try:
            resp = self.client.futures_get_position_mode()
            dual = resp.get('dualSidePosition')
            # dualSidePosition may be bool or string
            return True if dual is True or (isinstance(dual, str) and dual.lower() == 'true') else False
        except BinanceAPIException as e:
            logger.warning('Unable to read position mode (assuming one-way): %s', e)
            return False
        except Exception as e:
            logger.warning('Error determining position mode (assuming one-way): %s', e)
            return False

    def set_leverage(self, symbol: str, leverage: int) -> int:
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info('Leverage set to %dx for %s', leverage, symbol)
            return leverage
        except BinanceAPIException as e:
            logger.error('Failed to set leverage %dx for %s: %s', leverage, symbol, e)
            raise
        except Exception as e:
            logger.exception('Unexpected error setting leverage %dx for %s: %s', leverage, symbol, e)
            raise

    def open_futures_long(self, symbol: str, usdt_capital: float, leverage: int) -> dict | None:
        try:
            try:
                mark = float(self.client.futures_mark_price(symbol=symbol)['markPrice'])
            except Exception:
                mark = float(self.client.get_symbol_ticker(symbol=symbol)['price'])

            notional = usdt_capital * leverage
            qty_raw = notional / mark

            # Fetch exchange info to respect market lot size/filters
            info = self.client.futures_exchange_info()
            sym_info = next((s for s in info.get('symbols', []) if s.get('symbol') == symbol), None)
            if not sym_info:
                logger.error('Symbol info not found for %s', symbol)
                return None

            # Prefer MARKET_LOT_SIZE; fallback to LOT_SIZE
            filters = sym_info.get('filters', [])
            market_lot = next((f for f in filters if f.get('filterType') == 'MARKET_LOT_SIZE'), None)
            lot = next((f for f in filters if f.get('filterType') == 'LOT_SIZE'), None)
            qty_filter = market_lot or lot or {}

            step_size = qty_filter.get('stepSize') or '0.001'
            min_qty = qty_filter.get('minQty') or '0.0'

            # Some futures symbols also enforce notional minimum
            min_notional = None
            notional_filter = next((f for f in filters if f.get('filterType') in ('MIN_NOTIONAL', 'NOTIONAL')), None)
            if notional_filter:
                min_notional = float(notional_filter.get('minNotional') or notional_filter.get('notional', 0.0))

            def floor_to_step(value: float, step: str) -> float:
                dv = Decimal(str(value))
                ds = Decimal(step)
                if ds == 0:
                    return float(value)
                return float((dv // ds) * ds)

            qty = floor_to_step(qty_raw, step_size)

            if qty <= 0.0:
                logger.error('Computed quantity is zero. Try increasing TRADE_USDT or leverage. qty_raw=%.10f step=%s', qty_raw, step_size)
                return None

            if float(qty) < float(min_qty):
                logger.error('Quantity %.10f below minQty %s for %s. Increase TRADE_USDT.', qty, min_qty, symbol)
                return None

            if min_notional is not None and (qty * mark) < min_notional:
                logger.error('Notional %.8f below minNotional %.8f for %s. Increase TRADE_USDT.', qty * mark, min_notional, symbol)
                return None

            hedge = self.is_hedge_mode()
            order_params = {
                'symbol': symbol,
                'side': 'BUY',
                'type': 'MARKET',
                'quantity': str(qty),
            }
            if hedge:
                order_params['positionSide'] = 'LONG'

            try:
                resp = self.client.futures_create_order(**order_params)
            except BinanceAPIException as e:
                # If user is in hedge mode and we didn't set positionSide, retry
                if getattr(e, 'code', None) == -4061 and not hedge:
                    order_params['positionSide'] = 'LONG'
                    resp = self.client.futures_create_order(**order_params)
                else:
                    raise
            # Use avgPrice if present and > 0, otherwise fall back to current mark
            entry_price = mark
            try:
                ap = resp.get('avgPrice')
                if ap is not None and float(ap) > 0:
                    entry_price = float(ap)
            except Exception:
                entry_price = mark
            logger.info('Opened LONG: %s qty=%s entry=%.8f', symbol, qty, entry_price)
            return {'qty': qty, 'entry_price': entry_price, 'raw': resp}
        except BinanceAPIException as e:
            logger.error('Futures buy failed: %s', e)
            return None
        except Exception as e:
            logger.exception('Unexpected open error: %s', e)
            return None

    def place_native_trailing_stop(self, symbol: str, qty: float, callback_rate: float = 1.0):
        try:
            hedge = self.is_hedge_mode()
            params = {
                'symbol': symbol,
                'side': 'SELL',
                'type': 'TRAILING_STOP_MARKET',
                'quantity': str(qty),
                'callbackRate': str(callback_rate),
            }
            if hedge:
                params['positionSide'] = 'LONG'
            try:
                # Some accounts/symbols reject reduceOnly for TSM; send without reduceOnly, then retry with reduceOnly=false if needed
                resp = self.client.futures_create_order(**params)
            except BinanceAPIException as e:
                if getattr(e, 'code', None) == -1106 and 'reduceonly' in str(e).lower():
                    params['reduceOnly'] = 'false'
                    resp = self.client.futures_create_order(**params)
                else:
                    raise
            logger.info('Placed trailing stop: %s', resp)
            return resp
        except BinanceAPIException as e:
            logger.warning('Trailing stop failed: %s', e)
            return None
        except Exception as e:
            logger.exception('Unexpected trailing stop error: %s', e)
            return None


