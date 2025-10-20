import asyncio
import logging
import argparse
import sys
from binance.client import Client

from config import config
from announce_watcher import AnnounceWatcher
from scanner import compute_score
from executor import FuturesExecutor


logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger('main')


def create_client(testnet=True):
    return Client(config.API_KEY, config.API_SECRET, testnet=testnet)


async def on_new_listing(symbol: str):
    logger.info('New futures listing: %s', symbol)
    client = create_client(testnet=config.is_testnet)

    score = compute_score(client, symbol)
    logger.info('Pre-launch futures score for %s: %.4f', symbol, score)
    if score <= 0.01:
        logger.info('Score below threshold. Skipping trade for %s', symbol)
        return

    ex = FuturesExecutor(client)
    try:
        chosen_lev = ex.set_leverage_with_fallback(symbol, preferred=(50, 20, 10))
    except Exception as e:
        logger.error('Failed to set leverage for %s: %s', symbol, e)
        return

    res = ex.open_futures_long(symbol, config.TRADE_USDT, leverage=chosen_lev)
    if not res:
        logger.error('Open long failed for %s', symbol)
        return

    qty = res['qty']
    entry = res['entry_price']
    ex.place_take_profit_limits(symbol, qty, entry)

    async def monitor_and_arm_trailing():
        while True:
            try:
                mark = float(client.futures_mark_price(symbol=symbol)['markPrice'])
                if mark >= entry * 1.10:
                    logger.info('Reached +10%%. Arming trailing stop for %s', symbol)
                    ex.place_native_trailing_stop(symbol, qty, callback_rate=1.0)
                    break
            except Exception as e:
                logger.exception('Monitor loop error: %s', e)
            await asyncio.sleep(0.8)

    asyncio.create_task(monitor_and_arm_trailing())


async def main_loop():
    watcher = AnnounceWatcher(
        on_new_futures_listing=lambda s: asyncio.create_task(on_new_listing(s)),
        poll_interval=config.POLL_INTERVAL,
    )
    await watcher.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['testnet', 'live'], default='testnet')
    args = parser.parse_args()
    config.MODE = args.mode
    logger.info(
        'Starting bot. mode=%s testnet=%s poll_interval=%ss log_level=%s',
        config.MODE,
        'true' if config.is_testnet else 'false',
        config.POLL_INTERVAL,
        config.LOG_LEVEL,
    )
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info('Stopped by user')
