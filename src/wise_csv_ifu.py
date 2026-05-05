#!/usr/bin/env python3
"""
wise_csv_ifu.py — Calcule l'équivalent d'un IFU à partir des exports CSV Wise Assets
pour la déclaration fiscale française (résident fiscal français, frontalier).

Usage:
    python3 src/wise_csv_ifu.py <année> [--transactions-folder <dossier>] [--cache <fichier_fx>]

Produit (ifu/wise/<année>/) :
    - <année>_transactions.csv  : opérations de l'année avec conversion EUR
    - <année>_gains_2074.csv    : plus/moins-values (formulaire 2074)
    - <année>_dividendes.csv    : dividendes / distributions (vide — fonds capitalisants)
    - <année>_fees.csv          : frais de gestion mensuels (non déductibles en PFU)
    - <année>_summary.csv       : positions et PMP au 31/12 de l'année cible
    - <année>_fx_log.csv        : journal des taux BCE utilisés

Input : fichiers `wise_assets_statement_*.csv` dans `--transactions-folder`.

Colonnes CSV Wise Assets :
    Traded Asset ID Type | Traded Asset ID Value | Execution Date | Transaction Type |
    Traded Units | Asset Base Currency | Asset Base Currency Unit Price Amount |
    Asset Base Currency Value Traded | Settlement Date | Settlement Currency |
    Settlement Amount | Settlement Conversion Rate | Settlement Conversion Rate Timestamp |
    Legal Entity | Wise ID

Hypothèses :
    - Transaction Type BUY  : coût = Settlement Amount (en Settlement Currency).
    - Transaction Type SELL : produit = Settlement Amount.
    - Transaction Type FEE_CHARGE : frais de gestion mensuel — journalisé séparément,
      NON inclus dans le prix de revient (pas un frais d'acquisition au sens de
      l'art. 150-0 D CGI sous PFU).
    - Date retenue = date de l'Execution Date (stripped to UTC date).
      Pour FEE_CHARGE (pas d'Execution Date) : date du Settlement Date.
    - Méthode PMP (art. 150-0 D CGI) recomputed depuis les transactions brutes.
    - Taux de change BCE via api.frankfurter.dev si Settlement Currency ≠ EUR.
      En pratique Wise Assets est tout en EUR (taux=1,0000).
    - Tous les CSV disponibles sont lus pour un PMP exact sur l'historique complet.
      Contrairement au PDF fiscal Wise, le CSV INCLUT les achats de positions
      non cédées à la fin de l'année.

Dépendances :
    pip install requests
"""
import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from fx_cache import FXCache
from de_ruyter import DeRuyterConfig, pfu_rate_label, load_de_ruyter_arg


# ---------------------------------------------------------------------------
# Fonds Wise connus (ISIN → nom canonique)
# Ajouter tout nouveau fonds ici.
# ---------------------------------------------------------------------------
WISE_FUNDS: dict[str, str] = {
    'IE00B41N0724': 'EUR Interest fund',  # BlackRock ICS EUR Liquidity Fund (Irlande)
    'LU0852473015': 'Stocks fund',        # iShares World Equity Index Fund / MSCI World (Luxembourg)
}


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------
@dataclass
class WiseTx:
    row_id: str
    date: date
    type: str              # 'buy' | 'sell'
    isin: str
    fund_name: str
    quantity: float        # toujours positif (direction donnée par type)
    price_native: float    # prix unitaire en devise native
    amount_native: float   # Settlement Amount (toujours positif)
    currency: str          # Settlement Currency
    fx_rate: float         # taux Settlement Conversion Rate (ou BCE si recalculé)
    fx_date_used: str      # date BCE utilisée
    total_eur: float       # montant en EUR (positif pour buy ET sell — signe géré par type)


@dataclass
class WiseFee:
    date: date
    currency: str
    amount_native: float   # positif (valeur absolue)
    fx_rate: float
    total_eur: float       # positif (valeur absolue)


# ---------------------------------------------------------------------------
# Parsing CSV Wise Assets
# ---------------------------------------------------------------------------

