# Aandelen-analyzer

A self-hosted, multi-user tool that reads DEGIRO exports, analyses each holding against its market
history, labels it Verkopen / Houden / Bijkopen with the reasons shown, ranks stocks outside your
portfolio, draws sell levels on share charts, and keeps a dividend calendar. The interface is in
Dutch. It cannot log in to DEGIRO or place orders. An optional page lets you ask Claude about terms,
market history and the considerations around buying and selling.

> **Not financial advice.** Signals, buy candidates and sell levels are the output of rules you can
> inspect. The defaults are starting points, not recommendations, and have not been shown to predict
> returns. Use the Backtest page and the evidence beside each level to see how they behaved.

## Start with Docker

```bash
docker compose up -d --build
```

Open <http://127.0.0.1:8000> and create the first account, which becomes the administrator. Stop it
with `docker compose down`; your data stays in the volume.

## Accounts and portfolios

- Each person has their own login and sees only their own portfolios and settings. The administrator
  creates accounts under **Account**, with a temporary password the person then changes.
- Each account can hold several portfolios, each with its own imports, signals, dividends and backtest.
  Switch at the top of the page, and check the portfolio name on **Importeren** before uploading.
- Market data is shared. A ticker correction by one user applies to everyone who holds that stock.
- A database from the single-user version is migrated at start-up: its imports move into the first
  portfolio of the first account you create.

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

## Compared with the market

**Overzicht** compares the portfolio, or any one of your stocks, with the AEX, Europe 50 and USA 500 over a
period you choose, with a table per period and per stock.

- The portfolio line is a time-weighted return including costs, so buying or selling doesn't move it.
- Everything is in EUR and excludes dividends on both sides, because these are price indices. The USA 500 is
  converted from USD, so it includes the currency effect.
- Europe 50 is the Euro Stoxx 50 (eurozone only). The STOXX Europe 50, with the UK and Switzerland, isn't on
  Yahoo. USA 500 is the S&P 500. They're set in `MARKETS` in `app/analysis/comparison.py`.
- Trades far from the closing price are treated as splits or ISIN changes and don't count as gain or loss.
  The page says how many.

## Buy candidates

**Koopkandidaten** ranks about 1,250 stocks outside the selected portfolio, on company results, dividend,
valuation, tradability (bid-ask spread and daily turnover), momentum, trend, risk, and how much a stock adds
to your portfolio's spread over sectors and countries. Presets change the weights. Each stock shows the
numbers behind its score.

- The list (`app/market/universe.json`) holds the AEX, AMX, BEL 20, DAX, MDAX, CAC 40, FTSE 100, FTSE 250,
  SMI, IBEX 35, FTSE MIB, OMX 30/25, OBX and S&P 500 as they are now. It is not literally the STOXX Europe
  600, because no reliable free list of that index could be retrieved. Refresh it with
  `python scripts/build_universe.py`; administrators can add tickers under **Instellingen**.
- About 200 stocks refresh per night, oldest first, so a first full pass takes about six nights and data can
  be several days old. Yahoo rate limits end a run early, and the next run continues.
- **The ranking has not been tested.** Free historical company data is too thin to backtest it, so it's a
  starting point for your own research.

## Sell levels and day trading

Share charts show a stop (22-day high minus 3× ATR), resistance levels from clustered past peaks, and the
12-month high. A second chart loads 5-minute prices on request, with floor pivots from the previous session
and a trailing stop for the day.

Each level shows what happened at it over the past 5 years (or about 60 trading days for 5-minute data),
compared with a normal period of the same length, and says when there's no clear difference.

- **Yahoo prices are delayed by about 15 minutes or more.** That's unsuitable for acting within minutes, so
  check the live price in DEGIRO.
- Tested on a few stocks, a break of the stop line showed no consistent drop afterwards. Don't assume these
  lines predict anything for a particular stock; read the evidence shown for it.
