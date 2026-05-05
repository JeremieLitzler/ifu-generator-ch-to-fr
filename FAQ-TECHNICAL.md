# FAQ — Technical

## Is the README meant for users or developers?

The README is for **users**: it covers what the tool does, which brokers are supported, how to run the scripts, what output files are produced, and which tax rules are applied. No Python internals.

`CLAUDE.md` is for **developers/Claude Code**: it covers the script inventory, internal architecture (parsing, FX cache, PMP logic), and implementation rules.

---

## What documentation files exist and what do they cover?

| File                       | Audience                 | Content                                                                  |
| -------------------------- | ------------------------ | ------------------------------------------------------------------------ |
| `README.md`                | Users                    | Business usage — brokers, IFU forms, commands, output files, tax rules   |
| `CLAUDE.md`                | Developers / Claude Code | Technical details — script inventory, architecture, implementation rules |
| `FAQ.md`                   | Users                    | Tax and business questions                                               |
| `FAQ-TECHNICAL.md`         | Developers / Users       | Technical implementation questions                                       |
| `CALCULATIONS_ACCURACY.md` | Users / Developers       | Confidence levels per computation area                                   |

---

## Which scripts exist and what do they do?

| Script                    | Purpose                                                                     |
| ------------------------- | --------------------------------------------------------------------------- |
| `src/yuh_csv_ifu.py`      | Processes Yuh/Swissquote CSV exports → IFU CSVs                             |
| `src/wise_csv_ifu.py`     | Processes Wise Assets CSV exports → IFU CSVs (primary)                      |
| `src/wise_pdf_ifu.py`     | Processes Wise annual PDF tax statement → IFU CSVs (cross-check / fallback) |
| `src/unified_readme.py`   | Merges Yuh + Wise outputs into a single `ifu/<year>/README.md`              |
| `src/fees_by_activity.py` | Debug utility: groups Yuh fees by activity type                             |
| `src/constants.py`        | Activity type constants for Yuh CSV rows                                    |
| `src/ticker_isin.py`      | Ticker → ISIN mapping for Yuh securities                                    |

---

## What shell wrappers are in `scripts/` and how do I use them?

| Script                         | Calls                 | Usage                                                |
| ------------------------------ | --------------------- | ---------------------------------------------------- |
| `scripts/generate_ifu_yuh.sh`  | `src/yuh_csv_ifu.py`  | `bash scripts/generate_ifu_yuh.sh <year> [options]`  |
| `scripts/generate_ifu_wise.sh` | `src/wise_csv_ifu.py` | `bash scripts/generate_ifu_wise.sh <year> [options]` |

Both wrappers pass all arguments through to the underlying Python script (`"$@"`), so every optional flag — `--transactions-folder`, `--cache`, `-s`, `-f`, `-ff` — works exactly as documented for the Python scripts.

```bash
# Examples
bash scripts/generate_ifu_yuh.sh 2024
bash scripts/generate_ifu_wise.sh 2024 --transactions-folder transactions -s
```

---

## Why does `yuh_csv_ifu.py` use CSV exports instead of individual transaction PDFs?

The original `yuh_ifu.py` parsed individual `TRANSACTION-*.PDF` files downloaded one by one from the Yuh app. The CSV export (`ACTIVITIES_REPORT-<year>.CSV`) covers the entire year in one file, is already structured (semicolon-delimited, consistent columns), and requires only `requests` instead of `pdfplumber`. PDF parsing relies on regex against free-form text and breaks if Yuh changes the notice layout; the CSV format is far more stable.

---

## How does the script identify which security paid a dividend?

Yuh's `CASH_TRANSACTION_RELATED_OTHER` rows (dividends) leave the `ASSET` column empty — only the `ACTIVITY NAME` free-text field identifies the security (e.g. `S&P 500 (Vanguard S&P 500) Dividend`).