def _parse_dt(s: str) -> date:
    """Parse ISO 8601 UTC datetime → date locale (UTC+0 → date)."""
    s = s.strip()
    if not s:
        raise ValueError("Date vide")
    # Remplace 'Z' par '+00:00' pour fromisoformat (Python < 3.11)
    s = s.replace('Z', '+00:00')
    return datetime.fromisoformat(s).astimezone(timezone.utc).date()


def _f(s: str) -> float:
    s = s.strip()
    return float(s) if s else 0.0


def parse_wise_csv(csv_path: Path) -> tuple[list[WiseTx], list[WiseFee]]:
    """
    Parse un fichier wise_assets_statement_*.csv.
    Retourne (transactions, frais_gestion).
    """
    transactions: list[WiseTx] = []
    fees: list[WiseFee] = []
    unknown_isins: set[str] = set()
    row_counter = 0

    with csv_path.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            tx_type = row['Transaction Type'].strip()

            # ---- Frais de gestion mensuels ----
            if tx_type == 'FEE_CHARGE':
                try:
                    fee_date = _parse_dt(row['Settlement Date'])
                except ValueError:
                    print(f"  ⚠ FEE_CHARGE ligne {i+2} : date invalide — ignorée",
                          file=sys.stderr)
                    continue
                amount = _f(row['Settlement Amount'])
                currency = row['Settlement Currency'].strip()
                fees.append(WiseFee(
                    date=fee_date,
                    currency=currency,
                    amount_native=amount,
                    fx_rate=_f(row['Settlement Conversion Rate']) or 1.0,
                    total_eur=amount,   # Settlement Currency est EUR dans les données connues
                ))
                print(f"  💳 {fee_date} frais  {amount:>7.2f} {currency}")
                continue

            # ---- Ordres d'investissement BUY / SELL ----
            if tx_type not in ('BUY', 'SELL'):
                print(f"  ⚠ Type inconnu ligne {i+2} : {tx_type!r} — ignoré",
                      file=sys.stderr)
                continue

            isin = row['Traded Asset ID Value'].strip()
            if not isin:
                print(f"  ⚠ Ligne {i+2} {tx_type} sans ISIN — ignorée", file=sys.stderr)
                continue
            if isin not in WISE_FUNDS and isin not in unknown_isins:
                print(f"  ⚠ ISIN inconnu : {isin!r} — ajoutez-le dans WISE_FUNDS",
                      file=sys.stderr)
                unknown_isins.add(isin)

            try:
                exec_date = _parse_dt(row['Execution Date'])
            except ValueError:
                print(f"  ⚠ Ligne {i+2} {tx_type} : Execution Date invalide — ignorée",
                      file=sys.stderr)
                continue

            quantity = _f(row['Traded Units'])
            price = _f(row['Asset Base Currency Unit Price Amount'])
            amount = _f(row['Settlement Amount'])
            currency = row['Settlement Currency'].strip()
            fx_rate = _f(row['Settlement Conversion Rate']) or 1.0
            row_counter += 1
            row_id = f"{exec_date.isoformat()}_{isin}_{tx_type.lower()}_{row_counter}"
            fund_name = WISE_FUNDS.get(isin, isin)

            label = '✓' if tx_type == 'BUY' else '↩'
            print(f"  {label} {exec_date} {tx_type:4s} {isin} "
                  f"{fund_name[:28]:28s} {quantity:>12.6f} × {price:>8.4f} {currency}"
                  f"  → {amount:>9.2f} EUR")

            transactions.append(WiseTx(
                row_id=row_id,
                date=exec_date,
                type='buy' if tx_type == 'BUY' else 'sell',
                isin=isin,
                fund_name=fund_name,
                quantity=quantity,
                price_native=price,
                amount_native=amount,
                currency=currency,
                fx_rate=fx_rate,
                fx_date_used=exec_date.isoformat(),
                total_eur=amount,  # recalculé via FXCache si currency ≠ EUR
            ))

    return transactions, fees


# ---------------------------------------------------------------------------
# Conversion FX (si Settlement Currency ≠ EUR)
# ---------------------------------------------------------------------------

