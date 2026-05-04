#!/usr/bin/env python3
"""
unified_readme.py — Récapitulatif fiscal unifié Yuh + Wise pour une année donnée.

Lit les CSV produits par yuh_csv_ifu.py et wise_csv_ifu.py et produit
un tableau par formulaire avec les montants exacts à saisir en ligne.

Usage:
    python3 src/unified_readme.py <année> [--ifu-root <dossier>]
                                  [--de-ruyter-periods JSON_OU_FICHIER]
                                  [-s | -f | -ff | -cldp [--penalty-scenario ...] [--declaration-deadline YYYY-MM-DD]]

Prérequis :
    Avoir exécuté yuh_csv_ifu.py et/ou wise_csv_ifu.py au préalable.

Produit :
    ifu-new/<année>/README.md  — valeurs à saisir par formulaire (2074, 2042)
"""
import argparse
import csv
import math
import sys
from datetime import date, datetime
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from de_ruyter import DeRuyterConfig, pfu_rate_label, load_de_ruyter_arg


# ---------------------------------------------------------------------------
# Lecture des CSV produits par les scripts broker
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def _f(s: str) -> float:
    try:
        return float(s.strip().replace('+', '').replace(' ', ''))
    except (ValueError, AttributeError):
        return 0.0


def sum_col(rows: list[dict], col: str) -> float:
    return sum(_f(r[col]) for r in rows if col in r)


# ---------------------------------------------------------------------------
# Calcul gains × taux PFU par source
# ---------------------------------------------------------------------------

def _row_tax_and_gain(
    row: dict,
    date_col: str,
    gain_col: str,
    de_ruyter: DeRuyterConfig,
) -> tuple[str, float, float]:
    """Returns (rate_label, gain_eur, tax_eur) for one gain row."""
    tx_date = date.fromisoformat(row[date_col])
    rate = de_ruyter.pfu_rate_on(tx_date)
    gain = _f(row[gain_col])
    rounded = _f(row.get('Montant arrondi EUR', '0'))
    tax = rounded * rate if rounded > 0 else 0.0
    return pfu_rate_label(rate), gain, tax


