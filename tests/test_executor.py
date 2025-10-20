from src.executor import FuturesExecutor


class DummyClient:
    def __init__(self):
        self.calls = []
        self._lev_attempts = []

    def futures_change_leverage(self, symbol, leverage):
        self._lev_attempts.append(leverage)
        if leverage in (50, 20):
            raise Exception('fail')
        return {'leverage': leverage}

    def futures_mark_price(self, symbol):
        return {'markPrice': '100.0'}

    def futures_create_order(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs['type'] == 'MARKET' and kwargs['side'] == 'BUY':
            return {'avgPrice': '100.0'}
        return {'ok': True}

    def get_symbol_ticker(self, symbol):
        return {'price': '100.0'}


def test_set_leverage_with_fallback_works_on_third():
    ex = FuturesExecutor(DummyClient())
    lev = ex.set_leverage_with_fallback('TESTUSDT', preferred=(50, 20, 10))
    assert lev == 10


def test_open_futures_long_places_market_buy():
    dc = DummyClient()
    ex = FuturesExecutor(dc)
    res = ex.open_futures_long('TESTUSDT', usdt_capital=50, leverage=10)
    assert res['qty'] > 0
    # First call should be MARKET BUY
    assert any(c['type'] == 'MARKET' and c['side'] == 'BUY' for c in dc.calls)


def test_place_take_profit_limits_creates_reduce_only_orders():
    dc = DummyClient()
    ex = FuturesExecutor(dc)
    ex.place_take_profit_limits('TESTUSDT', qty=1.0, entry_price=100.0)
    assert any(c.get('reduceOnly') == 'true' for c in dc.calls)


