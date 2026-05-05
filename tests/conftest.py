import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
TRANSACTIONS = REPO_ROOT / "transactions"
GOLDEN_ROOT = REPO_ROOT / "ifu"
OUTPUT_ROOT = REPO_ROOT / "tests" / "output"
FX_CACHE = REPO_ROOT / "fx_cache.json"
YEARS = [2023, 2024, 2025]

_DATE_PATTERN = re.compile(r'Généré le \d{4}-\d{2}-\d{2}')


def normalize(content: str) -> str:
    """Normalize line endings, trailing whitespace, and volatile date stamps."""
    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    stripped = [_DATE_PATTERN.sub('Généré le DATE', line.rstrip()) for line in lines]
    return '\n'.join(stripped).strip()


def _inputs_available() -> bool:
    return TRANSACTIONS.is_dir() and FX_CACHE.exists()


def _has_yuh_csv(year: int) -> bool:
    upper = list(TRANSACTIONS.glob(f"yuh_ACTIVITIES_REPORT-{year}.CSV"))
    lower = list(TRANSACTIONS.glob(f"yuh_ACTIVITIES_REPORT-{year}.csv"))
    return bool(upper or lower)


def _has_wise_csv(year: int) -> bool:
    return bool(list(TRANSACTIONS.glob(f"wise_assets_statement_*{year}*.csv")))


def _run(script: str, arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / script)] + arguments,
        cwd=str(REPO_ROOT),
        capture_output=True,
        encoding='utf-8',
    )


def _generate_year(year: int) -> None:
    shared = ["--transactions-folder", str(TRANSACTIONS), "--cache", "fx_cache.json", "--out", str(OUTPUT_ROOT)]
    if _has_yuh_csv(year):
        _run("yuh_csv_ifu.py", [str(year)] + shared)
    if _has_wise_csv(year):
        _run("wise_csv_ifu.py", [str(year)] + shared)
    _run("unified_readme.py", [str(year), "--ifu-root", str(OUTPUT_ROOT)])


@pytest.fixture(scope="session", autouse=True)
def generate_outputs() -> None:
    if not _inputs_available():
        return
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        _generate_year(year)
