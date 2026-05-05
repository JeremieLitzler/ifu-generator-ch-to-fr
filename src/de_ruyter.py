"""
de_ruyter.py — Dispositions dites « de Ruyter » (jurisprudence CJUE C-623/13).

Frontaliers affiliés à la LAMal suisse sont exonérés de CSG (9,2 %) et CRDS
(0,5 %) sur les revenus du patrimoine et de cession.  Le taux PFU effectif
passe de 30,0 % (standard) à 20,3 % (7,5 % prélèvement de solidarité +
12,8 % impôt forfaitaire sur le revenu).

La condition est appréciée à la date de réalisation du gain (art. L136-6
et L136-7, I ter CSS).  Lorsque le travailleur alterne travail en Suisse et
en France, le taux est déterminé ligne par ligne selon la date de l'opération.

Usage :
    from de_ruyter import DeRuyterConfig, pfu_rate_label

    config = DeRuyterConfig.from_raw([
        {"start_date": "2023-10-16", "end_date": "2025-05-31"},
        {"start_date": "2025-07-07", "end_date": None},
    ])
    rate = config.pfu_rate_on(date(2024, 6, 15))  # → 0.203
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

STANDARD_PFU_RATE: float = 0.30    # 17,2 % prélèvements sociaux + 12,8 % IR
DE_RUYTER_PFU_RATE: float = 0.203  # 7,5 % solidarité + 12,8 % IR

_DEFAULT_PERIODS_FILE = Path(__file__).parent / "config" / "de_ruyter_periods.json"


@dataclass
class SwissWorkPeriod:
    start_date: date
    end_date: Optional[date]   # None = ouvert jusqu'à aujourd'hui
    period_type: str = 'switzerland'  # 'switzerland' | 'france'


def _parse_period(entry: dict) -> SwissWorkPeriod:
    start = date.fromisoformat(entry['start_date'])
    end_raw = entry.get('end_date')
    end = date.fromisoformat(end_raw) if end_raw else None
    period_type = entry.get('type', 'switzerland')
    return SwissWorkPeriod(start_date=start, end_date=end, period_type=period_type)


def _date_in_period(check_date: date, period: SwissWorkPeriod) -> bool:
    effective_end = period.end_date or date.today()
    return period.start_date <= check_date <= effective_end


def _rate_from_periods(check_date: date, periods: list[SwissWorkPeriod]) -> float:
    for period in periods:
        if period.period_type == 'switzerland' and _date_in_period(check_date, period):
            return DE_RUYTER_PFU_RATE
    return STANDARD_PFU_RATE


def _period_to_raw(period: SwissWorkPeriod) -> dict:
    return {
        'start_date': period.start_date.isoformat(),
        'end_date': period.end_date.isoformat() if period.end_date else None,
        'type': period.period_type,
    }


class DeRuyterConfig:
    # calisthenics-exception: single-collection wrapper; all behavior via methods
    def __init__(self, periods: list[SwissWorkPeriod]):
        self._periods = periods

    @classmethod
    def empty(cls) -> 'DeRuyterConfig':
        return cls([])

    @classmethod
    def from_raw(cls, raw: list[dict]) -> 'DeRuyterConfig':
        return cls([_parse_period(entry) for entry in raw])

    def is_active(self) -> bool:
        return any(p.period_type == 'switzerland' for p in self._periods)

    def pfu_rate_on(self, transaction_date: date) -> float:
        if not self._periods:
            return STANDARD_PFU_RATE
        return _rate_from_periods(transaction_date, self._periods)

    def periods_as_raw(self) -> list[dict]:
        return [_period_to_raw(p) for p in self._periods]


def pfu_rate_label(rate: float) -> str:
    """Formate un taux PFU (ex: 0.203 → '20,3 %')."""
    return f"{rate * 100:.1f} %".replace('.', ',')


def load_de_ruyter_arg(arg: Optional[str]) -> DeRuyterConfig:
    """
    Charge la configuration de Ruyter.

    - arg=None : cherche src/config/de_ruyter_periods.json (auto-découverte) ;
                 retourne DeRuyterConfig.empty() si le fichier est absent.
    - arg='[…]' : JSON inline.
    - arg='path/to/file.json' : chemin vers un fichier JSON.
    """
    if arg is None:
        return _load_default_config()
    if arg.strip().startswith('['):
        return DeRuyterConfig.from_raw(json.loads(arg))
    return _load_de_ruyter_file(Path(arg))


def _load_default_config() -> DeRuyterConfig:
    if not _DEFAULT_PERIODS_FILE.exists():
        return DeRuyterConfig.empty()
    return _load_de_ruyter_file(_DEFAULT_PERIODS_FILE)


def _load_de_ruyter_file(path: Path) -> DeRuyterConfig:
    raw = json.loads(path.read_text(encoding='utf-8'))
    return DeRuyterConfig.from_raw(raw)