def apply_fx(txs: list[WiseTx], fees: list[WiseFee],
             fx: FXCache) -> list[dict]:
    """
    Applique les taux BCE pour les transactions non-EUR.
    Retourne le journal FX (pour le CSV fx_log).
    """
    fx_log: list[dict] = []
    for tx in txs:
        if tx.currency == 'EUR':
            # Taux déjà 1.0 ; pas de requête BCE nécessaire
            continue
        try:
            rate, bce_date = fx.get(tx.date, tx.currency)
            tx.fx_rate = rate
            tx.fx_date_used = bce_date
            tx.total_eur = round(tx.amount_native * rate, 4)
            fx_log.append({
                'date_demandée': tx.date.isoformat(),
                'date_BCE_utilisée': bce_date,
                'devise': tx.currency,
                'taux_vers_EUR': rate,
                'même_date': 'oui' if tx.date.isoformat() == bce_date else 'non',
                'row_id': tx.row_id,
            })
        except Exception as e:
            print(f"  ⚠ Erreur FX {tx.date} ({tx.currency}): {e}", file=sys.stderr)
            sys.exit(2)
    for fee in fees:
        if fee.currency != 'EUR':
            try:
                rate, _ = fx.get(fee.date, fee.currency)
                fee.fx_rate = rate
                fee.total_eur = round(fee.amount_native * rate, 4)
            except Exception as e:
                print(f"  ⚠ Erreur FX frais {fee.date}: {e}", file=sys.stderr)
    return fx_log


# ---------------------------------------------------------------------------
# Calcul PMP (art. 150-0 D CGI)
# ---------------------------------------------------------------------------

