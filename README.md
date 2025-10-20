# Binance Futures Launch Trader Bot
Automated trading bot for newly listed Binance Futures pairs. Manual-only: you provide the coin and exact UTC launch time. The bot sets 10x leverage ahead of time and places a MARKET order at the specified second, then arms a trailing stop after +10%.

## Setup
1. Clone repo
2. Install dependencies
   
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment
   - `BINANCE_API_KEY` and `BINANCE_API_SECRET`
   - `USE_TESTNET=true` for testnet (or run with `--mode testnet`)
   - Optional: `TRADE_USDT` (amount of USDT to deploy; default is 1)

## Run for a new futures listing
You must provide the symbol and the exact UTC start time of trading.

- Live example (SUI at 2025-10-11 08:00 UTC):

  ```bash
  python -m src.main --mode live --symbol SUI --at-utc "2025-10-11 08:00"
  ```

- Testnet example (BTC, exact time):

  ```bash
  python -m src.main --mode testnet --symbol BTC --at-utc "2025-10-11 08:00"
  ```

### Behavior
- Leverage: fixed to 10x, set in advance to avoid delays at launch.
- Entry: MARKET BUY at the exact provided UTC second.
- Exits: no take-profits are placed; a native trailing stop is armed once mark price reaches +10% from entry (1.0% callback).

### Notes
- Symbol normalization: `BTC` will be treated as `BTCUSDT` automatically.
- Time must be UTC. Ensure your system clock is synced (Windows: Date & Time settings → Sync now) to minimize drift.
- Use small `TRADE_USDT` on testnet first to validate behavior.

## Environment variables (.env)
```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
USE_TESTNET=true
TRADE_USDT=5
```

## Troubleshooting
- "Manual-only mode: provide --symbol and --at-utc": both flags are required.
- API errors: verify keys and that futures are enabled on the account/testnet.
