#!/usr/bin/env python3
"""
csv_to_excel.py — Converts IFU CSV outputs into per-broker Excel workbooks.

Usage:
    python src/csv_to_excel.py <year> [--ifu-root <dir>]

For each broker subfolder (yuh, wise) found under <ifu-root>/<year>/,
produces one Excel workbook in <ifu-root>/<year>/excel/ with one sheet
per CSV file, named <broker>_<year>_ifu.xlsx.

Run after yuh_csv_ifu.py and/or wise_csv_ifu.py have generated their CSVs.
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

BROKERS = ('yuh', 'wise')


def _sheet_name(csv_path: Path) -> str:
    stem = csv_path.stem
    parts = stem.split('_', 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1][:31]
    return stem[:31]


def _load_csv_rows(csv_path: Path) -> list[list[str]]:
    with csv_path.open(encoding='utf-8', newline='') as file:
        return list(csv.reader(file))


def _write_sheet(workbook: openpyxl.Workbook, csv_path: Path) -> None:
    sheet = workbook.create_sheet(title=_sheet_name(csv_path))
    for row in _load_csv_rows(csv_path):
        sheet.append(row)


def _build_workbook(broker_dir: Path) -> openpyxl.Workbook:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for csv_path in sorted(broker_dir.glob('*.csv')):
        _write_sheet(workbook, csv_path)
    return workbook


def _convert_broker(broker: str, year: int, year_dir: Path, excel_dir: Path) -> bool:
    broker_dir = year_dir / broker
    if not broker_dir.is_dir():
        return False
    csv_files = sorted(broker_dir.glob('*.csv'))
    if not csv_files:
        return False
    excel_path = excel_dir / f'{broker}_{year}_ifu.xlsx'
    _build_workbook(broker_dir).save(excel_path)
    print(f"📊 {broker:5s} → {excel_path}  ({len(csv_files)} sheets)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert IFU CSV outputs to Excel workbooks (one per broker)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('year', type=int, help='Fiscal year (e.g. 2024)')
    parser.add_argument('--ifu-root', default='ifu-new',
                        help="Root output directory (default: 'ifu-new')")
    args = parser.parse_args()

    year_dir = Path(args.ifu_root) / str(args.year)
    if not year_dir.is_dir():
        print(f"Directory not found: {year_dir}", file=sys.stderr)
        sys.exit(1)

    excel_dir = year_dir / 'excel'
    excel_dir.mkdir(exist_ok=True)

    converted = [b for b in BROKERS if _convert_broker(b, args.year, year_dir, excel_dir)]
    if not converted:
        print(f"No broker CSV directories found under {year_dir}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
