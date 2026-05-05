import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from de_ruyter import (
    DeRuyterConfig,
    SwissWorkPeriod,
    DE_RUYTER_PFU_RATE,
    STANDARD_PFU_RATE,
    load_de_ruyter_arg,
    pfu_rate_label,
)

_FOUR_PERIODS_RAW = [
    {"start_date": "2023-07-01", "end_date": "2023-10-15", "type": "france"},
    {"start_date": "2023-10-16", "end_date": "2025-05-31", "type": "switzerland"},
    {"start_date": "2025-06-01", "end_date": "2025-07-06", "type": "france"},
    {"start_date": "2025-07-07", "end_date": None, "type": "switzerland"},
]


class TestDeRuyterConfigEmpty:
    def test_is_not_active(self) -> None:
        assert not DeRuyterConfig.empty().is_active()

    def test_always_returns_standard_rate(self) -> None:
        config = DeRuyterConfig.empty()
        assert config.pfu_rate_on(date(2024, 6, 15)) == STANDARD_PFU_RATE

    def test_returns_standard_rate_for_any_date(self) -> None:
        config = DeRuyterConfig.empty()
        assert config.pfu_rate_on(date(2020, 1, 1)) == STANDARD_PFU_RATE
        assert config.pfu_rate_on(date(2030, 12, 31)) == STANDARD_PFU_RATE


class TestDeRuyterConfigFourPeriods:
    @pytest.fixture
    def config(self) -> DeRuyterConfig:
        return DeRuyterConfig.from_raw(_FOUR_PERIODS_RAW)

    def test_is_active(self, config: DeRuyterConfig) -> None:
        assert config.is_active()

    def test_date_before_all_periods_returns_standard_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2023, 6, 30)) == STANDARD_PFU_RATE

    def test_date_inside_period_one_france_returns_standard_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2023, 8, 15)) == STANDARD_PFU_RATE

    def test_date_inside_period_two_returns_de_ruyter_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2024, 6, 15)) == DE_RUYTER_PFU_RATE

    def test_date_inside_open_ended_period_returns_de_ruyter_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2026, 1, 1)) == DE_RUYTER_PFU_RATE

    def test_periods_as_raw_round_trips(self, config: DeRuyterConfig) -> None:
        raw = config.periods_as_raw()
        assert raw[0]['start_date'] == '2023-07-01'
        assert raw[0]['end_date'] == '2023-10-15'
        assert raw[0]['type'] == 'france'
        assert raw[1]['type'] == 'switzerland'
        assert raw[2]['type'] == 'france'
        assert raw[3]['type'] == 'switzerland'
        assert raw[3]['end_date'] is None


class TestDeRuyterConfigGapScenario:
    """Frontalier who had a ~5-week French unemployment gap (2025-06-01 → 2025-07-06)."""

    @pytest.fixture
    def config(self) -> DeRuyterConfig:
        return DeRuyterConfig.from_raw([
            {"start_date": "2023-10-16", "end_date": "2025-05-31"},
            {"start_date": "2025-07-07", "end_date": None},
        ])

    def test_during_swiss_work_returns_de_ruyter_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2024, 6, 15)) == DE_RUYTER_PFU_RATE

    def test_start_of_gap_returns_standard_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2025, 6, 1)) == STANDARD_PFU_RATE

    def test_middle_of_gap_returns_standard_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2025, 6, 15)) == STANDARD_PFU_RATE

    def test_last_day_of_gap_returns_standard_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2025, 7, 6)) == STANDARD_PFU_RATE

    def test_first_day_after_gap_returns_de_ruyter_rate(self, config: DeRuyterConfig) -> None:
        assert config.pfu_rate_on(date(2025, 7, 7)) == DE_RUYTER_PFU_RATE


class TestPfuRateLabel:
    def test_standard_rate_label(self) -> None:
        assert pfu_rate_label(STANDARD_PFU_RATE) == "30,0 %"

    def test_de_ruyter_rate_label(self) -> None:
        assert pfu_rate_label(DE_RUYTER_PFU_RATE) == "20,3 %"


class TestLoadDeRuyterArg:
    def test_none_with_default_file_loads_config(self) -> None:
        config = load_de_ruyter_arg(None)
        assert config.is_active()
        assert config.pfu_rate_on(date(2024, 6, 15)) == DE_RUYTER_PFU_RATE

    def test_none_without_default_file_returns_empty_config(self, tmp_path: Path) -> None:
        missing = tmp_path / "no_file.json"
        with patch("de_ruyter._DEFAULT_PERIODS_FILE", missing):
            config = load_de_ruyter_arg(None)
        assert not config.is_active()

    def test_inline_json_returns_active_config(self) -> None:
        inline = json.dumps(_FOUR_PERIODS_RAW)
        config = load_de_ruyter_arg(inline)
        assert config.is_active()
        assert config.pfu_rate_on(date(2024, 6, 15)) == DE_RUYTER_PFU_RATE

    def test_json_file_returns_active_config(self, tmp_path: Path) -> None:
        json_file = tmp_path / "periods.json"
        json_file.write_text(json.dumps(_FOUR_PERIODS_RAW), encoding='utf-8')
        config = load_de_ruyter_arg(str(json_file))
        assert config.is_active()
        assert config.pfu_rate_on(date(2024, 6, 15)) == DE_RUYTER_PFU_RATE