def compute_pmp_gains(txs: list[WiseTx]) -> dict:
    """
    Calcule les plus/moins-values en PMP sur l'ensemble des transactions triées.
    Le CSV Wise inclut tous les achats (y compris positions non cédées) → PMP exact.
    """
    txs_sorted = sorted(txs, key=lambda t: (t.date, t.row_id))
    positions: dict[str, dict] = {}

    for tx in txs_sorted:
        p = positions.setdefault(tx.isin, {
            'name': tx.fund_name,
            'quantity': 0.0,
            'total_cost_eur': 0.0,
            'realized_gains': [],
        })

        if tx.type == 'buy':
            p['quantity'] += tx.quantity
            p['total_cost_eur'] += tx.total_eur

        elif tx.type == 'sell':
            qty_sold = tx.quantity
            if p['quantity'] < qty_sold - 1e-7:
                print(f"  ⚠ Vente sans position suffisante : {tx.isin} le {tx.date} "
                      f"(position={p['quantity']:.7f}, vendu={qty_sold:.7f})",
                      file=sys.stderr)
                continue

            pmp = p['total_cost_eur'] / p['quantity'] if p['quantity'] > 0 else 0.0
            cost_basis = pmp * qty_sold
            gain = tx.total_eur - cost_basis

            p['realized_gains'].append({
                'date': tx.date.isoformat(),
                'row_id': tx.row_id,
                'quantity': qty_sold,
                'proceeds_eur': tx.total_eur,
                'cost_basis_eur': cost_basis,
                'pmp_eur': pmp,
                'gain_eur': gain,
            })
            p['quantity'] -= qty_sold
            p['total_cost_eur'] -= cost_basis
            if abs(p['quantity']) < 1e-9:
                p['quantity'] = 0.0
                p['total_cost_eur'] = 0.0

    return positions


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="IFU Wise Assets (CSV) — recompute PMP for French residents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('year', type=int, help='Année fiscale cible (ex. 2024)')
    parser.add_argument('--transactions-folder', '-tf', default='transactions',
                        help="Dossier contenant les CSV Wise (défaut: 'transactions')")
    parser.add_argument('--cache', default='fx_cache.json',
                        help="Fichier cache taux BCE (défaut: fx_cache.json)")
    parser.add_argument('--calculate-late-declaration-penalties', '-cldp',
                        action='store_true')
    parser.add_argument('--penalty-scenario',
                        choices=['spontaneous', 'formal', 'fraud'],
                        default='spontaneous')
    parser.add_argument('--declaration-deadline', default=None, metavar='YYYY-MM-DD')
    parser.add_argument('-s', action='store_true', dest='penalty_s')
    parser.add_argument('-f', action='store_true', dest='penalty_f')
    parser.add_argument('-ff', action='store_true', dest='penalty_ff')
    parser.add_argument('--out', default='ifu-new',
                        help="Dossier racine pour les fichiers de sortie (défaut: 'ifu-new')")
    parser.add_argument('--de-ruyter-periods',
                        default=None,
                        metavar='JSON_OU_FICHIER',
                        help=(
                            "Périodes de travail en Suisse (LAMal) pour le régime de Ruyter. "
                            "Chemin vers un fichier JSON ou JSON inline. "
                            "Si absent : utilise src/config/de_ruyter_periods.json "
                            "(ou PFU standard 30 %% si le fichier n'existe pas)."
                        ))
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

    target_year = args.year
    folder = Path(args.transactions_folder)
    out_dir = Path(args.out) / str(target_year) / 'wise'
    out_dir.mkdir(parents=True, exist_ok=True)

    if not folder.is_dir():
        print(f"Dossier introuvable : {folder}", file=sys.stderr)
        sys.exit(1)

    all_csvs = sorted(folder.glob('wise_assets_statement_*.csv'))
    if not all_csvs:
        print(f"Aucun fichier wise_assets_statement_*.csv dans {folder}", file=sys.stderr)
        sys.exit(1)

    # Le CSV de l'année cible doit exister
    target_csvs = [p for p in all_csvs if str(target_year) in p.name]
    if not target_csvs:
        print(f"Aucun CSV Wise pour {target_year} dans {folder}", file=sys.stderr)
        sys.exit(1)

    # --- Parsing de tous les CSV (historique complet pour PMP exact) ---
    all_txs: list[WiseTx] = []
    all_fees: list[WiseFee] = []

    for csv_path in all_csvs:
        print(f"\n📄 Lecture {csv_path.name} ...")
        txs, fees = parse_wise_csv(csv_path)
        all_txs.extend(txs)
        all_fees.extend(fees)

    if not all_txs:
        print("Aucune transaction BUY/SELL exploitable.", file=sys.stderr)
        sys.exit(1)

    year_txs = [t for t in all_txs if t.date.year == target_year]
    year_fees = [f for f in all_fees if f.date.year == target_year]

    if not year_txs and not year_fees:
        print(f"Aucune opération pour {target_year}.", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Total chargé : {len(all_txs)} opérations, "
          f"{len(year_txs)} pour {target_year}")

    # --- FX ---
    print(f"\n💱 Vérification des taux BCE (cache: {args.cache})...")
    fx = FXCache(Path(args.cache))
    fx_log = apply_fx(all_txs, all_fees, fx)
    # Log EUR transactions trop (pour exhaustivité)
    for tx in all_txs:
        if tx.currency == 'EUR' and tx.date.year == target_year:
            fx_log.append({
                'date_demandée': tx.date.isoformat(),
                'date_BCE_utilisée': tx.date.isoformat(),
                'devise': 'EUR',
                'taux_vers_EUR': 1.0,
                'même_date': 'oui',
                'row_id': tx.row_id,
            })
    print(f"  ✓ {len(all_txs)} transactions vérifiées")

    # --- Calcul PMP (tout l'historique) ---
    positions = compute_pmp_gains(all_txs)

    # Cessions de l'année cible
    gains_2074 = []
    for isin, p in positions.items():
        for g in p['realized_gains']:
            if g['date'][:4] == str(target_year):
                gains_2074.append({**g, 'isin': isin, 'name': p['name']})

    # Positions au 31/12 de l'année cible
    last_day = date(target_year, 12, 31)
    positions_eoy = compute_pmp_gains(
        [t for t in all_txs if t.date <= last_day]
    )

    # ===================================================================
    # SORTIES CSV
    # ===================================================================

    def out(name: str) -> Path:
        return out_dir / f'{target_year}_{name}'

    # Journal FX
    fx_csv = out('fx_log.csv')
    with fx_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'date_demandée', 'date_BCE_utilisée', 'devise',
            'taux_vers_EUR', 'même_date', 'row_id',
        ])
        writer.writeheader()
        writer.writerows(fx_log)
    print(f"\n📊 Journal taux BCE       → {fx_csv}")

    # Transactions de l'année
    tx_csv = out('transactions.csv')
    with tx_csv.open('w', newline='', encoding='utf-8') as f:
        if year_txs:
            fields = list(asdict(year_txs[0]).keys())
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for tx in sorted(year_txs, key=lambda t: t.date):
                row = asdict(tx)
                row['date'] = tx.date.isoformat()
                writer.writerow(row)
    print(f"📊 Transactions           → {tx_csv}")

    # Dividendes (vide — fonds capitalisants)
    div_csv = out('dividendes.csv')
    with div_csv.open('w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(['Date', 'ISIN', 'Fonds', 'Montant EUR', 'Note'])
    print(f"📊 Dividendes             → {div_csv}  (vide — fonds capitalisants)")

    # Frais de gestion
    fees_csv = out('fees.csv')
    with fees_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Date', 'Devise', 'Montant', 'Taux de change', 'Montant EUR', 'Note fiscale',
        ])
        for fee in sorted(year_fees, key=lambda x: x.date):
            writer.writerow([
                fee.date.isoformat(), fee.currency,
                f"{fee.amount_native:.2f}", f"{fee.fx_rate:.4f}",
                f"{fee.total_eur:.2f}",
                'Frais de gestion courants — non déductibles (art. 150-0 D CGI : seuls les frais d\'acquisition sont inclus dans le prix de revient ; même règle sous barème progressif)',
            ])
    total_fees = sum(f.total_eur for f in year_fees)
    print(f"📊 Frais de gestion       → {fees_csv}  ({total_fees:.2f} EUR)")

    # Cessions 2074
    gains_csv = out('gains_2074.csv')
    with gains_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Date cession', 'ID', 'ISIN', 'Fonds',
            'Quantité cédée', 'Prix de cession EUR',
            'Prix de revient PMP EUR', 'PMP EUR/part',
            'Plus/moins-value EUR (PMP)', 'Montant arrondi EUR',
            'Taux PFU',
        ])
        for g in sorted(gains_2074, key=lambda x: x['date']):
            gain_pfu_rate = de_ruyter.pfu_rate_on(date.fromisoformat(g['date']))
            writer.writerow([
                g['date'], g['row_id'], g['isin'], g['name'],
                f"{g['quantity']:.7f}",
                f"{g['proceeds_eur']:.2f}",
                f"{g['cost_basis_eur']:.2f}",
                f"{g['pmp_eur']:.4f}",
                f"{g['gain_eur']:+.2f}",
                f"{round(g['gain_eur']):+d}",
                f"{gain_pfu_rate}",
            ])
    print(f"📊 Cessions (form. 2074)  → {gains_csv}")

    # Positions au 31/12
    summary_csv = out('summary.csv')
    with summary_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'ISIN', 'Fonds', 'Quantité détenue',
            'Coût total EUR (PMP)', 'PMP EUR/part',
            'Plus-values réalisées EUR', 'Formulaire',
        ])
        for isin, p in positions_eoy.items():
            total_realized = sum(
                g['gain_eur'] for g in p['realized_gains']
                if g['date'][:4] == str(target_year)
            )
            pmp = (p['total_cost_eur'] / p['quantity'] if p['quantity'] > 0 else 0.0)
            writer.writerow([
                isin, p['name'],
                f"{p['quantity']:.7f}",
                f"{p['total_cost_eur']:.2f}",
                f"{pmp:.4f}",
                f"{total_realized:+.2f}",
                '2074',
            ])
    print(f"📊 Positions au 31/12/{target_year} → {summary_csv}")

    # ===================================================================
    # RÉCAPITULATIF CONSOLE + README.md
    # ===================================================================

    md: list[str] = []

    def h(text: str) -> None:
        print(text)
        md.append(text)

    h(f"\n# Déclaration fiscale {target_year} — Wise Assets")
    h(f"\n> Généré le {datetime.now().strftime('%Y-%m-%d')} "
      f"· PMP calculé sur {len(all_csvs)} fichier(s) CSV · méthode art. 150-0 D CGI\n")

    if de_ruyter.is_active():
        h("## Régime de Ruyter\n")
        h("Exonération CSG (9,2 %) et CRDS (0,5 %) sur les revenus de cession "
          "durant les périodes de travail en Suisse (LAMal).\n")
        h("Taux PFU réduit : **20,3 %** (7,5 % solidarité + 12,8 % IR) "
          "au lieu de **30,0 %** (17,2 % prélèvements sociaux + 12,8 % IR).\n")
        h("| Début | Fin | Type | Taux PFU |")
        h("|-------|-----|------|----------|")
        for period_raw in de_ruyter.periods_as_raw():
            fin = period_raw['end_date'] or 'ouvert'
            period_type = period_raw.get('type', 'switzerland')
            type_label = 'Suisse' if period_type == 'switzerland' else 'France'
            rate_lbl = '20,3 %' if period_type == 'switzerland' else '30,0 %'
            h(f"| {period_raw['start_date']} | {fin} | {type_label} | {rate_lbl} |")
        h("")

    # -- Gains 2074 --
    net_gain = sum(g['gain_eur'] for g in gains_2074)
    total_proceeds = sum(g['proceeds_eur'] for g in gains_2074)
    total_cost_sold = sum(g['cost_basis_eur'] for g in gains_2074)

    pfu_titre = "de Ruyter actif" if de_ruyter.is_active() else "PFU 30 %"
    h(f"## Formulaire 2074 — Valeurs mobilières ({pfu_titre})")
    h("Plus-value nette → case 3VG | Moins-value → case 3VH\n")

    if gains_2074:
        h("| Ventes totales EUR | Acquisitions EUR | Gain PMP EUR | Arrondi | Case |")
        h("|-------------------|-----------------|-------------|---------|------|")
        rounded = round(net_gain)
        box = "3VG" if rounded >= 0 else "3VH"
        h(f"| {total_proceeds:.2f} | {total_cost_sold:.2f} | {net_gain:+.2f} | "
          f"{rounded:+d} € | {box} |")
        h(f"\n> Méthode PMP obligatoire pour les résidents fiscaux français "
          f"(art. 150-0 D CGI). Le relevé fiscal annuel Wise utilise FIFO — "
          f"les montants ci-dessus peuvent différer.")
        if de_ruyter.is_active():
            h("\n### Répartition par taux PFU\n")
            h("| Taux PFU | Gain/perte EUR |")
            h("|----------|---------------|")
            by_rate_wise: dict = {}
            for g in gains_2074:
                rate_lbl = pfu_rate_label(de_ruyter.pfu_rate_on(date.fromisoformat(g['date'])))
                by_rate_wise[rate_lbl] = by_rate_wise.get(rate_lbl, 0.0) + g['gain_eur']
            for rate_lbl in sorted(by_rate_wise):
                total_rate = by_rate_wise[rate_lbl]
                h(f"| {rate_lbl} | {total_rate:+.2f} € |")
    else:
        h(f"Aucune cession en {target_year} — rien à déclarer.")

    if args.calculate_late_declaration_penalties and gains_2074 and net_gain > 0:
        _RATES = {
            'spontaneous': (0.10, "correction spontanée avant mise en demeure"),
            'formal':      (0.40, "après mise en demeure"),
            'fraud':       (0.80, "manœuvres frauduleuses"),
        }
        penalty_rate, scenario_label = _RATES[args.penalty_scenario]
        if args.declaration_deadline:
            deadline = datetime.strptime(args.declaration_deadline, '%Y-%m-%d').date()
        else:
            deadline = date(target_year + 1, 6, 1)
        today = date.today()
        months_delay = (
            math.ceil((today - deadline).days / 30.4375) if today > deadline else 0
        )
        rate_groups_wise: dict[str, dict] = {}
        for g in gains_2074:
            _rate = de_ruyter.pfu_rate_on(date.fromisoformat(g['date']))
            _rate_lbl = pfu_rate_label(_rate)
            _rounded = round(g['gain_eur'])
            _row_tax = _rounded * _rate if _rounded > 0 else 0.0
            _entry = rate_groups_wise.setdefault(_rate_lbl, {'gain': 0.0, 'tax': 0.0})
            _entry['gain'] += g['gain_eur']
            _entry['tax'] += _row_tax
        tax_owed = round(sum(grp['tax'] for grp in rate_groups_wise.values()))
        late_interest = round(tax_owed * 0.002 * months_delay)
        surcharge = round(tax_owed * penalty_rate)
        total_due = tax_owed + late_interest + surcharge
        h(f"\n## Pénalités — Formulaire 2074 ({target_year})\n")
        h(f"> Scénario : **{scenario_label}** · "
          f"Délai : **{months_delay} mois** "
          f"(échéance : {deadline.isoformat()}, calcul au {today.isoformat()})\n")
        h("| | Montant |")
        h("|---|---------|")
        for rate_lbl in sorted(rate_groups_wise):
            grp = rate_groups_wise[rate_lbl]
            gain_at_rate = round(grp['gain'])
            tax_at_rate = round(grp['tax'])
            h(f"| Plus-value nette (arrondie, case 3VG) ({rate_lbl}) | {gain_at_rate:+d} € |")
            h(f"| Impôt dû ({rate_lbl}) | {tax_at_rate} € |")
        if len(rate_groups_wise) > 1:
            h(f"| **Impôt dû total** | **{tax_owed} €** |")
        h(f"| Intérêts de retard (0,20 % × {months_delay} mois) | {late_interest} € |")
        h(f"| Majoration ({penalty_rate * 100:.0f} %) | {surcharge} € |")
        h(f"| **Total estimé** | **{total_due} €** |\n")
        h("> ⚠ Estimation indicative — consultez votre Service des Impôts des Particuliers (SIP) ou un conseiller fiscal.")

    # -- Dividendes --
    h("\n## Dividendes / Distributions — formulaire 2042")
    h("Aucune distribution : fonds capitalisants (IE00B41N0724, LU0852473015). "
      "Rien à déclarer en 2042.")

    # -- Frais de gestion --
    if year_fees:
        h(f"\n## Frais de gestion Wise\n")
        h("| Date | Montant EUR |")
        h("|------|------------|")
        for fee in sorted(year_fees, key=lambda x: x.date):
            h(f"| {fee.date.isoformat()} | {fee.total_eur:.2f} |")
        h(f"\n**Total {target_year} : {total_fees:.2f} EUR**")
        h("\n> Frais de gestion prélevés mensuellement sur le compte Wise. "
          "**Non déductibles** (art. 150-0 D CGI) : sous PFU comme sous barème progressif, "
          "seuls les frais d'*acquisition* sont inclus dans le prix de revient. "
          "Les frais de gestion courants ne s'y qualifient pas, quelle que soit l'option fiscale choisie.")

    # -- Positions au 31/12 --
    h(f"\n## Positions au 31/12/{target_year}\n")
    open_pos = [(isin, p) for isin, p in positions_eoy.items() if p['quantity'] > 1e-9]
    if open_pos:
        h("| ISIN | Fonds | Quantité | PMP EUR/part | Coût total EUR |")
        h("|------|-------|---------|-------------|----------------|")
        for isin, p in open_pos:
            pmp = p['total_cost_eur'] / p['quantity']
            h(f"| {isin} | {p['name']} | {p['quantity']:.7f} | "
              f"{pmp:.4f} | {p['total_cost_eur']:.2f} |")
    else:
        h(f"Toutes les positions sont fermées au 31/12/{target_year}.")

    # -- Rappels --
    h("\n## Rappels\n")
    h("- **Formulaire 3916** : déclarer le compte Wise chaque année "
      "(1 500 € d'amende sinon).")
    h("- **ETFs capitalisants** : imposition uniquement à la cession.")
    h(f"- **Conserver les CSV Wise 10 ans** (durée de reprise fiscale).")
    h(f"- Cache des taux BCE : `{args.cache}`")

    h(f"\n## Fichiers produits\n")
    h(f"| Fichier | Contenu |")
    h(f"|---------|---------|")
    h(f"| `{tx_csv.name}` | Opérations avec conversion EUR |")
    h(f"| `{gains_csv.name}` | Cessions — formulaire 2074 |")
    h(f"| `{div_csv.name}` | Dividendes (vide) |")
    h(f"| `{fees_csv.name}` | Frais de gestion |")
    h(f"| `{summary_csv.name}` | Positions PMP au 31/12/{target_year} |")
    h(f"| `{fx_csv.name}` | Journal des taux BCE |")

    readme = out_dir / 'README.md'
    readme.write_text('\n'.join(md), encoding='utf-8')
    print(f"\n📝 Résumé                  → {readme}")


if __name__ == '__main__':
    main()
