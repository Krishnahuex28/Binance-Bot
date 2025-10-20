import asyncio
import logging
import argparse
import sys
from datetime import datetime, timezone
from binance.client import Client

from config import config
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

    ex = FuturesExecutor(client)
    try:
        chosen_lev = ex.set_leverage(symbol, 10)
    except Exception as e:
        logger.error('Failed to set leverage for %s: %s', symbol, e)
        return

    res = ex.open_futures_long(symbol, config.TRADE_USDT, leverage=chosen_lev)
    if not res:
        logger.error('Open long failed for %s', symbol)
        return

    qty = res['qty']
    entry = res['entry_price']

    async def monitor_and_arm_trailing():
        while True:
            try:
                mark = float(client.futures_mark_price(symbol=symbol)['markPrice'])
                try:
                    change_pct = ((mark / entry) - 1.0) * 100.0 if entry else 0.0
                except Exception:
                    change_pct = 0.0
                logger.info('Price tick %s: mark=%.8f entry=%.8f (%.2f%%)', symbol, mark, entry, change_pct)
                if mark >= entry * 1.10:
                    logger.info('Reached +10%%. Arming trailing stop for %s', symbol)
                    ex.place_native_trailing_stop(symbol, qty, callback_rate=1.0)
                    break
            except Exception as e:
                logger.exception('Monitor loop error: %s', e)
            await asyncio.sleep(1.0)

    async def monitor_until_close():
        try:
            hedge = False
            try:
                hedge = FuturesExecutor(client).is_hedge_mode()
            except Exception:
                hedge = False
            while True:
                pos_list = client.futures_position_information(symbol=symbol)
                remaining = 0.0
                for p in pos_list:
                    side = p.get('positionSide') or 'BOTH'
                    amt = float(p.get('positionAmt') or 0.0)
                    if hedge:
                        if side == 'LONG':
                            remaining = abs(amt)
                            break
                    else:
                        remaining = abs(amt)
                        break
                mark = float(client.futures_mark_price(symbol=symbol)['markPrice'])
                try:
                    change_pct = ((mark / entry) - 1.0) * 100.0 if entry else 0.0
                except Exception:
                    change_pct = 0.0
                logger.info('Position %s: remaining=%.8f mark=%.8f entry=%.8f (%.2f%%)', symbol, remaining, mark, entry, change_pct)
                if remaining <= 1e-10:
                    logger.info('Position closed for %s. Exiting monitor.', symbol)
                    break
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.exception('Monitor until close error: %s', e)

    await monitor_and_arm_trailing()
    await monitor_until_close()


async def execute_immediate_trade(client: Client, symbol: str, leverage: int):
    ex = FuturesExecutor(client)
    res = ex.open_futures_long(symbol, config.TRADE_USDT, leverage=leverage)
    if not res:
        logger.error('Open long failed for %s', symbol)
        return
    qty = res['qty']
    entry = res['entry_price']

    async def monitor_and_arm_trailing():
        while True:
            try:
                mark = float(client.futures_mark_price(symbol=symbol)['markPrice'])
                try:
                    change_pct = ((mark / entry) - 1.0) * 100.0 if entry else 0.0
                except Exception:
                    change_pct = 0.0
                logger.info('Price tick %s: mark=%.8f entry=%.8f (%.2f%%)', symbol, mark, entry, change_pct)
                if mark >= entry * 1.10:
                    logger.info('Reached +10%%. Arming trailing stop for %s', symbol)
                    ex.place_native_trailing_stop(symbol, qty, callback_rate=1.0)
                    break
            except Exception as e:
                logger.exception('Monitor loop error: %s', e)
            await asyncio.sleep(1.0)

    async def monitor_until_close():
        try:
            hedge = False
            try:
                hedge = FuturesExecutor(client).is_hedge_mode()
            except Exception:
                hedge = False
            while True:
                pos_list = client.futures_position_information(symbol=symbol)
                remaining = 0.0
                for p in pos_list:
                    side = p.get('positionSide') or 'BOTH'
                    amt = float(p.get('positionAmt') or 0.0)
                    if hedge:
                        if side == 'LONG':
                            remaining = abs(amt)
                            break
                    else:
                        remaining = abs(amt)
                        break
                mark = float(client.futures_mark_price(symbol=symbol)['markPrice'])
                try:
                    change_pct = ((mark / entry) - 1.0) * 100.0 if entry else 0.0
                except Exception:
                    change_pct = 0.0
                logger.info('Position %s: remaining=%.8f mark=%.8f entry=%.8f (%.2f%%)', symbol, remaining, mark, entry, change_pct)
                if remaining <= 1e-10:
                    logger.info('Position closed for %s. Exiting monitor.', symbol)
                    break
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.exception('Monitor until close error: %s', e)

    await monitor_and_arm_trailing()
    await monitor_until_close()