- The page shows the price rise needed just to cover your order costs. Most day traders lose money.

## Vraag Claude

An optional chat page for explaining terms, market history and what the signals mean. Its
instructions are the skill in `app/ask/skills/beurs-expert/SKILL.md`, which you can edit like any
other text file. It lays out the arguments on buying or selling but doesn't tell you what to do:
Claude is not a licensed adviser and doesn't know your full situation.

**Setting it up.** By default it runs Claude Code on the same computer as the app, using your Claude
subscription, so there is no API key and no charge per question. Questions count towards your plan's
limits. Install Claude Code, run `claude auth login` once, and start the app outside Docker.

- **Only for you.** A subscription is personal, so only the oldest administrator account can use the
  page. Anthropic's terms don't allow routing plan credentials on behalf of other users, and they
  don't mention a private app used by its owner. Anthropic says it can enforce its rules without notice.
- **Locked down.** Each question starts Claude Code with no tools, MCP servers, skills or settings, in
  an empty folder, and it saves no session. It can only write an answer. API keys in the app's
  environment are not passed on, so a question can't end up billed to a key by accident.
- **Options.** `ASK_CLI_PATH` points to the program if it isn't found, `ASK_CLI_MODEL` picks a model
  (default: your plan's), and `ASK_DAILY_LIMIT` limits questions per day.
- **Docker and the Raspberry Pi.** The image doesn't include Claude Code, so the page shows setup
  instructions there. Adding it isn't built or tested yet.

**With an API key instead.** Set `ASK_BACKEND=api` and `ANTHROPIC_API_KEY`, and every account can use
the page, also in Docker. Each question is billed to the key, separately from a subscription, and its
owner pays for all users. The default model, `claude-opus-5-5`, costs $4 per million input tokens and
$20 per million output tokens at the time of writing. Change it with `ASK_MODEL`. Don't keep the key in
a `.env` file in this OneDrive folder.

**What leaves your machine.** Every question goes to Anthropic. Nothing from your portfolio goes along
unless you pick it for that question, and the page shows the exact text first. A shared stock or
portfolio includes names, ISINs, percentages, signals and their reasons, but no amounts, quantities or
account names. Conversations stay in the browser tab and aren't stored or logged by this tool.

**Limits.** Claude has no live prices or news beyond what the app shares, and only stocks you hold can
be shared. Its historical figures come from memory, so check them before relying on them.

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

The only outside connection is to Yahoo Finance, which receives ticker symbols and ISINs of holdings,
but no amounts or personal details. Passwords are stored as scrypt hashes.

## Move to a Raspberry Pi

Needs a Pi 4 or 5 with 64-bit Raspberry Pi OS and Docker installed. The arm64 build has not been run
on real hardware yet.

**1. Back up the volume on the current machine:**

```bash
docker run --rm -v stock-analyzer_stock_data:/data -v "$(pwd):/backup" alpine tar czf /backup/stock-data.tgz -C /data .
```

Run this outside the OneDrive folder, because the backup contains your financial data.

**2. Create the first account before opening it to your network**, because the first visitor to an empty
installation becomes the administrator. A restored database that already has accounts doesn't have this
risk. Then, on the Pi, create `.env` next to `docker-compose.yml`:

```ini
BIND_ADDRESS=0.0.0.0
```

Traffic on your network is plain HTTP, including passwords. Don't forward this port to the internet.

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
| `app/auth.py`, `app/migrations.py` | Accounts, database upgrades |
| `app/importers/` | CSV parsing and storing |
| `app/portfolio/positions.py` | Positions, average cost, result |
| `app/market/` | Data source interface, Yahoo adapter, nightly refresh |
| `app/analysis/` | Metrics, scoring, screener, sell levels, backtest |
| `app/dividends/calendar.py` | Received and expected dividends |
| `app/i18n/nl.py` | All interface text |
| `app/web/` | Routes, templates, CSS, charts |
