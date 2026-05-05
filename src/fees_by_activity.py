#!/usr/bin/env python3
"""
fees_by_activity.py — Groupe les frais (FEES/COMMISSION) par ACTIVITY TYPE
à partir des exports CSV Yuh (ACTIVITIES_REPORT-*.CSV).

Usage:
    python fees_by_activity.py <year> [--transactions-folder transactions]

Exemple:
    python fees_by_activity.py 2023
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path


def parse_fee(value: str) -> float:
    value = value.strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def process_files(paths: list[Path]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for path in paths:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                activity = row["ACTIVITY TYPE"].strip()
                fee = parse_fee(row["FEES/COMMISSION"])
                if fee:
                    totals[activity] += fee
    return dict(totals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sum FEES/COMMISSION by ACTIVITY TYPE")
    parser.add_argument("year", help="Year suffix, e.g. 2023")
    parser.add_argument("--transactions-folder", "-tf", default="transactions", help="Folder containing the CSV files")
    args = parser.parse_args()

    path = Path(args.transactions_folder) / f"ACTIVITIES_REPORT-{args.year}.CSV"
    if not path.exists():
        print(f"File not found: {path}")
        return
    paths = [path]

    if not paths:
        print(f"No CSV files found in '{args.transactions_folder}'.")
        return

    print(f"Processing {len(paths)} file(s):")
    for p in paths:
        print(f"  {p}")
    print()

    totals = process_files(paths)

    if not totals:
        print("No fees found.")
        return

    col_w = max(len(k) for k in totals)
    print(f"{'ACTIVITY TYPE':<{col_w}}  FEES/COMMISSION")
    print("-" * (col_w + 20))
    grand_total = 0.0
    for activity, total in sorted(totals.items()):
        print(f"{activity:<{col_w}}  {total:.2f}")
        grand_total += total
    print("-" * (col_w + 20))
    print(f"{'TOTAL':<{col_w}}  {grand_total:.2f}")


if __name__ == "__main__":
    main()
