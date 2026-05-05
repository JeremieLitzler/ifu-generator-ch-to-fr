# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scripts

| Script | Purpose |
|--------|---------|
| `src/yuh_csv_ifu.py` | Yuh/Swissquote CSV → IFU CSVs |
| `src/wise_csv_ifu.py` | Wise Assets CSV → IFU CSVs |
| `src/unified_readme.py` | Merges Yuh + Wise outputs into a single `ifu/<year>/README.md` |
| `src/fees_by_activity.py` | Debug utility: groups Yuh `FEES/COMMISSION` by `ACTIVITY_TYPE` |
| `src/constants.py` | `ACTIVITY_TYPE` string constants for Yuh CSV rows |
| `src/ticker_isin.py` | `TICKER_ISIN` dict (Yuh ticker → ISIN + name). Update when new securities appear. |
| `src/csv_to_excel.py` | Standalone script: reads broker CSV outputs and writes `<broker>_<year>_ifu.xlsx` into `<ifu-root>/<year>/excel/`. Run after the broker scripts. |

Shell wrappers in `scripts/` call the Python scripts from the repo root.

## Bash command rules

- **Always prefix `git` commands with `rtk`**: use `rtk git …` for every git command (e.g. `rtk git status`, `rtk git commit`, `rtk git push`).
- **Always prefix `gh` commands with `rtk`**: use `rtk gh …` for every GitHub CLI call (e.g. `rtk gh issue list`, `rtk gh issue create`, `rtk gh pr view`).

## Architecture — yuh_csv_ifu.py

1. **CSV parsing** (`parse_csv_file`) — UTF-8 BOM, semicolon-delimited. Filters `INVEST_*` (buy/sell), `CASH_TRANSACTION_RELATED_OTHER` (dividends), `BANK_AUTO_ORDER_EXECUTED` Autoexchange (exchange fees). Resolves ticker→ISIN via `ticker_isin.py`.
2. **FX conversion** (`FXCache`) — persistent JSON cache keyed `"{date}_{currency}"`. Pass-through for EUR. Shifts weekend/holiday dates to last business day.
3. **PMP gain calculation** (`compute_gains`) — sorted by date+row_id; weighted average cost per ISIN; realized gains recorded on each sell.
4. **Output** — filters to target year; writes six CSV files; prints console summary.

## Architecture — wise_csv_ifu.py

Same FXCache and PMP logic. Input columns: `Traded Asset ID Value`, `Execution Date`, `Transaction Type` (BUY / SELL / FEE_CHARGE), `Traded Units`, `Settlement Amount`, `Settlement Currency`. FEE_CHARGE rows are logged separately and excluded from cost basis.

## Dependencies

- All runtime dependencies are listed in `requirements.txt`. Update it when adding a new `import` that requires a third-party package.

## Key implementation rules

- **Crypto-ETPs**: `CRYPTO_ETP_ISINS` in `yuh_csv_ifu.py` must be updated when new crypto-ETPs are held.
- **Cost basis** (buy) = `abs(DEBIT)` including Yuh commission. **Proceeds** (sell) = `CREDIT` net of fees.
- **Auto-exchange fees** (`BANK_AUTO_ORDER_EXECUTED`): matched to buy order by date + foreign currency. Ambiguous or unmatched fees reported as lump sum.
- `transactions/` CSVs and `guide-investissement-frontalier*.md` are gitignored (personal financial data).
