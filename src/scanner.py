import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger('scanner')


def compute_score(client: Client, symbol: str) -> float:
    """
    Simple rule-based score using 1m close momentum and order book imbalance.
    Returns 0.0 on error or no signal.
    """
    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=6)
        closes = [float(k[4]) for k in klines]
        if len(closes) < 2:
            return 0.0
        avg_prev = sum(closes[:-1]) / max(1, len(closes) - 1)
        momentum = (closes[-1] / avg_prev) - 1

        depth = client.get_order_book(symbol=symbol, limit=20)
        bid_depth = sum(float(b[1]) for b in depth.get('bids', []))
        ask_depth = sum(float(a[1]) for a in depth.get('asks', []))
        denom = max(1.0, bid_depth + ask_depth)
        imbalance = (bid_depth - ask_depth) / denom

        score = 0.6 * momentum + 0.4 * imbalance
        return score
    except BinanceAPIException as e:
        logger.error('Binance API error in scanner: %s', e)
        return 0.0
    except Exception as e:
        logger.exception('Scanner unexpected error: %s', e)
        return 0.0