The script resolves this via `TICKER_NAME_KEYWORDS` in `ticker_isin.py`: a dict mapping each ticker to a list of keywords. It searches the activity name case-insensitively for any of those keywords and returns the first match. If no keyword matches, a warning is printed and the dividend is recorded with ticker `UNKNOWN` so it still appears in the output CSVs for manual review.

---

## What filename format does `yuh_csv_ifu.py` expect for input CSV files?

Files must be named `yuh_ACTIVITIES_REPORT-<year>.CSV` (or `.csv`) and placed inside the folder specified by `--transactions-folder` (default: `transactions/`). The `yuh_` prefix distinguishes Yuh exports from Wise files when both brokers' exports share the same folder.

Example: `transactions/yuh_ACTIVITIES_REPORT-2024.CSV`

---

## What happened to `generate_ifu.sh`?

It was renamed to `generate_ifu_yuh.sh` to match the broker-specific naming convention alongside `generate_ifu_wise.sh`. There is no longer a generic `generate_ifu.sh`.

---

## Why was `-f` removed as the shorthand for `--transactions-folder`?

The `-f` flag was reassigned to mean "formal penalty scenario" (40 % surcharge) when the `-s`/`-f`/`-ff` penalty shortcuts were introduced. Use `--transactions-folder` (shorthand `-tf`) instead. The default (`transactions/`) is correct for most setups, so this only affects users who were explicitly passing `-f <path>` on the command line.

---

## How are BANK_AUTO_ORDER_EXECUTED auto-exchange fees matched to a specific buy order?

The script matches each auto-exchange fee to a buy transaction using two criteria: (1) same date, and (2) same foreign currency (the exchange's `CREDIT CURRENCY` equals the buy's `DEBIT CURRENCY`). When exactly one buy satisfies both criteria, the CHF fee is converted to EUR at the BCE rate for that date and added to that transaction's `exchange_fee_eur` field, which flows into the PMP cost basis.

Amount-based matching is not used — the exchanged USD amount and the buy's USD debit are not expected to match exactly due to how Yuh books the two legs internally.

---

## Is there an audit trail for attributed auto-exchange fees in the output CSVs?

Yes. The `*_transactions.csv` output includes an `exchange_fee_eur` column showing the EUR-converted auto-exchange fee attributed to each buy transaction. A value of `0.0` means no fee was attributed — either the buy was in CHF (no auto-exchange needed) or the fee was ambiguous/unmatched and reported in the lump-sum section instead.

---

## What is the output directory structure under `ifu/`?

```plaintext
ifu/
└── <year>/
    ├── README.md             ← unified_readme.py consolidated summary
    ├── yuh/
    │   ├── README.md         ← yuh_csv_ifu.py per-broker summary
    │   ├── <year>_transactions.csv
    │   ├── <year>_gains_2074.csv
    │   ├── <year>_gains_2086.csv
    │   ├── <year>_dividendes.csv
    │   ├── <year>_summary.csv
    │   └── <year>_fx_log.csv
    └── wise/
        ├── README.md         ← wise_csv_ifu.py per-broker summary
        ├── <year>_transactions.csv
        ├── <year>_gains_2074.csv
        ├── <year>_dividendes.csv
        ├── <year>_fees.csv
        ├── <year>_summary.csv
        └── <year>_fx_log.csv
```

Outputs are grouped by year then broker. The unified `README.md` at the year root aggregates both brokers; each broker subdirectory also has its own `README.md`. Yuh produces `gains_2086.csv` (crypto-ETP precautionary output); Wise produces `fees.csv` (platform fee log). Neither file has an equivalent in the other broker's output.

---

## What does `unified_readme.py` produce?

A single `ifu/<year>/README.md` with one table per tax form, showing the exact values to type into the online French tax return:

