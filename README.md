# ifu-generator

Generates French tax declaration data (IFU equivalent) for French-resident cross-border workers (frontaliers) holding investment accounts at **Yuh/Swissquote** and/or **Wise Assets**.

Implements the **PMP method** (art. 150-0 D CGI) with ECB CHF→EUR exchange rates.

Produces per year and broker:

- CSVs with detailed data, if the authorities ask for them
- a summary Markdown file.

A unified Markdown summary per year provide the figures to fill in forms 2074, 2086, and 2042.

---

## Supported brokers

| Broker           | Input files                   | Output folder          |
| ---------------- | ----------------------------- | ---------------------- |
| Yuh / Swissquote | `ACTIVITIES_REPORT-*.CSV`     | `ifu-new/<year>/yuh/`  |
| Wise Assets      | `wise_assets_statement_*.csv` | `ifu-new/<year>/wise/` |

---

## Prerequisites

```bash
pip install -r requirements.txt
```

Dependencies:

- `requests` for ECB exchange rates
- `openpyxl` for Excel export

---

## Usage — Yuh / Swissquote

```bash
bash scripts/generate_ifu_yuh.sh <year> [--folder <dir>] [--cache fx_cache.json]
```

Or directly:

```bash
python src/yuh_csv_ifu.py 2024 [--folder transactions] [--cache fx_cache.json]
```

**With dispositions de Ruyter (frontaliers LAMal — PFU 20,3 %):**

```bash
python src/yuh_csv_ifu.py 2024 --de-ruyter-periods src/config/de_ruyter_periods.json
```

**With late-declaration penalty estimate:**

```bash
python src/yuh_csv_ifu.py 2024 -s    # spontaneous correction (10 %)
python src/yuh_csv_ifu.py 2024 -f    # after formal notice (40 %)
python src/yuh_csv_ifu.py 2024 -ff   # fraud (80 %)
```

**Output files** in `ifu-new/<year>/yuh/`:

| File                      | Content                                                                   |
| ------------------------- | ------------------------------------------------------------------------- |
| `<year>_transactions.csv` | All operations with CHF/USD→EUR conversion                                |
| `<year>_gains_2074.csv`   | Capital gains/losses → form 2074 (securities); includes `Taux PFU` column |
| `<year>_gains_2086.csv`   | Crypto-ETP gains → form 2086 (informational); includes `Taux PFU` column  |
| `<year>_dividendes.csv`   | Dividends and distributions                                               |
| `<year>_summary.csv`      | Positions and PMP at 31/12                                                |
| `<year>_fx_log.csv`       | ECB rates used                                                            |

---

## Usage — Wise Assets

```bash
bash scripts/generate_ifu_wise.sh <year> [--folder <dir>] [--cache fx_cache.json]
```

Or directly:

```bash
python src/wise_csv_ifu.py 2024 [--folder transactions] [--cache fx_cache.json]
```

Same `--de-ruyter-periods` and penalty flags (`-s`, `-f`, `-ff`) apply.

**Output files** in `ifu-new/<year>/wise/`:

| File                      | Content                                                      |
| ------------------------- | ------------------------------------------------------------ |
| `<year>_transactions.csv` | All operations with EUR conversion                           |
| `<year>_gains_2074.csv`   | Capital gains/losses → form 2074; includes `Taux PFU` column |
| `<year>_dividendes.csv`   | Dividends (empty for accumulating funds)                     |
| `<year>_fees.csv`         | Monthly management fees (not deductible under PFU)           |
| `<year>_summary.csv`      | Positions and PMP at 31/12                                   |
| `<year>_fx_log.csv`       | ECB rates used                                               |

---

## Usage — Excel export

After running either (or both) broker scripts, convert the CSVs to Excel workbooks:

```bash
python src/csv_to_excel.py 2024 [--ifu-root ifu-new]
```

**Output files** in `ifu-new/<year>/excel/`:

| File                   | Sheets                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------- |
| `yuh_<year>_ifu.xlsx`  | One sheet per CSV (dividendes, fx_log, gains_2074, gains_2086, summary, transactions) |
| `wise_<year>_ifu.xlsx` | One sheet per CSV (dividendes, fees, fx_log, gains_2074, summary, transactions)       |

Only workbooks for broker subdirectories that already exist are created — no error if one broker is missing.

---

## Usage — Unified summary (Yuh + Wise)

After running both scripts, generate a consolidated report:

```bash
python src/unified_readme.py 2024 [--ifu-root ifu-new] [--de-ruyter-periods src/config/de_ruyter_periods.json] [-s|-f|-ff]
```

Produces `ifu-new/<year>/README.md` with exact amounts to enter per tax form line (2074, 2042).

---

## Key tax rules applied

- **PMP method** — weighted average cost basis, recomputed from full transaction history
- **Cost basis** includes broker commissions and auto-exchange fees (frais d'acquisition)
- **ECB rate** on weekends/holidays → last business day (standard DGFiP practice)
- **Crypto-ETPs** (WisdomTree BTC/ETH, etc.) reported separately on form 2086
- **Dispositions de Ruyter** (CJUE C-623/13) — PFU reduced to 20,3 % for LAMal-affiliated frontaliers; rate applied per transaction date via `--de-ruyter-periods`
