import asyncio
import logging
import argparse
import sys
from datetime import datetime, timezone
from binance.client import Client
from binance.exceptions import BinanceAPIException

from src.config import config
from src.executor import FuturesExecutor


logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger('main')


def create_client():
    return Client(config.API_KEY, config.API_SECRET, testnet=False)


async def on_new_listing(symbol: str):
    logger.info('New futures listing: %s', symbol)
    client = create_client()

    ex = FuturesExecutor(client)
    try:
        chosen_lev = ex.set_leverage(symbol, config.LEVERAGE)
    except Exception as e:
        logger.error('Failed to set leverage for %s: %s', symbol, e)
        return

    res = ex.open_futures_long(symbol, config.TRADE_USDT, leverage=chosen_lev)
    if not res:
        logger.error('Open long failed for %s', symbol)
        return

    qty = res['qty']
    entry = res['entry_price']

    # Place trailing stop immediately with server-side activation using env percentages
    try:
        activation = entry * (1.0 + config.TRAILING_ACTIVATION_PCT)
        ex.place_native_trailing_stop(symbol, qty, callback_rate=config.TRAILING_CALLBACK_PCT, activation_price=activation)
        logger.info('Placed server-side trailing stop for %s with activation %.8f (callback %.3f%%)', symbol, activation, config.TRAILING_CALLBACK_PCT)
    except Exception as e:
        logger.exception('Failed to place server-side trailing stop: %s', e)

    # Place stop-loss at configured pct below entry (MARK_PRICE, closePosition)
    try:
        sl = entry * (1.0 - config.STOP_LOSS_PCT)
        ex.place_stop_loss(symbol, qty, stop_price=sl)
        logger.info('Placed stop-loss for %s at %.8f', symbol, sl)
    except Exception as e:
        logger.exception('Failed to place stop-loss: %s', e)

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

    await monitor_until_close()


async def execute_immediate_trade(client: Client, symbol: str, leverage: int):
    ex = FuturesExecutor(client)

    # Set leverage with quick retries in case the symbol is not yet active at the exact second
    lev_set = False
    for attempt in range(15):  # up to ~15s
        try:
            ex.set_leverage(symbol, leverage)
            lev_set = True
            break
        except BinanceAPIException as e:
            code = getattr(e, 'code', None)
            if code == -1121:  # Invalid symbol (not active yet)
                await asyncio.sleep(1.0)
                continue
            raise
        except Exception:
            await asyncio.sleep(1.0)
            continue
    if not lev_set:
        logger.error('Could not set leverage for %s after retries', symbol)
        return

    # Open market long with retries if symbol just became active
    res = None
    for attempt in range(15):
        res = ex.open_futures_long(symbol, config.TRADE_USDT, leverage=leverage)
        if res:
            break
        await asyncio.sleep(1.0)
    if not res:
        logger.error('Open long failed for %s after retries', symbol)
        return
    qty = res['qty']
    entry = res['entry_price']

    # Place trailing stop immediately with server-side activation using env percentages
    try:
        activation = entry * (1.0 + config.TRAILING_ACTIVATION_PCT)
        ex.place_native_trailing_stop(symbol, qty, callback_rate=config.TRAILING_CALLBACK_PCT, activation_price=activation)
        logger.info('Placed server-side trailing stop for %s with activation %.8f (callback %.3f%%)', symbol, activation, config.TRAILING_CALLBACK_PCT)
    except Exception as e:
        logger.exception('Failed to place server-side trailing stop: %s', e)

    # Place stop-loss at configured pct below entry (MARK_PRICE, closePosition)
    try:
        sl = entry * (1.0 - config.STOP_LOSS_PCT)
        ex.place_stop_loss(symbol, qty, stop_price=sl)
        logger.info('Placed stop-loss for %s at %.8f', symbol, sl)
    except Exception as e:
        logger.exception('Failed to place stop-loss: %s', e)

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

    client = create_client()
    ex = FuturesExecutor(client)

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
        while True:
            now = datetime.now(tz=timezone.utc)
            remaining = int((dt - now).total_seconds())
            if remaining <= 0:
                break
            hrs = remaining // 3600
            mins = (remaining % 3600) // 60
            secs = remaining % 60
            logger.info('T-minus %02d:%02d:%02d for %s', hrs, mins, secs, sym)
            await asyncio.sleep(1.0)

    await execute_immediate_trade(client, sym, config.LEVERAGE)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', help='Manual symbol to trade (e.g., BTCUSDT or BTC)')
    parser.add_argument('--at-utc', help='UTC datetime to execute, e.g., "2025-10-11 08:00" or ISO 8601')
    args = parser.parse_args()
    if args.symbol and not args.at_utc:
        parser.error('--at-utc is required when --symbol is provided')
    logger.info(
        'Starting bot (live). poll_interval=%ss log_level=%s',
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