async def main_loop():
    raise SystemExit('Watcher mode has been removed. Use --symbol and --at-utc for manual execution.')


def _parse_utc_datetime(s: str) -> datetime:
    """Parse a UTC datetime string. Accepts formats like 'YYYY-MM-DD HH:MM' or ISO. Assumes UTC if tz missing."""
    dt = None
    try:
        # Try common "YYYY-MM-DD HH:MM" without seconds
        if 'T' not in s and len(s) >= 16 and s[10] == ' ':
            dt = datetime.fromisoformat(s + "+00:00")
        else:
            # General ISO; replace trailing Z with +00:00
            iso = s.replace('Z', '+00:00')
            dt = datetime.fromisoformat(iso)
    except Exception:
        # Fallback: try plain date-time without tz
        try:
            dt = datetime.strptime(s, '%Y-%m-%d %H:%M')
        except Exception:
            raise ValueError(f"Unrecognized datetime format: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def manual_flow(symbol: str, at_utc: str | None):
    # Normalize symbol (allow coin like BTC -> BTCUSDT)
    sym = symbol.upper()
    if not sym.endswith('USDT'):
        sym = sym + 'USDT'

    client = create_client(testnet=config.is_testnet)
    ex = FuturesExecutor(client)
    # Pre-set leverage ahead of time to avoid delay at the exact second (fixed 10x)
    try:
        chosen_lev = ex.set_leverage(sym, 10)
    except Exception as e:
        logger.error('Failed to set leverage for %s: %s', sym, e)
        return

    # Detect and log position mode (Hedge vs One-way)
    try:
        hedge = ex.is_hedge_mode()
        logger.info('Position mode detected: %s', 'Hedge' if hedge else 'One-way')
    except Exception:
        logger.info('Position mode detection failed; proceeding')

    dt = _parse_utc_datetime(at_utc) if at_utc else None
    now = datetime.now(tz=timezone.utc)
    delay = (dt - now).total_seconds() if dt else 0
    if delay > 0:
        logger.info('Manual mode: waiting until %s UTC (%.1fs) for %s', dt.isoformat(), delay, sym)
        await asyncio.sleep(delay)

    await execute_immediate_trade(client, sym, chosen_lev)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['testnet', 'live'], default='testnet')
    parser.add_argument('--symbol', help='Manual symbol to trade (e.g., BTCUSDT or BTC)')
    parser.add_argument('--at-utc', help='UTC datetime to execute, e.g., "2025-10-11 08:00" or ISO 8601')
    args = parser.parse_args()
    if args.symbol and not args.at_utc:
        parser.error('--at-utc is required when --symbol is provided')
    config.MODE = args.mode
    logger.info(
        'Starting bot. mode=%s testnet=%s poll_interval=%ss log_level=%s',
        config.MODE,
        'true' if config.is_testnet else 'false',
        config.POLL_INTERVAL,
        config.LOG_LEVEL,
    )
    try:
        if args.symbol:
            asyncio.run(manual_flow(args.symbol, args.at_utc))
        else:
            raise SystemExit('Manual-only mode: provide --symbol and --at-utc')
    except KeyboardInterrupt:
        logger.info('Stopped by user')
