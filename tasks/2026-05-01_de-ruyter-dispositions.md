# Feature: Dispositions de Ruyter — taux PFU réduit pour frontaliers LAMal

Created: 2026-05-01

## Context

Frontaliers affiliated to Swiss LAMal are exempt from French CSG (9.2 %) and CRDS (0.5 %)
on capital gains and dividends under CJUE ruling C-623/13 (_de Ruyter_, 26 Feb 2015) and
art. L136-6 / L136-7 I ter CSS. The effective PFU rate drops from **30.0 %** to **20.3 %**
(12.8 % IR + 7.5 % prélèvement de solidarité) during Swiss work periods.

The rate is determined **at the date of each transaction**. Workers who alternate between
Switzerland and France get a different rate per gain line. A France gap (unemployment,
French employment) reverts to 30.0 %.

## New module — `src/de_ruyter.py`

Key exports:

| Symbol                    | Type      | Description                                                                              |
| ------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `STANDARD_PFU_RATE`       | `float`   | `0.30`                                                                                   |
| `DE_RUYTER_PFU_RATE`      | `float`   | `0.203`                                                                                  |
| `SwissWorkPeriod`         | dataclass | `start_date`, `end_date` (None = open), `period_type` (`'switzerland'` \| `'france'`)    |
| `DeRuyterConfig`          | class     | Collection wrapper; `pfu_rate_on(date)`, `is_active()`, `from_raw()`, `periods_as_raw()` |
| `pfu_rate_label(rate)`    | function  | `0.203 → "20,3 %"`                                                                       |
| `load_de_ruyter_arg(arg)` | function  | Loads config from `None` (auto-discover), inline JSON, or file path                      |

`is_active()` returns `True` only if at least one period has `period_type == 'switzerland'`.
`pfu_rate_on(date)` returns `DE_RUYTER_PFU_RATE` for dates inside a Switzerland period,
`STANDARD_PFU_RATE` otherwise (including gaps between periods and France-typed periods).

## Configuration file — `src/config/de_ruyter_periods.json`

Auto-discovered at startup when `--de-ruyter-periods` is not passed. Missing file silently
returns `DeRuyterConfig.empty()` (standard 30.0 % everywhere).

```json
[
  {"start_date": "2023-07-01", "end_date": "2023-10-15", "type": "france"},
  {"start_date": "2023-10-16", "end_date": "2025-05-31", "type": "switzerland"},
  {"start_date": "2025-06-01", "end_date": "2025-07-06", "type": "france"},
  {"start_date": "2025-07-07", "end_date": null,          "type": "switzerland"}
]
```

`"type"` defaults to `"switzerland"` when omitted (backward compatibility).
`"end_date": null` means the period is open-ended (through today).

## CLI flag added (all three scripts)

| Flag                                  | Default | Description                                                                                                |
| ------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| `--de-ruyter-periods JSON_OU_FICHIER` | `None`  | Inline JSON array or path to `.json` file. If omitted, auto-discovers `src/config/de_ruyter_periods.json`. |

## CSV changes

| File                          | Column added | Value                    |
| ----------------------------- | ------------ | ------------------------ |
| `<year>_gains_2074.csv`       | `Taux PFU`   | float — `0.203` or `0.3` |
| `<year>_gains_2086.csv` (Yuh) | `Taux PFU`   | float — `0.203` or `0.3` |
| `<year>_dividendes.csv` (Yuh) | _(none)_     | rate used in README only |

A `Taux PFU appliqué` label column (human-readable string) was considered and removed —
the float column is sufficient for downstream processing.

The Yuh gains column was also renamed `Plus/moins-value EUR` → `Plus/moins-value EUR (PMP)`
for consistency with the Wise output, which `unified_readme.py` reads under that name.

## README changes (per broker + unified)

- **Régime de Ruyter section**: period table with `Début | Fin | Type | Taux PFU` columns.
- **Formulaire 2074 header**: `"de Ruyter actif"` suffix when active.
- **Répartition par taux PFU table**: gain/perte split by rate label per year.
- **Penalty section**: per-rate rows `Plus-value nette (arrondie, case 3VG) (20,3 %)` and
  `Impôt dû (20,3 %)` instead of a single hardcoded 30 % row. A `**Impôt dû total**` row
  appears only when both rates are present.

### Penalty computation (updated)

```
by_year_rate = {year: {rate_label: {'gain': float, 'tax': float}}}

tax per row  = round(gain_eur) * rate   if round(gain_eur) > 0
             = 0.0                       otherwise

tax_owed     = round(sum of tax across all rate groups for the year)
```

`unified_readme.py` merges `yuh_groups` and `wise_groups` by rate label into
`combined_groups` before computing the penalty table.

## Tests — `tests/test_de_ruyter.py`

| Class                           | What it covers                                             |
| ------------------------------- | ---------------------------------------------------------- |
| `TestDeRuyterConfigEmpty`       | empty config always returns standard rate                  |
| `TestDeRuyterConfigFourPeriods` | four-period fixture; France period 1 returns standard rate |
| `TestDeRuyterConfigGapScenario` | ~5-week France gap between two Swiss periods               |
| `TestPfuRateLabel`              | formatting of both rates                                   |
| `TestLoadDeRuyterArg`           | None/missing file, inline JSON, file path                  |

## Files modified

- `src/de_ruyter.py` — new module
- `src/config/de_ruyter_periods.json` — new config file
- `src/yuh_csv_ifu.py` — `--de-ruyter-periods` arg, `by_year_rate_2074` dict, CSV columns, README sections
- `src/wise_csv_ifu.py` — `--de-ruyter-periods` arg, `rate_groups_wise` dict, CSV column, README sections
- `src/unified_readme.py` — `--de-ruyter-periods` arg, `_group_gains`, `combined_groups`, penalty table
- `tests/test_de_ruyter.py` — new test file
- `.gitignore` — `ifu/` → `ifu*/` to cover `ifu-new/` output directory