def _group_gains(
    rows: list[dict],
    date_col: str,
    gain_col: str,
    de_ruyter: DeRuyterConfig,
) -> dict[str, dict]:
    """Group gain rows by rate label → {'gain': float, 'tax': float}."""
    result: dict[str, dict] = {}
    for row in rows:
        if date_col not in row or gain_col not in row:
            continue
        rate_label, gain, tax = _row_tax_and_gain(row, date_col, gain_col, de_ruyter)
        entry = result.setdefault(rate_label, {'gain': 0.0, 'tax': 0.0})
        entry['gain'] += gain
        entry['tax'] += tax
    return result


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Récapitulatif fiscal unifié Yuh + Wise — valeurs à saisir par formulaire.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('year', type=int, help='Année fiscale cible (ex. 2024)')
    parser.add_argument('--ifu-root', default='ifu-new',
                        help="Dossier racine des sorties broker (défaut: 'ifu-new')")
    parser.add_argument('--de-ruyter-periods',
                        default=None,
                        metavar='JSON_OU_FICHIER',
                        help=(
                            "Périodes de travail en Suisse (LAMal). "
                            "Chemin vers un fichier JSON ou JSON inline. "
                            "Si absent : utilise src/config/de_ruyter_periods.json "
                            "(ou PFU 30 %% si le fichier n'existe pas)."
                        ))
    parser.add_argument('--calculate-late-declaration-penalties', '-cldp',
                        action='store_true')
    parser.add_argument('--penalty-scenario',
                        choices=['spontaneous', 'formal', 'fraud'],
                        default='spontaneous')
    parser.add_argument('--declaration-deadline', default=None, metavar='YYYY-MM-DD')
    parser.add_argument('-s', action='store_true', dest='penalty_s')
    parser.add_argument('-f', action='store_true', dest='penalty_f')
    parser.add_argument('-ff', action='store_true', dest='penalty_ff')
    args = parser.parse_args()

    if args.penalty_ff:
        args.calculate_late_declaration_penalties = True
        args.penalty_scenario = 'fraud'
    elif args.penalty_f:
        args.calculate_late_declaration_penalties = True
        args.penalty_scenario = 'formal'
    elif args.penalty_s:
        args.calculate_late_declaration_penalties = True
        args.penalty_scenario = 'spontaneous'

    de_ruyter = load_de_ruyter_arg(args.de_ruyter_periods)

    year = args.year
    root = Path(args.ifu_root)

    yuh_dir  = root / str(year) / 'yuh'
    wise_dir = root / str(year) / 'wise'
    out_dir  = root / str(year)

    # --- Gains 2074 ---
    yuh_gains  = _read_csv(yuh_dir  / f'{year}_gains_2074.csv')
    wise_gains = _read_csv(wise_dir / f'{year}_gains_2074.csv')

    yuh_groups  = _group_gains(yuh_gains,  'Date cession', 'Plus/moins-value EUR (PMP)', de_ruyter)
    wise_groups = _group_gains(wise_gains, 'Date cession', 'Plus/moins-value EUR (PMP)', de_ruyter)

    all_rate_labels = sorted(set(yuh_groups) | set(wise_groups))
    combined_groups: dict[str, dict] = {
        rate_label: {
            'gain': yuh_groups.get(rate_label, {'gain': 0.0, 'tax': 0.0})['gain']
                    + wise_groups.get(rate_label, {'gain': 0.0, 'tax': 0.0})['gain'],
            'tax':  yuh_groups.get(rate_label, {'gain': 0.0, 'tax': 0.0})['tax']
                    + wise_groups.get(rate_label, {'gain': 0.0, 'tax': 0.0})['tax'],
        }
        for rate_label in all_rate_labels
    }
    total_gain = sum(v['gain'] for v in combined_groups.values())
    total_tax  = sum(v['tax']  for v in combined_groups.values())
    mixed_rates = len(all_rate_labels) > 1

    # --- Gains 2086 (informatif Yuh uniquement) ---
    yuh_gains_2086 = _read_csv(yuh_dir / f'{year}_gains_2086.csv')
    yuh_2086 = sum_col(yuh_gains_2086, 'Plus/moins-value EUR')
    yuh_2086_proceeds = sum_col(yuh_gains_2086, 'Prix de cession EUR')

    # --- Dividendes 2042 (Yuh uniquement — Wise fonds capitalisants) ---
    yuh_divs = _read_csv(yuh_dir / f'{year}_dividendes.csv')
    divs_2dc = [r for r in yuh_divs if '2DC' in r.get('Ligne 2042', '')]
    divs_2tr = [r for r in yuh_divs if '2TR' in r.get('Ligne 2042', '')]
    total_2dc = sum_col(divs_2dc, 'Montant EUR')
    total_2tr = sum_col(divs_2tr, 'Montant EUR')
    total_2ab = sum_col(yuh_divs, 'Retenue à la source EUR (zone AA)')

    # --- Frais Wise (informatif) ---
    wise_fees = _read_csv(wise_dir / f'{year}_fees.csv')
    total_fees = sum_col(wise_fees, 'Montant EUR')

    sources = []
    if yuh_gains or yuh_divs:
        sources.append('Yuh')
    if wise_gains or wise_fees:
        sources.append('Wise')

    if not sources:
        print(
            f"Aucune donnée trouvée pour {year}.\n"
            f"Attendu dans : {yuh_dir}  et/ou  {wise_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n📋 Sources : {', '.join(sources)}")

    # ===================================================================
    # Construction du README
    # ===================================================================

    md: list[str] = []

    def h(text: str) -> None:
        print(text)
        md.append(text)

    today = datetime.now().strftime('%Y-%m-%d')
    h(f"# Déclaration fiscale {year} — Valeurs à saisir")
    h(f"\n> Généré le {today} · Sources : {', '.join(sources)}\n")

    # --- Formulaire 2074 ---
    pfu_note = " — de Ruyter actif" if de_ruyter.is_active() else ""
    h(f"## Formulaire 2074 — Plus/moins-values valeurs mobilières{pfu_note}\n")

    if yuh_gains or wise_gains:
        rounded = round(total_gain)
        box = "**3VG**" if rounded >= 0 else "**3VH**"

        h("| Source | Taux PFU | Gain/perte EUR | Impôt estimé |")
        h("|--------|----------|---------------|-------------|")
        for rate_label in all_rate_labels:
            if rate_label in yuh_groups:
                g = yuh_groups[rate_label]
                tax_str = f"{g['tax']:.2f} €" if g['gain'] > 0 else "—"
                h(f"| Yuh  | {rate_label} | {g['gain']:+.2f} € | {tax_str} |")
            if rate_label in wise_groups:
                g = wise_groups[rate_label]
                tax_str = f"{g['tax']:.2f} €" if g['gain'] > 0 else "—"
                h(f"| Wise | {rate_label} | {g['gain']:+.2f} € | {tax_str} |")
        h(f"| **Total** | | **{total_gain:+.2f} €** | **{total_tax:.2f} €** |")
        h(f"\n> Impôt estimé = Σ (Montant arrondi EUR × Taux PFU) par cession.")

        h(f"\n→ Saisir **{rounded:+d} €** en case {box}")
        if rounded >= 0:
            h("\n> Plus-value : case **3VG** du formulaire 2074 (et 2042 C ligne 3VG).")
        else:
            h("\n> Moins-value : case **3VH** du formulaire 2074 (imputable sur gains futurs).")
        if de_ruyter.is_active():
            h("\n> Régime de Ruyter : taux PFU réduit à **20,3 %** sur les cessions réalisées "
              "durant les périodes de travail en Suisse (LAMal). "
              "Exonération CSG (9,2 %) + CRDS (0,5 %). "
              "Le montant à saisir en 3VG reste le total brut — la réduction s'applique "
              "lors du calcul des prélèvements sociaux.")
    else:
        h(f"Aucune cession en {year} — rien à déclarer.")

    if args.calculate_late_declaration_penalties and (yuh_gains or wise_gains) and total_gain > 0:
        _RATES = {
            'spontaneous': (0.10, "correction spontanée avant mise en demeure"),
            'formal':      (0.40, "après mise en demeure"),
            'fraud':       (0.80, "manœuvres frauduleuses"),
        }
        penalty_rate, scenario_label = _RATES[args.penalty_scenario]
        if args.declaration_deadline:
            deadline = datetime.strptime(args.declaration_deadline, '%Y-%m-%d').date()
        else:
            deadline = date(year + 1, 6, 1)
        today_date = date.today()
        months_delay = (
            math.ceil((today_date - deadline).days / 30.4375) if today_date > deadline else 0
        )
        tax_owed = round(total_tax)
        late_interest = round(tax_owed * 0.002 * months_delay)
        surcharge = round(tax_owed * penalty_rate)
        total_due = tax_owed + late_interest + surcharge

        h(f"\n## Pénalités de déclaration tardive — Formulaire 2074\n")
        h(f"> Scénario : **{scenario_label}** · "
          f"Délai : **{months_delay} mois** "
          f"(échéance : {deadline.isoformat()}, calcul au {today_date.isoformat()})\n")
        h("| | Montant |")
        h("|---|---------|")
        for rate_label in all_rate_labels:
            grp = combined_groups[rate_label]
            gain_at_rate = round(grp['gain'])
            tax_at_rate = round(grp['tax'])
            h(f"| Plus-value nette (arrondie, case 3VG) ({rate_label}) | {gain_at_rate:+d} € |")
            h(f"| Impôt dû ({rate_label}) | {tax_at_rate} € |")
        if mixed_rates:
            h(f"| **Impôt dû total** | **{tax_owed} €** |")
        h(f"| Intérêts de retard (0,20 % × {months_delay} mois) | {late_interest} € |")
        h(f"| Majoration ({penalty_rate * 100:.0f} %) | {surcharge} € |")
        h(f"| **Total estimé à régulariser** | **{total_due} €** |\n")
        h("> ⚠ Estimation indicative — consultez votre Service des Impôts des Particuliers (SIP) ou un conseiller fiscal.")

    # --- Formulaire 2086 informatif ---
    if yuh_gains_2086:
        h("\n## Formulaire 2086 — ⚠ Informatif seulement (crypto-ETPs Yuh)\n")
        rounded_2086 = round(yuh_2086)
        box_2086 = "3AN" if rounded_2086 >= 0 else "3BN"
        h("| | Valeur |")
        h("|---|-------|")
        h(f"| Plus/moins-value | {yuh_2086:+.2f} € |")
        h(f"| Cessions totales | {yuh_2086_proceeds:.2f} € |")
        if yuh_2086_proceeds <= 305.0:
            h(f"\n→ Cessions ≤ 305 € → **EXONÉRÉ** — rien à saisir.")
        else:
            h(f"\n→ Saisir **{rounded_2086:+d} €** en case **{box_2086}** si la DGFiP requalifie en actifs numériques.")
        h("\n> Classification retenue : valeurs mobilières (form. 2074). "
          "Ce bloc est produit à titre précautionnel uniquement.")

    # --- Formulaire 2042 — Dividendes ---
    h("\n## Formulaire 2042 — Dividendes / Distributions\n")

    if yuh_divs:
        h("| Case | Description | Montant EUR | Arrondi | À saisir |")
        h("|------|-------------|------------|---------|----------|")
        if divs_2dc:
            h(f"| **2DC** | Distributions éligibles abattement 40 % (ISIN FR) "
              f"| {total_2dc:.2f} | {round(total_2dc):+d} € | ✓ |")
        if divs_2tr:
            h(f"| **2TR** | Distributions non éligibles (étrangères) "
              f"| {total_2tr:.2f} | {round(total_2tr):+d} € | ✓ |")
        if total_2ab > 0:
            h(f"| **2AB** | Retenue à la source étrangère (zone AA) "
              f"| {total_2ab:.2f} | {round(total_2ab):+d} € | ✓ |")
        else:
            h("| **2AB** | Retenue à la source (zone AA) | 0.00 | 0 € | — (néant) |")
        h(f"\n> Base prélèvements sociaux (zone DQ) : **{round(total_2dc + total_2tr):+d} €**")
    else:
        h("Aucun dividende Yuh pour cette année.")

    if wise_fees:
        h("\n> Wise Assets : fonds capitalisants — aucune distribution à déclarer.")

    # --- Frais Wise informatifs ---
    if wise_fees:
        h(f"\n## Frais de gestion Wise — informatif\n")
        h(f"Total {year} : **{total_fees:.2f} EUR** — "
          f"non déductibles (art. 150-0 D CGI), aucune saisie requise.")

    # --- Formulaire 3916 ---
    h("\n## Formulaire 3916 — Comptes étrangers\n")
    accounts = []
    if 'Yuh' in sources:
        accounts.append("Yuh / Swissquote (Suisse)")
    if 'Wise' in sources:
        accounts.append("Wise (Belgique)")
    for acc in accounts:
        h(f"- [ ] Déclarer le compte **{acc}**")
    h("\n> 1 500 € d'amende par compte non déclaré.")

    # --- Rappels ---
    h("\n## Rappels\n")
    h("- **ETFs capitalisants** : imposition uniquement à la cession.")
    h("- **Méthode PMP** : les montants ci-dessus sont calculés selon l'art. 150-0 D CGI. "
      "Le relevé fiscal annuel Wise utilise FIFO — les montants peuvent différer.")
    h(f"- **Conserver les CSV 10 ans** (durée de reprise fiscale).")

    # --- Écriture ---
    out_dir.mkdir(parents=True, exist_ok=True)
    out_readme = out_dir / 'README.md'
    out_readme.write_text('\n'.join(md), encoding='utf-8')
    print(f"\n📝 Récapitulatif          → {out_readme}\n")


if __name__ == '__main__':
    main()
