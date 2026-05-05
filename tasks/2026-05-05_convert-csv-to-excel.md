# Task: Convert IFU CSVs to Excel workbooks

**Issue:** #20  
**Branch:** `feat/convert-csv-to-excel`

## Context

After running `yuh_csv_ifu.py` or `wise_csv_ifu.py`, the output directory contains several CSV files per broker. Users need a single Excel workbook per broker for easier reading and sharing, without changing the CSV generation scripts themselves.

## Feature description

New standalone script `src/csv_to_excel.py`:

- Reads CSV files from `<ifu-root>/<year>/yuh/` and/or `<ifu-root>/<year>/wise/`
- Produces one `.xlsx` workbook per broker in `<ifu-root>/<year>/excel/`
- Each CSV file becomes one sheet (sheet name = filename stem minus the year prefix)
- Workbook naming: `<broker>_<year>_ifu.xlsx` (e.g. `yuh_2024_ifu.xlsx`)
- Silently skips brokers whose subfolder does not exist

## Usage

```bash
python src/csv_to_excel.py 2024
python src/csv_to_excel.py 2024 --ifu-root ifu
```

## Verification steps

- [x] Run `yuh_csv_ifu.py` for a given year to produce CSVs
- [x] Run `python src/csv_to_excel.py <year>` and confirm `ifu-new/<year>/excel/yuh_<year>_ifu.xlsx` is created
- [x] Open the workbook and verify one sheet per CSV, sheet names match CSV names (without year prefix)
- [x] Run for a year that has both yuh and wise CSVs — confirm two workbooks are produced
- [x] Run for a year with only one broker — confirm only one workbook is created, no error for the missing broker
- [x] Verify accented characters (é, à, ô) in French column headers render correctly in Excel
