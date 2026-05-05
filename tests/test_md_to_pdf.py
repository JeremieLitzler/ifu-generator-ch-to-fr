import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from md_to_pdf import (
    _BROWSER_PATHS,
    _convert,
    _find_browser,
    _pdf_path,
    _preprocess,
    _read_readme,
    _readme_path,
    _to_html,
    _write_pdf,
)

_SAMPLE_MARKDOWN = """\
# Déclaration fiscale 2024

## Formulaire 2074

| Source | Gain EUR | Impôt |
|--------|----------|-------|
| Yuh    | +100.00  | 20.30 |

> ⚠ Estimation indicative.

- [ ] Déclarer le compte **Yuh / Swissquote** ✓
"""

_browser_available = any(Path(p).exists() for p in _BROWSER_PATHS)


def _exits_with_code(fn, *args) -> int:
    # calisthenics-exception: pytest.raises requires a with-block
    with pytest.raises(SystemExit) as exc_info:
        fn(*args)
    return exc_info.value.code


class TestMdToPdf:
    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def test_readme_path_is_inside_year_directory(self, tmp_path: Path) -> None:
        assert _readme_path(tmp_path, 2024) == tmp_path / '2024' / 'README.md'

    def test_pdf_path_is_inside_year_directory(self, tmp_path: Path) -> None:
        assert _pdf_path(tmp_path, 2024) == tmp_path / '2024' / 'rapport-2024.pdf'

    # ------------------------------------------------------------------
    # _preprocess
    # ------------------------------------------------------------------

    def test_preprocess_replaces_checkmark_with_oui(self) -> None:
        assert _preprocess('résultat ✓') == 'résultat Oui'

    def test_preprocess_replaces_warning_sign(self) -> None:
        assert _preprocess('⚠ Attention') == '(!) Attention'

    def test_preprocess_leaves_unrelated_text_unchanged(self) -> None:
        text = 'Aucun symbole spécial ici.'
        assert _preprocess(text) == text

    def test_preprocess_replaces_all_occurrences(self) -> None:
        assert _preprocess('✓ done ✓') == 'Oui done Oui'

    # ------------------------------------------------------------------
    # _to_html
    # ------------------------------------------------------------------

    def test_to_html_contains_doctype(self) -> None:
        assert '<!DOCTYPE html>' in _to_html('# Titre')

    def test_to_html_contains_style_block(self) -> None:
        assert '<style>' in _to_html('# Titre')

    def test_to_html_css_not_rendered_as_body_text(self) -> None:
        html = _to_html('# Titre')
        body_section = html.split('</style>', 1)[1]
        assert 'font-family' not in body_section

    def test_to_html_renders_h1_heading(self) -> None:
        assert '<h1>' in _to_html('# Déclaration')

    def test_to_html_renders_h2_heading(self) -> None:
        assert '<h2>' in _to_html('## Section')

    def test_to_html_renders_table_from_markdown(self) -> None:
        assert '<table>' in _to_html(_SAMPLE_MARKDOWN)

    def test_to_html_replaces_checkmark_via_preprocess(self) -> None:
        html = _to_html('Résultat ✓')
        assert 'Oui' in html
        assert '✓' not in html

    def test_to_html_replaces_warning_via_preprocess(self) -> None:
        html = _to_html('⚠ Attention')
        assert '(!)' in html
        assert '⚠' not in html

    # ------------------------------------------------------------------
    # _read_readme
    # ------------------------------------------------------------------

    def test_read_readme_returns_file_content(self, tmp_path: Path) -> None:
        year_dir = tmp_path / '2024'
        year_dir.mkdir()
        (year_dir / 'README.md').write_text('# Test', encoding='utf-8')

        assert _read_readme(tmp_path, 2024) == '# Test'

    def test_read_readme_exits_with_code_1_when_file_missing(self, tmp_path: Path) -> None:
        assert _exits_with_code(_read_readme, tmp_path, 2099) == 1

    # ------------------------------------------------------------------
    # _find_browser
    # ------------------------------------------------------------------

    def test_find_browser_raises_when_no_browser_found(self, monkeypatch) -> None:
        monkeypatch.setattr('md_to_pdf._BROWSER_PATHS', [])
        with pytest.raises(RuntimeError, match="No supported browser"):
            _find_browser()

    def test_find_browser_returns_first_existing_path(self, tmp_path: Path, monkeypatch) -> None:
        browser = tmp_path / 'msedge.exe'
        browser.touch()
        monkeypatch.setattr('md_to_pdf._BROWSER_PATHS', [str(browser), str(tmp_path / 'chrome.exe')])
        assert _find_browser() == str(browser)

    def test_find_browser_skips_nonexistent_paths(self, tmp_path: Path, monkeypatch) -> None:
        browser = tmp_path / 'chrome.exe'
        browser.touch()
        monkeypatch.setattr('md_to_pdf._BROWSER_PATHS', [str(tmp_path / 'missing.exe'), str(browser)])
        assert _find_browser() == str(browser)

    # ------------------------------------------------------------------
    # Integration — requires Edge or Chrome
    # ------------------------------------------------------------------

    @pytest.mark.skipif(not _browser_available, reason="No Edge or Chrome browser installed")
    def test_write_pdf_output_is_valid_pdf(self, tmp_path: Path) -> None:
        output = tmp_path / 'rapport-2024.pdf'
        _write_pdf(_to_html(_SAMPLE_MARKDOWN), output)
        assert output.read_bytes().startswith(b'%PDF')

    @pytest.mark.skipif(not _browser_available, reason="No Edge or Chrome browser installed")
    def test_convert_creates_rapport_year_pdf_next_to_readme(self, tmp_path: Path) -> None:
        year_dir = tmp_path / '2024'
        year_dir.mkdir()
        (year_dir / 'README.md').write_text(_SAMPLE_MARKDOWN, encoding='utf-8')

        result = _convert(tmp_path, 2024)

        assert result == tmp_path / '2024' / 'rapport-2024.pdf'
        assert result.read_bytes().startswith(b'%PDF')
