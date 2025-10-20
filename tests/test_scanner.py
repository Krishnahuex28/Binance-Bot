import types
from src.scanner import compute_score


class DummyClient:
    KLINE_INTERVAL_1MINUTE = '1m'

    def __init__(self, closes, bids=None, asks=None):
        self._closes = closes
        self._bids = bids or [[0, '1']]
        self._asks = asks or [[0, '1']]

    def get_klines(self, symbol, interval, limit):
        result = []
        for c in self._closes[-limit:]:
            result.append([0, 0, 0, 0, str(c)])
        return result

    def get_order_book(self, symbol, limit=20):
        return {'bids': self._bids, 'asks': self._asks}


def test_compute_score_increasing_prices():
    client = DummyClient([1, 2, 3, 4, 5, 6], bids=[[0, '10']], asks=[[0, '5']])
    s = compute_score(client, 'TESTUSDT')
    assert s > 0


def test_compute_score_handles_short_series():
    client = DummyClient([1], bids=[[0, '10']], asks=[[0, '10']])
    s = compute_score(client, 'TESTUSDT')
    assert s == 0.0


