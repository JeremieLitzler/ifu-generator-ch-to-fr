#!/usr/bin/env python3
"""
yuh_csv_ifu.py — Calcule l'équivalent d'un IFU à partir des exports CSV Yuh
pour la déclaration fiscale française (résident fiscal français).

Usage:
    python3 yuh_csv_ifu.py <année> [--transactions-folder <dossier>] [--cache <fichier_fx>]
                           [-cldp [--penalty-scenario {spontaneous,formal,fraud}]
                                  [--declaration-deadline YYYY-MM-DD]]

Produit (prefixe par defaut : ifu_<annee>) :
    - <prefix>_transactions.csv  : toutes les operations de l'annee avec conversion EUR
    - <prefix>_gains_2074.csv    : plus/moins-values valeurs mobilieres (formulaire 2074)
    - <prefix>_gains_2086.csv    : plus/moins-values actifs numeriques (formulaire 2086, informatif)
    - <prefix>_dividendes.csv    : dividendes / distributions de l'annee
    - <prefix>_summary.csv       : positions et PMP au 31/12 de l'annee cible
    - <prefix>_fx_log.csv        : journal des taux BCE utilises

Hypothèses :
    - Le PMP est calculé sur l'intégralité de l'historique disponible (tous les CSV
      présents dans le dossier), pas uniquement sur l'année demandée, afin d'être exact.
    - Méthode PMP conforme à l'article 150-0 D du CGI.
    - Taux de change : taux de référence BCE (via api.frankfurter.dev).
    - Achat : cout = valeur absolue du debit (frais inclus dans le montant debite).
    - Vente : produit de cession = credit (net de frais).
    - Les frais d'autochange CHF/devise (BANK_AUTO_ORDER_EXECUTED) sont attribues a
      l'ordre d'investissement correspondant (meme date, meme devise) quand possible,
      et sinon journalises separement avec leur equivalent EUR.
    - Les crypto-ETPs sont classes comme valeurs mobilieres (formulaire 2074).
      Un recapitulatif 2086 est aussi produit par precaution.
"""
import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows (cp1252 console can't render accented chars or symbols)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from fx_cache import FXCache
from constants import (
    INVEST_ORDER_EXECUTED,
    INVEST_RECURRING_ORDER_EXECUTED,
    CASH_TRANSACTION_RELATED_OTHER,
    BANK_AUTO_ORDER_EXECUTED,
)
from ticker_isin import TICKER_ISIN, NON_SECURITY_ASSETS, TICKER_NAME_KEYWORDS
from de_ruyter import DeRuyterConfig, pfu_rate_label, load_de_ruyter_arg


# ---------------------------------------------------------------------------
# Classification crypto-ETPs
# ---------------------------------------------------------------------------

CRYPTO_ETP_ISINS = {
    'GB00BJYDH287',  # WisdomTree Physical Bitcoin
    'GB00BJYDH394',  # WisdomTree Physical Ethereum
    'GB00BMTP1626',  # WisdomTree Physical Solana
    'GB00BLD4ZL17',  # CoinShares Physical Bitcoin
    'CH1199067674',  # 21Shares Bitcoin Core ETP
    'DE000A28M8D0',  # VanEck Bitcoin ETN
    'DE000A3GWKF5',  # ETC Group Physical Bitcoin
    'DE000A40B5N8',  # iShares Bitcoin ETP
}

# ---------------------------------------------------------------------------
# Régimes de retenue à la source par préfixe ISIN (zone AA — art. 78 ann. II CGI)
# ---------------------------------------------------------------------------
# 'zero'               — 0 % confirmé pour les investisseurs non-résidents ;
#                        aucune saisie manuelle requise
# 'treaty_recoverable' — retenue probable ; saisir withholding_tax_native
#                        depuis le relevé fiscal annuel Yuh ou l'avis de distribution
# 'unknown'            — situation conventionnelle à vérifier au cas par cas
WITHHOLDING_REGIME: dict[str, str] = {
    'IE': 'zero',               # Irlande : 0 % sur distributions OPCVM aux non-résidents
    'LU': 'zero',               # Luxembourg : 0 % sur distributions OPCVM aux non-résidents
    'GB': 'zero',               # Royaume-Uni : pas de retenue sur dividendes aux non-résidents
    'FR': 'zero',               # France : pas de retenue étrangère pour les résidents français
    'US': 'treaty_recoverable', # 15–30 % retenue NRA ; convention France–USA plafond 15 %
    'CH': 'treaty_recoverable', # 35 % impôt anticipé (Verrechnungssteuer)
}


# ---------------------------------------------------------------------------
# Structure de données
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    row_id: str
    date: date
    type: str                 # 'buy' | 'sell' | 'dividend'
    ticker: str
    security_name: str
    isin: str
    quantity: float
    price_native: float
    amount_native: float      # abs(DEBIT) pour achat, CREDIT pour vente/dividende
    commission_native: float
    currency: str             # devise native de la transaction
    is_crypto_etp: bool
    exchange_fee_eur: float = 0.0        # frais d'autochange CHF→devise attribués (converti en EUR)
    withholding_tax_native: float = 0.0  # retenue à la source (zone AA) — non fourni par Yuh CSV
    withholding_tax_eur: float = 0.0     # retenue convertie en EUR (= withholding_tax_native × taux BCE)
    fx_rate_to_eur: Optional[float] = None
    fx_rate_date_used: Optional[str] = None
    total_eur: Optional[float] = None
    price_eur: Optional[float] = None


# ---------------------------------------------------------------------------
# Parsing CSV
# ---------------------------------------------------------------------------

def _strip_name(raw: str) -> str:
    """Supprime les guillemets triples et le préfixe de quantité «Nx »."""
    name = raw.strip('"').strip()
    name = re.sub(r'^\d[\d\.]*x\s+', '', name)
    return name.strip()


def _f(s: str) -> float:
    return float(s.strip()) if s.strip() else 0.0


def _guess_ticker(activity_name: str) -> Optional[str]:
    """Identifie un ticker depuis le libellé d'un dividende."""
    for ticker, keywords in TICKER_NAME_KEYWORDS.items():
        if any(kw.lower() in activity_name.lower() for kw in keywords):
            return ticker
    return None


def parse_csv_file(csv_path: Path) -> tuple[list[Transaction], list[dict]]:
    """
    Parse un fichier ACTIVITIES_REPORT CSV Yuh.
    Retourne (transactions, exchange_fees).
    exchange_fees = frais d'autochange non attribués à un titre spécifique.
    """
    transactions: list[Transaction] = []
    exchange_fees: list[dict] = []
    unknown_tickers: set[str] = set()

    with csv_path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        for i, row in enumerate(reader):
            activity_type = row['ACTIVITY TYPE'].strip()
            raw_name = row['ACTIVITY NAME']
            activity_name = _strip_name(raw_name)
            tx_date = datetime.strptime(row['DATE'].strip(), '%d/%m/%Y').date()

            # --- Autochange CHF→devise : collecte des frais ---
            if activity_type == BANK_AUTO_ORDER_EXECUTED:
                raw_name_clean = raw_name.strip('"').strip()
                if raw_name_clean.startswith('Autoexchange Swiss francs'):
                    fee = _f(row['FEES/COMMISSION'])
                    if fee > 0:
                        exchange_fees.append({
                            'date': tx_date,
                            'debit_chf': abs(_f(row['DEBIT'])),
                            'credit_amount': _f(row['CREDIT']),
                            'credit_currency': row['CREDIT CURRENCY'].strip(),
                            'fee_chf': fee,
                        })
                continue

            # --- Ordres d'investissement ---
            if activity_type in (INVEST_ORDER_EXECUTED, INVEST_RECURRING_ORDER_EXECUTED):
                buy_sell = row['BUY/SELL'].strip().upper()
                if buy_sell not in ('BUY', 'SELL'):
                    # INVEST_RECURRING_ORDER_REJECTED ou autre ligne sans direction
                    continue

                ticker = row['ASSET'].strip()
                if ticker in NON_SECURITY_ASSETS:
                    continue
                if ticker not in TICKER_ISIN:
                    if ticker not in unknown_tickers:
                        print(f"  ⚠ Ticker inconnu : {ticker!r} ligne {i+2} — ignorée",
                              file=sys.stderr)
                        unknown_tickers.add(ticker)
                    continue

                isin, sec_name = TICKER_ISIN[ticker]
                quantity = _f(row['QUANTITY'])
                price = _f(row['PRICE PER UNIT'])
                commission = _f(row['FEES/COMMISSION'])
                row_id = f"{tx_date.isoformat()}_{ticker}_{i}"

                if buy_sell == 'BUY':
                    amount = abs(_f(row['DEBIT']))
                    currency = row['DEBIT CURRENCY'].strip()
                    tx_type = 'buy'
                else:
                    amount = _f(row['CREDIT'])
                    currency = row['CREDIT CURRENCY'].strip()
                    tx_type = 'sell'

                is_crypto = isin in CRYPTO_ETP_ISINS
                label = "🔸" if is_crypto else "✓"
                print(f"  {label} {tx_date} {tx_type:4s} {ticker:6s} "
                      f"{activity_name[:35]:35s} "
                      f"{quantity:>10.4f} @ {price:>10.4f} {currency}")

                transactions.append(Transaction(
                    row_id=row_id,
                    date=tx_date,
                    type=tx_type,
                    ticker=ticker,
                    security_name=activity_name or sec_name,
                    isin=isin,
                    quantity=quantity,
                    price_native=price,
                    amount_native=amount,
                    commission_native=commission,
                    currency=currency,
                    is_crypto_etp=is_crypto,
                ))
                continue

            # --- Dividendes ---
            if activity_type == CASH_TRANSACTION_RELATED_OTHER:
                if not re.search(
                    r'dividend|distribution|coupon|income', activity_name, re.IGNORECASE
                ):
                    continue

                ticker = _guess_ticker(activity_name)
                if ticker is None:
                    print(f"  ⚠ Dividende : ticker non identifié pour «{activity_name}»",
                          file=sys.stderr)
                    isin, sec_name, is_crypto = 'UNKNOWN', activity_name, False
                else:
                    isin, sec_name = TICKER_ISIN[ticker]
                    is_crypto = isin in CRYPTO_ETP_ISINS

                amount = _f(row['CREDIT'])
                currency = row['CREDIT CURRENCY'].strip()
                print(f"  💰 {tx_date} div  {activity_name[:40]:40s} "
                      f"{amount:>10.2f} {currency}")

                transactions.append(Transaction(
                    row_id=f"{tx_date.isoformat()}_DIV_{i}",
                    date=tx_date,
                    type='dividend',
                    ticker=ticker or 'UNKNOWN',
                    security_name=activity_name,
                    isin=isin,
                    quantity=0.0,
                    price_native=0.0,
                    amount_native=amount,
                    commission_native=0.0,
                    currency=currency,
                    is_crypto_etp=is_crypto,
                ))

    return transactions, exchange_fees


# ---------------------------------------------------------------------------
# Calcul des plus-values (PMP, art. 150-0 D CGI)
# ---------------------------------------------------------------------------

def compute_gains(txs: list[Transaction]) -> dict:
    """Calcule les plus/moins-values en PMP sur l'ensemble des transactions triées."""
    txs_sorted = sorted(txs, key=lambda t: (t.date, t.row_id))
    positions: dict[str, dict] = {}

    for tx in txs_sorted:
        if tx.type == 'dividend':
            continue

        p = positions.setdefault(tx.isin, {
            'name': tx.security_name,
            'ticker': tx.ticker,
            'is_crypto_etp': tx.is_crypto_etp,
            'quantity': 0.0,
            'total_cost_eur': 0.0,
            'realized_gains': [],
        })

        if tx.type == 'buy':
            p['quantity'] += tx.quantity
            p['total_cost_eur'] += tx.total_eur + tx.exchange_fee_eur
        elif tx.type == 'sell':
            if p['quantity'] <= 0:
                print(f"  ⚠ Vente sans position pour {tx.isin} le {tx.date}",
                      file=sys.stderr)
                continue
            pmp = p['total_cost_eur'] / p['quantity']
            cost_basis = pmp * tx.quantity
            gain = tx.total_eur - cost_basis
            p['realized_gains'].append({
                'date': tx.date.isoformat(),
                'row_id': tx.row_id,
                'quantity': tx.quantity,
                'proceeds_eur': tx.total_eur,
                'cost_basis_eur': cost_basis,
                'pmp_eur': pmp,
                'gain_eur': gain,
            })
            p['quantity'] -= tx.quantity
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
        description="Calcule l'IFU équivalent depuis les exports CSV Yuh "
                    "(résident fiscal français)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('year', type=int,
                        help='Année fiscale cible (ex. 2024)')
    parser.add_argument('--transactions-folder', '-tf', default='transactions',
                        help="Dossier contenant les CSV Yuh (défaut: 'transactions')")
    parser.add_argument('--cache', default='fx_cache.json',
                        help="Fichier cache des taux BCE (défaut: fx_cache.json)")
    parser.add_argument('--calculate-late-declaration-penalties', '-cldp',
                        action='store_true',
                        help="Calcule les pénalités de déclaration tardive (formulaire 2074 uniquement)")
    parser.add_argument('--penalty-scenario',
                        choices=['spontaneous', 'formal', 'fraud'],
                        default='spontaneous',
                        help="Scénario de majoration : spontaneous=10%%, formal=40%%, "
                             "fraud=80%% (défaut: spontaneous)")
    parser.add_argument('--declaration-deadline',
                        default=None,
                        metavar='YYYY-MM-DD',
                        help="Date limite de déclaration originale "
                             "(défaut: 1er juin de l'année suivante)")
    parser.add_argument('-s', action='store_true', dest='penalty_s',
                        help="Alias : -cldp --penalty-scenario spontaneous (correction spontanée, majoration 10 %%)")
    parser.add_argument('-f', action='store_true', dest='penalty_f',
                        help="Alias : -cldp --penalty-scenario formal (après mise en demeure, majoration 40 %%)")
    parser.add_argument('-ff', action='store_true', dest='penalty_ff',
                        help="Alias : -cldp --penalty-scenario fraud (manœuvres frauduleuses, majoration 80 %%)")
    parser.add_argument('--out', default='ifu-new',
                        help="Dossier racine pour les fichiers de sortie (défaut: 'ifu-new')")
    parser.add_argument('--de-ruyter-periods',
                        default=None,
                        metavar='JSON_OU_FICHIER',
                        help=(
                            "Périodes de travail en Suisse (LAMal) pour application des dispositions de Ruyter. "
                            "Chemin vers un fichier JSON ou JSON inline. "
                            "Si absent : utilise src/config/de_ruyter_periods.json "
                            "(ou PFU standard 30 % si le fichier n'existe pas)."
                        ))
    args = parser.parse_args()

    # Résoudre les alias de scénario de pénalité
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
    out_dir = Path(args.out) / str(target_year) / 'yuh'
    out_dir.mkdir(parents=True, exist_ok=True)

    if not folder.is_dir():
        print(f"Dossier introuvable : {folder}", file=sys.stderr)
        sys.exit(1)

    # Tous les CSV disponibles, triés par année, pour un PMP correct
    all_csvs = sorted(folder.glob('yuh_ACTIVITIES_REPORT-*.CSV'))
    all_csvs += sorted(folder.glob('yuh_ACTIVITIES_REPORT-*.csv'))
    all_csvs = sorted(set(all_csvs))

    if not all_csvs:
        print(f"Aucun fichier yuh_ACTIVITIES_REPORT-*.CSV trouvé dans {folder}",
              file=sys.stderr)
        sys.exit(1)

    target_csv = folder / f'yuh_ACTIVITIES_REPORT-{target_year}.CSV'
    if not target_csv.exists():
        target_csv = folder / f'yuh_ACTIVITIES_REPORT-{target_year}.csv'
    if not target_csv.exists():
        print(f"Fichier introuvable pour l'année {target_year}: {target_csv}",
              file=sys.stderr)
        sys.exit(1)

    # --- Parsing de tous les CSV (pour PMP correct) ---
    all_txs: list[Transaction] = []
    all_exchange_fees: list[dict] = []

    for csv_path in all_csvs:
        year_tag = csv_path.stem.replace('yuh_ACTIVITIES_REPORT-', '')
        print(f"\n📄 Lecture {csv_path.name} ...")
        txs, fees = parse_csv_file(csv_path)
        all_txs.extend(txs)
        all_exchange_fees.extend(fees)

    if not all_txs:
        print("Aucune transaction exploitable.", file=sys.stderr)
        sys.exit(1)

    # Transactions de l'année cible uniquement (pour les sorties)
    year_txs = [t for t in all_txs if t.date.year == target_year]
    year_divs = [t for t in year_txs if t.type == 'dividend']
    year_invest = [t for t in year_txs if t.type != 'dividend']

    if not year_txs:
        print(f"Aucune transaction pour {target_year}.", file=sys.stderr)
        sys.exit(1)

    # --- Conversion FX ---
    print(f"\n💱 Récupération des taux BCE (cache: {args.cache})...")
    fx = FXCache(Path(args.cache))
    fx_log: list[dict] = []

    for tx in all_txs:
        try:
            rate, bce_date = fx.get(tx.date, tx.currency)
            tx.fx_rate_to_eur = rate
            tx.fx_rate_date_used = bce_date
            tx.total_eur = round(tx.amount_native * rate, 4)
            tx.price_eur = round(tx.price_native * rate, 6)
            if tx.date.year == target_year:
                fx_log.append({
                    'date_demandée': tx.date.isoformat(),
                    'date_BCE_utilisée': bce_date,
                    'devise': tx.currency,
                    'taux_vers_EUR': rate,
                    'même_date': 'oui' if tx.date.isoformat() == bce_date else 'non',
                    'row_id': tx.row_id,
                })
        except Exception as e:
            print(f"  ⚠ Erreur FX pour {tx.date} ({tx.currency}): {e}", file=sys.stderr)
            sys.exit(2)

    print(f"  ✓ {len(all_txs)} transactions converties")

    # --- Attribution des frais d'autochange aux ordres d'investissement ---
    buys_by_date_ccy: dict = {}
    for tx in all_txs:
        if tx.type == 'buy':
            buys_by_date_ccy.setdefault((tx.date, tx.currency), []).append(tx)

    unattributed_fees: list[dict] = []
    attributed_count = 0
    for fee in all_exchange_fees:
        key = (fee['date'], fee['credit_currency'])
        candidates = buys_by_date_ccy.get(key, [])
        chf_rate, _ = fx.get(fee['date'], 'CHF')
        fee_eur = round(fee['fee_chf'] * chf_rate, 4)
        if len(candidates) == 1:
            candidates[0].exchange_fee_eur += fee_eur
            attributed_count += 1
        else:
            fee['fee_eur'] = fee_eur
            unattributed_fees.append(fee)
            if len(candidates) > 1:
                print(
                    f"  ⚠ Frais autochange {fee['date']} {fee['credit_currency']}: "
                    f"{len(candidates)} achats candidats — non attribué",
                    file=sys.stderr,
                )
    if attributed_count:
        print(f"  ✓ {attributed_count} frais d'autochange attribués aux ordres d'achat")
    if unattributed_fees:
        print(f"  ⚠ {len(unattributed_fees)} frais d'autochange non attribués")

    # --- Calcul des plus-values sur tout l'historique ---
    positions = compute_gains(all_txs)

    # --- Cessions de l'année cible ---
    gains_2074 = []
    gains_2086_info = []

    for isin, p in positions.items():
        for g in p['realized_gains']:
            if g['date'][:4] != str(target_year):
                continue
            entry = {**g, 'isin': isin, 'name': p['name'],
                     'ticker': p['ticker'], 'is_crypto_etp': p['is_crypto_etp']}
            gains_2074.append(entry)
            if p['is_crypto_etp']:
                gains_2086_info.append(entry)

    # --- Positions au 31/12 de l'année cible ---
    # Recalculer les positions jusqu'à fin de l'année cible
    last_day = date(target_year, 12, 31)
    positions_at_year_end = compute_gains(
        [t for t in all_txs if t.date <= last_day]
    )

    # ===================================================================
    # SORTIES CSV  →  ifu/<year>/
    # ===================================================================

    def out(name: str) -> Path:
        return out_dir / f'{target_year}_{name}'

    def _ligne_2042(isin: str) -> str:
        """Ligne 2042 pour un dividende : 2DC si ISIN FR (abattement 40 %), sinon 2TR."""
        return '2DC (éligible abattement 40 %)' if isin.startswith('FR') else '2TR (non éligible)'

    # Journal des taux BCE
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

    # Dividendes de l'année
    div_csv = out('dividendes.csv')
    with div_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Date', 'ID', 'Ticker', 'ISIN', 'Titre',
            'Montant brut', 'Devise', 'Taux BCE', 'Date BCE',
            'Montant EUR', 'Montant arrondi EUR',
            'Retenue à la source native (zone AA)',
            'Retenue à la source EUR (zone AA / ligne 2AB)',
            'Base DQ EUR (prélèvements sociaux)',
            'Crypto-ETP', 'Ligne 2042',
        ])
        for d in sorted(year_divs, key=lambda t: t.date):
            base_dq = round(d.total_eur + d.withholding_tax_eur, 2)
            writer.writerow([
                d.date.isoformat(), d.row_id, d.ticker, d.isin, d.security_name,
                f"{d.amount_native:.2f}", d.currency,
                f"{d.fx_rate_to_eur:.6f}", d.fx_rate_date_used,
                f"{d.total_eur:.2f}",
                f"{round(d.total_eur):d}",
                f"{d.withholding_tax_native:.2f}",
                f"{d.withholding_tax_eur:.2f}",
                f"{base_dq:.2f}",
                'oui' if d.is_crypto_etp else 'non',
                _ligne_2042(d.isin),
            ])
    print(f"📊 Dividendes             → {div_csv}")

    # Cessions formulaire 2074
    gains_2074_csv = out('gains_2074.csv')
    with gains_2074_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Date cession', 'ID', 'Ticker', 'ISIN', 'Titre',
            'Quantité cédée', 'Prix de cession EUR',
            'Prix de revient PMP EUR', 'Plus/moins-value EUR (PMP)',
            'Montant arrondi EUR', 'Crypto-ETP', 'Taux PFU',
        ])
        for g in sorted(gains_2074, key=lambda x: x['date']):
            gain_pfu_rate = de_ruyter.pfu_rate_on(date.fromisoformat(g['date']))
            writer.writerow([
                g['date'], g['row_id'], g['ticker'], g['isin'], g['name'],
                f"{g['quantity']:.6f}",
                f"{g['proceeds_eur']:.2f}",
                f"{g['cost_basis_eur']:.2f}",
                f"{g['gain_eur']:+.2f}",
                f"{round(g['gain_eur']):+d}",
                'oui' if g['is_crypto_etp'] else 'non',
                f"{gain_pfu_rate}",
            ])
    print(f"📊 Cessions (form. 2074)  → {gains_2074_csv}")

    # Récapitulatif 2086 (informatif)
    gains_2086_csv = out('gains_2086.csv')
    with gains_2086_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Date cession', 'ID', 'Ticker', 'ISIN', 'Titre',
            'Quantité cédée', 'Prix de cession EUR',
            'Prix de revient PMP EUR', 'Plus/moins-value EUR (PMP)',
            'Montant arrondi EUR',
            '⚠ INFORMATIF — seulement si DGFiP requalifie en actifs numériques',
            'Taux PFU',
        ])
        for g in sorted(gains_2086_info, key=lambda x: x['date']):
            gain_pfu_rate = de_ruyter.pfu_rate_on(date.fromisoformat(g['date']))
            writer.writerow([
                g['date'], g['row_id'], g['ticker'], g['isin'], g['name'],
                f"{g['quantity']:.6f}",
                f"{g['proceeds_eur']:.2f}",
                f"{g['cost_basis_eur']:.2f}",
                f"{g['gain_eur']:+.2f}",
                f"{round(g['gain_eur']):+d}",
                '',
                f"{gain_pfu_rate}",
            ])
    print(f"📊 Cessions (form. 2086)  → {gains_2086_csv}  ⚠ informatif")

    # Positions au 31/12 de l'année cible
    summary_csv = out('summary.csv')
    with summary_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Ticker', 'ISIN', 'Titre', 'Quantité détenue',
            'Coût total EUR', 'PMP EUR/part',
            'Plus-values réalisées EUR', 'Crypto-ETP', 'Formulaire',
        ])
        for isin, p in positions_at_year_end.items():
            total_realized = sum(g['gain_eur'] for g in p['realized_gains'])
            pmp = (p['total_cost_eur'] / p['quantity']
                   if p['quantity'] > 0 else 0.0)
            writer.writerow([
                p['ticker'], isin, p['name'],
                f"{p['quantity']:.6f}",
                f"{p['total_cost_eur']:.2f}",
                f"{pmp:.4f}",
                f"{total_realized:+.2f}",
                'oui' if p['is_crypto_etp'] else 'non',
                ('2074 (+ 2086 si requalifié)' if p['is_crypto_etp'] else '2074'),
            ])
    print(f"📊 Positions au 31/12/{target_year} → {summary_csv}")

    # ===================================================================
    # RÉCAPITULATIF — console + README.md
    # ===================================================================

    by_year_2074: dict[str, float] = {}
    by_year_2086: dict[str, float] = {}
    proceeds_by_year_2086: dict[str, float] = {}

    by_year_rate_2074: dict[str, dict] = {}
    for g in gains_2074:
        y = g['date'][:4]
        by_year_2074[y] = by_year_2074.get(y, 0.0) + g['gain_eur']
        rate = de_ruyter.pfu_rate_on(date.fromisoformat(g['date']))
        rate_lbl = pfu_rate_label(rate)
        rounded_gain = round(g['gain_eur'])
        row_tax = rounded_gain * rate if rounded_gain > 0 else 0.0
        if y not in by_year_rate_2074:
            by_year_rate_2074[y] = {}
        entry = by_year_rate_2074[y].setdefault(rate_lbl, {'gain': 0.0, 'tax': 0.0})
        entry['gain'] += g['gain_eur']
        entry['tax'] += row_tax
    for g in gains_2086_info:
        y = g['date'][:4]
        by_year_2086[y] = by_year_2086.get(y, 0.0) + g['gain_eur']
        proceeds_by_year_2086[y] = proceeds_by_year_2086.get(y, 0.0) + g['proceeds_eur']

    # Build summary lines for both stdout and README.md
    md: list[str] = []

    def h(text: str) -> None:
        print(text)
        md.append(text)

    h(f"\n# Déclaration fiscale {target_year} — Yuh")
    h(f"\n> Généré le {datetime.now().strftime('%Y-%m-%d')} "
      f"· PMP calculé sur {len(all_csvs)} fichier(s) CSV\n")

    if de_ruyter.is_active():
        h("## Régime de Ruyter\n")
        h("Exonération CSG (9,2 %) et CRDS (0,5 %) sur les revenus de cession et les "
          "dividendes durant les périodes de travail en Suisse (LAMal).\n")
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

    pfu_titre = "de Ruyter actif" if de_ruyter.is_active() else "PFU 30 %"
    h(f"## Formulaire 2074 — Valeurs mobilières ({pfu_titre})")
    h("Plus-value nette → case 3VG | Moins-value → case 3VH\n")
    if by_year_2074:
        h("| Année | Gain/perte EUR | Arrondi | Case |")
        h("|-------|---------------|---------|------|")
        for year in sorted(by_year_2074):
            total = by_year_2074[year]
            rounded = round(total)
            box = "3VG" if rounded >= 0 else "3VH"
            h(f"| {year} | {total:+.2f} | {rounded:+d} € | {box} |")
        if de_ruyter.is_active():
            h("\n### Répartition par taux PFU\n")
            h("| Année | Taux PFU | Gain/perte EUR |")
            h("|-------|----------|---------------|")
            for yr in sorted(by_year_rate_2074):
                for rate_lbl in sorted(by_year_rate_2074[yr]):
                    total = by_year_rate_2074[yr][rate_lbl]['gain']
                    h(f"| {yr} | {rate_lbl} | {total:+.2f} € |")
    else:
        h(f"Aucune cession en {target_year} — rien à déclarer.")

    if args.calculate_late_declaration_penalties and by_year_2074:
        _PENALTY_RATES = {
            'spontaneous': (0.10, "correction spontanée avant mise en demeure"),
            'formal':      (0.40, "après mise en demeure"),
            'fraud':       (0.80, "manœuvres frauduleuses"),
        }
        penalty_rate, scenario_label = _PENALTY_RATES[args.penalty_scenario]

        if args.declaration_deadline:
            deadline = datetime.strptime(args.declaration_deadline, '%Y-%m-%d').date()
        else:
            deadline = date(target_year + 1, 6, 1)

        today = date.today()
        months_delay = (
            math.ceil((today - deadline).days / 30.4375)
            if today > deadline else 0
        )

        for year_str in sorted(by_year_2074):
            net_gain = by_year_2074[year_str]
            if net_gain <= 0:
                h(f"\n## Pénalités de déclaration tardive — Formulaire 2074 ({year_str})\n")
                h("Moins-value ou gain nul — aucun impôt dû, pas de pénalité applicable.")
                continue

            rate_groups = by_year_rate_2074.get(year_str, {})
            tax_owed = round(sum(grp['tax'] for grp in rate_groups.values()))
            late_interest = round(tax_owed * 0.002 * months_delay)
            penalty_surcharge = round(tax_owed * penalty_rate)
            total_due = tax_owed + late_interest + penalty_surcharge

            h(f"\n## Pénalités de déclaration tardive — Formulaire 2074 ({year_str})\n")
            h(f"> Scénario : **{scenario_label}** · "
              f"Délai : **{months_delay} mois** "
              f"(échéance : {deadline.isoformat()}, calcul au {today.isoformat()})\n")
            h("| | Montant |")
            h("|---|---------|")
            for rate_lbl in sorted(rate_groups):
                grp = rate_groups[rate_lbl]
                gain_at_rate = round(grp['gain'])
                tax_at_rate = round(grp['tax'])
                h(f"| Plus-value nette (arrondie, case 3VG) ({rate_lbl}) | {gain_at_rate:+d} € |")
                h(f"| Impôt dû ({rate_lbl}) | {tax_at_rate} € |")
            if len(rate_groups) > 1:
                h(f"| **Impôt dû total** | **{tax_owed} €** |")
            h(f"| Intérêts de retard (0,20 % × {months_delay} mois) | {late_interest} € |")
            h(f"| Majoration ({penalty_rate * 100:.0f} %) | {penalty_surcharge} € |")
            h(f"| **Total estimé à régulariser** | **{total_due} €** |\n")
            h("> ⚠ Estimation indicative — consultez votre Service des Impôts des Particuliers (SIP) ou un conseiller fiscal.")

    if by_year_2086:
        h("\n## Formulaire 2086 — ⚠ Informatif seulement (crypto-ETPs)")
        h("**Classification retenue : valeurs mobilières → formulaire 2074 (art. 150-0 A CGI).**")
        h("Base légale : l'art. L. 54-10-1 CMF définit les *actifs numériques* en excluant "
          "explicitement les instruments financiers au sens de l'art. L. 211-1 CMF. "
          "Les crypto-ETPs (WisdomTree, CoinShares, ETC Group…) sont des valeurs mobilières "
          "admises sur marchés réglementés (LSE, Xetra, Euronext) — ils sortent donc du champ "
          "de l'art. 150 VH bis CGI. Source : BOI-RPPM-PVBMI-70-10-10 §20–30.")
        h("Ce fichier 2086 est produit à titre **précautionnel uniquement**. "
          "En l'absence de prise de position formelle du DGFiP sur les crypto-ETPs, "
          "**ne déclarez pas ces montants sur le formulaire 2086**. "
          "Consultez un conseiller fiscal si vos positions sont significatives.")
        h("Plus-value → case 3AN | Moins-value → case 3BN\n")
        h("| Année | Gain/perte EUR | Arrondi | Cessions | Note |")
        h("|-------|---------------|---------|----------|------|")
        for year in sorted(by_year_2086):
            total = by_year_2086[year]
            rounded = round(total)
            proceeds = proceeds_by_year_2086[year]
            box = "3AN" if rounded >= 0 else "3BN"
            if proceeds <= 305.0:
                h(f"| {year} | {total:+.2f} | — | {proceeds:.2f} € | "
                  f"EXONÉRÉ (≤ 305 €) |")
            else:
                h(f"| {year} | {total:+.2f} | {rounded:+d} € ({box}) | "
                  f"{proceeds:.2f} € | imposable |")

    if year_divs:
        h("\n## Dividendes / Distributions — formulaire 2042\n")
        div_2dc = [d for d in year_divs if d.isin.startswith('FR')]
        div_2tr = [d for d in year_divs if not d.isin.startswith('FR')]
        total_2dc = sum(d.total_eur for d in div_2dc)
        total_2tr = sum(d.total_eur for d in div_2tr)
        div_total = total_2dc + total_2tr
        h("| Ligne | Description | Total EUR | Arrondi |")
        h("|-------|-------------|-----------|---------|")
        if div_2dc:
            h(f"| **2DC** | Distributions éligibles abattement 40 % (ISIN FR) "
              f"| {total_2dc:+.2f} | {round(total_2dc):+d} € |")
        if div_2tr:
            h(f"| **2TR** | Distributions non éligibles (étrangères) "
              f"| {total_2tr:+.2f} | {round(total_2tr):+d} € |")
        h(f"| | **Total** | **{div_total:+.2f}** | **{round(div_total):+d} €** |")
        h(f"\n> Base prélèvements sociaux (zone DQ) : **{round(div_total):+d} €**"
          f" — Yuh n'ayant pas effectué de retenue, montant brut = montant net déclaré."
          f" Sous PFU (défaut) : les 17,2 % sont calculés automatiquement sur les montants"
          f" déclarés en 2TR / 2DC — aucune ligne supplémentaire à renseigner."
          f" Sous option barème progressif : la CSG déductible (6,8 %) est à reporter"
          f" ligne **2CG** du formulaire 2042.")
        withholding_total_eur = sum(d.withholding_tax_eur for d in year_divs)
        needs_manual = [d for d in year_divs
                        if d.isin != 'UNKNOWN'
                        and WITHHOLDING_REGIME.get(d.isin[:2], 'unknown') == 'treaty_recoverable'
                        and d.withholding_tax_eur == 0.0]
        unknown_regime = [d for d in year_divs
                          if d.isin != 'UNKNOWN'
                          and WITHHOLDING_REGIME.get(d.isin[:2], 'unknown') == 'unknown']
        if withholding_total_eur > 0:
            h(f"\n> Retenue à la source étrangère (zone AA / ligne 2AB) :"
              f" **{withholding_total_eur:.2f} €** — à reporter sur la ligne 2AB du formulaire 2042.")
        if needs_manual:
            tickers_str = ', '.join(sorted({d.ticker for d in needs_manual}))
            h(f"\n> ⚠ Zone AA — saisie manuelle requise pour **{tickers_str}**."
              f" Ces instruments (préfixe ISIN US ou CH) sont soumis à retenue à la source."
              f" Consultez le relevé fiscal annuel Yuh, renseignez `withholding_tax_native`"
              f" dans le CSV des dividendes, puis relancez le script."
              f" Le crédit récupérable s'impute sur la **ligne 2AB** du formulaire 2042.")
        if unknown_regime:
            tickers_str = ', '.join(sorted({d.ticker for d in unknown_regime}))
            h(f"\n> ℹ Zone AA — régime de retenue non classifié pour **{tickers_str}**"
              f" (préfixe ISIN inconnu du dictionnaire). Vérifier la convention fiscale applicable.")
        if not needs_manual and not unknown_regime and withholding_total_eur == 0:
            h(f"\n> Zone AA (retenue à la source / ligne 2AB) : **0 €** confirmé"
              f" — tous les dividendes proviennent d'instruments à retenue nulle"
              f" (IE/LU/GB/FR : pas de retenue sur distributions aux non-résidents).")
        if de_ruyter.is_active():
            h(f"\n> Régime de Ruyter : le taux PFU (colonne **Taux PFU**) est déterminé"
              f" à la date de chaque distribution dans `{div_csv.name}`.")

    h(f"\n## Positions au 31/12/{target_year}\n")
    open_positions = [(isin, p) for isin, p in positions_at_year_end.items()
                      if p['quantity'] > 0]
    if open_positions:
        h("| Ticker | ISIN | Titre | Quantité | PMP EUR/part | Coût total EUR |")
        h("|--------|------|-------|----------|-------------|----------------|")
        for isin, p in open_positions:
            pmp = p['total_cost_eur'] / p['quantity']
            crypto_tag = " ⚠ crypto-ETP" if p['is_crypto_etp'] else ""
            h(f"| {p['ticker']} | {isin} | {p['name']}{crypto_tag} | "
              f"{p['quantity']:.6f} | {pmp:.4f} | {p['total_cost_eur']:.2f} |")
    else:
        h("Aucune position ouverte.")

    year_unattributed = [e for e in unattributed_fees if e['date'].year == target_year]
    if year_unattributed:
        total_fees_chf = sum(e['fee_chf'] for e in year_unattributed)
        total_fees_eur = sum(e['fee_eur'] for e in year_unattributed)
        h(f"\n## Frais d'autochange non attribués\n")
        h(f"{total_fees_chf:.2f} CHF ({total_fees_eur:.2f} EUR) "
          f"sur {len(year_unattributed)} opération(s). "
          f"Coûts d'acquisition non attribués à un titre spécifique — "
          f"ajustement manuel si souhaité.")

    shifted = [e for e in fx_log if e['même_date'] == 'non']
    if shifted:
        h(f"\n## Taux BCE décalés ({len(shifted)}/{len(fx_log)})\n")
        h("La BCE ne publie pas les week-ends et jours fériés — "
          "taux du dernier jour ouvré utilisé (pratique acceptée par la DGFiP).\n")
        h("| Date transaction | Devise | Date BCE utilisée | Taux |")
        h("|-----------------|--------|------------------|------|")
        for e in shifted:
            h(f"| {e['date_demandée']} | {e['devise']} | "
              f"{e['date_BCE_utilisée']} | {e['taux_vers_EUR']:.6f} |")

    h("\n## Rappels\n")
    h("- **Formulaire 3916** : déclarer le compte Yuh chaque année "
      "(1 500 € d'amende sinon).")
    h("- **ETFs capitalisants** : imposition uniquement à la cession.")
    h("- **Conserver les CSV Yuh 10 ans** (durée de reprise fiscale).")
    h(f"- Cache des taux BCE : `{args.cache}`")

    h(f"\n## Fichiers produits\n")
    h(f"| Fichier | Contenu |")
    h(f"|---------|---------|")
    h(f"| `{tx_csv.name}` | Toutes les opérations avec conversion EUR |")
    h(f"| `{gains_2074_csv.name}` | Cessions — formulaire 2074 |")
    h(f"| `{gains_2086_csv.name}` | Cessions crypto-ETPs — formulaire 2086 (informatif) |")
    h(f"| `{div_csv.name}` | Dividendes et distributions |")
    h(f"| `{summary_csv.name}` | Positions et PMP au 31/12/{target_year} |")
    h(f"| `{fx_csv.name}` | Journal des taux BCE utilisés |")

    readme = out_dir / 'README.md'
    readme.write_text('\n'.join(md), encoding='utf-8')
    print(f"\n📝 Résumé                  → {readme}")


if __name__ == '__main__':
    main()
