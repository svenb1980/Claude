# Aandelen-analyzer

A self-hosted tool that reads your DEGIRO exports, analyses each holding against its market
history, labels it Verkopen / Houden / Bijkopen with the reasons shown, and keeps a dividend
calendar. The interface is in Dutch. It cannot log in to DEGIRO or place orders.

> **Not financial advice.** Signals are the output of rules you can inspect and change. The default
> weights and thresholds are starting points, not recommendations, and have not been shown to
> predict returns. Use the Backtest page to see how they behaved on your own holdings.

## Start with Docker

```bash
docker compose up -d --build
```

Open <http://127.0.0.1:8000>. Stop it with `docker compose down`; your data stays in the volume.

## Import your portfolio

In DEGIRO, export these as CSV over the longest period available, then upload each one on **Importeren**:

| Export | Supplies |
|---|---|
| Transactions | Buys and sells, cost basis, realised result |
| Account Statement | Dividends, withholding tax, FX, fees |

You see a preview before anything is saved. Overlapping exports are safe: rows already stored are skipped.

After the import, open **Instellingen** and check the ISIN-to-ticker table, especially for European
stocks. Yahoo may pick another listing of the same company; correct it there if needed.

## How the signals work

Each holding gets a 0-100 score on six factors, combined using weights you can edit:

| Factor | Inputs |
|---|---|
| Trend | Price vs 200-day average, 50-day vs 200-day, 12-month slope |
| Momentum | 3/6/12-month return, 12-month return vs benchmark, RSI |
| Risk | Volatility, largest fall over 5 years, Sharpe ratio, beta |
| Valuation | P/E (absolute), dividend yield vs its own past 5 years |
| Quality and dividend | Payout ratio, dividend growth streak, margin, debt |
| Portfolio fit | Position weight, sector share, foreign currency share |

- Missing data isn't scored as neutral. It's left out and lowers the *datadekking*. Below the minimum
  you get **Onvoldoende data** instead of a label.
- A position above the maximum weight never gets Bijkopen.
- ETFs and funds skip the company-based factors.

## Known limitations

- **DEGIRO format:** DEGIRO publishes no export specification, so the parser is based on public
  descriptions and has only been tested on made-up files. Check the preview on your first import.
- **Corporate actions:** spin-offs, ISIN changes and other events that appear in exports in unusual
  ways are not specially handled and can distort a position. The dashboard warns if a sale exceeds the
  shares known to be held.
- **Market data:** Yahoo Finance via `yfinance` is unofficial and can break or have gaps, especially
  for European stocks. The last good data stays in use, and errors appear on **Instellingen**. To use
  another source, implement `MarketDataProvider` in `app/market/provider.py`.
- **Dividend forecasts:** unannounced dividends repeat last year's pattern, and free data rarely has
  payment dates. Every item is marked as confirmed or estimated.
- **Backtest:** survivorship bias (only stocks you still own), price factors only, local currency,
  no tax. The page lists these limits with the results.
- **Time zones:** beta and relative strength compare stocks with a European-listed benchmark by
  calendar day, which understates beta for US stocks.

## Your data

Everything stays in the `stock_data` Docker volume: the SQLite database and uploads in progress.

The named volume is deliberate. This repository sits in a OneDrive folder, and a bind mount would sync
your financial data there. `.gitignore` also blocks CSV and database files.

The only outside connection is to Yahoo Finance, which receives ticker symbols and ISINs of your
holdings, but no amounts or personal details.

## Move to a Raspberry Pi

Needs a Pi 4 or 5 with 64-bit Raspberry Pi OS and Docker installed. The arm64 build has not been run
on real hardware yet.

**1. Back up the volume on the current machine:**

```bash
docker run --rm -v stock-analyzer_stock_data:/data -v "$(pwd):/backup" alpine tar czf /backup/stock-data.tgz -C /data .
```

Run this outside the OneDrive folder, because the backup contains your financial data.

**2. Set a password before opening it to your network.** On the Pi, create `.env` next to
`docker-compose.yml`:

```ini
BIND_ADDRESS=0.0.0.0
PORTFOLIO_PASSWORD=choose-a-long-password
```

Traffic on your network is plain HTTP. Don't forward this port to the internet.

**3. Create the volume, restore and start, on the Pi:**

```bash
docker compose up --no-start
docker run --rm -v stock-analyzer_stock_data:/data -v "$(pwd):/backup" alpine sh -c "tar xzf /backup/stock-data.tgz -C /data && chown -R 1000:1000 /data"
docker compose up -d --build
```

To build for the Pi from another machine:

```bash
docker buildx build --platform linux/arm64 -t stock-analyzer:latest .
```

## Development

Without Docker, set `DATA_DIR` to a folder outside OneDrive first:

```bash
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```

All test data is made up. Never add a real export to the repository.

| Path | Purpose |
|---|---|
| `app/importers/` | CSV parsing and storing |
| `app/portfolio/positions.py` | Positions, average cost, result |
| `app/market/` | Data source interface, Yahoo adapter, nightly refresh |
| `app/analysis/` | Metrics, scoring, backtest |
| `app/dividends/calendar.py` | Received and expected dividends |
| `app/i18n/nl.py` | All interface text |
| `app/web/` | Routes, templates, CSS, charts |