- **Formulaire 2074** — Yuh and Wise gains shown separately, then combined with the final case (3VG or 3VH) and rounded integer to enter.
- **Formulaire 2042** — 2DC, 2TR, and 2AB values from Yuh dividends.
- **Formulaire 3916** — checklist of foreign accounts to declare (inferred from which broker data is present).
- **Penalty block** — if a `-s`/`-f`/`-ff` flag is passed, the late-declaration penalty estimate for the combined gain.

Run it after both broker scripts have generated their CSVs for the year.

---

## Can a script automatically fill in the IFU PDF forms?

No — the official PDFs (`2561_R24.pdf`, `2561_ter_R24.pdf`) are **flat, non-interactive** files with no fillable AcroForm fields. They are explicitly labelled _"Support visuel uniquement — Ne pas envoyer à la DGFiP"_.

The most practical alternative is a **summary report script** that reads the CSV outputs and prints each IFU zone value alongside the corresponding 2042 / 2074 line to type into the online declaration at impots.gouv.fr.

---

## Where are the official IFU PDF forms stored in this project?

In `tax_forms/<year>/`. For 2024 income:

| File                                     | Content                                                                                                                                                                                                                       |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tax_forms/2024/2561_NOT_R25_notice.pdf` | Explanatory notice (filing rules, field descriptions)                                                                                                                                                                         |
| `tax_forms/2024/2561_R24.pdf`            | Main form — zone AN (_montant brut des cessions_), zone AY (_revenus éligibles abattement 40 %_), zone AZ (_revenus non éligibles_), zone AA (_retenue à la source étrangère_), zone AD (_intérêts et produits assimilés_), … |
| `tax_forms/2024/2561_ter_R24.pdf`        | Tax credit certificate — zone 2AB (_crédit d'impôt étranger, porté ligne 2AB form 2042_), zone 2CK (_prélèvement forfaitaire non libératoire imputé_), capital gains summary                                                  |

These files are for reference only and are not submitted to the DGFiP.

---

## Which files are gitignored?

- `transactions/` — personal CSV exports from Yuh and Wise
- `guide-investissement-frontalier*.md` — personal reference documents
- `ifu/` output files (optional, depending on local config)

---

## Why does the Wise script recompute gains instead of using the annual PDF tax report?

Two reasons:

1. **Wrong method**: Wise's PDF uses FIFO (_First In First Out_). French law (art. 150-0 D CGI) requires PMP (_Prix Moyen Pondéré_). The two methods give different results whenever shares bought at different prices are partially sold.

2. **Incomplete history**: The PDF only lists buys that are FIFO-matched to that year's sells. Buys for positions still held at 31 December are absent, making it impossible to compute a correct PMP for future years from the PDF alone.

The raw CSV contains all transactions and is sufficient for an exact PMP computation.

---

## Does the project require any external Python packages?

No. Every script uses only the Python standard library — no `pip install` needed.

| Module | Source |
|--------|--------|
| `argparse`, `csv`, `json`, `math`, `re`, `sys` | Standard library |
| `collections`, `dataclasses`, `datetime`, `pathlib`, `typing` | Standard library |
| `constants`, `ticker_isin` | Local modules within `src/` |

Python 3.7+ is sufficient to run all scripts.

---

## How do I use `fees_by_activity.py` to audit my Yuh broker fees?

Run `python fees_by_activity.py <year>` (e.g., `python fees_by_activity.py 2023`). It reads `transactions/ACTIVITIES_REPORT-<year>.CSV`, sums the `FEES/COMMISSION` column grouped by `ACTIVITY TYPE`, and prints a table with a grand total. Use `--transactions-folder` to point to a different directory.

```
ACTIVITY TYPE                    FEES/COMMISSION
---------------------------------------------------
BANK_AUTO_ORDER_EXECUTED         2.09
BANK_ORDER_EXECUTED              17.88
INVEST_ORDER_EXECUTED            2.23
INVEST_RECURRING_ORDER_EXECUTED  8.02
---------------------------------------------------
TOTAL                            30.22
```
