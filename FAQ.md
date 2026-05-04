# FAQ — Tax & Business

## What is ifu-generator?

A set of Python scripts that generate French tax declaration data for French-resident cross-border workers (frontaliers) who hold investment accounts at Yuh/Swissquote and/or Wise Assets. It produces CSVs ready to fill in forms 2074, 2086, and 2042.

---

## What are the "Dispositions de Ruyter" and why do they matter?

The *dispositions de Ruyter* stem from the CJUE ruling **C-623/13** (*de Ruyter v. Ministre des Finances et des Comptes publics*, 26 February 2015). The Court held that a member state cannot levy social contributions on investment income if the taxpayer is already affiliated to another member state's social security system — because that creates a dual contribution obligation prohibited by EU Regulation 883/2004.

For French tax residents who work **in Switzerland under Swiss social insurance (LAMal)**, this means the French **CSG (9.2 %)** and **CRDS (0.5 %)** are not due on capital gains and dividends during Swiss work periods. The effective PFU rate drops from **30.0 %** (12.8 % IR + 17.2 % prélèvements sociaux) to **20.3 %** (12.8 % IR + 7.5 % *prélèvement de solidarité*, the only social levy that still applies to non-EU-coordinated residents).

The rate is determined **at the date of each transaction**, not for the whole year. If you alternate between Swiss and French employment (or unemployment), each gain line gets its own rate:

| Period | Affiliation | PFU rate |
|--------|-------------|----------|
| Swiss work period | LAMal | **20.3 %** |
| French unemployment / French employment | Sécurité Sociale | **30.0 %** |

Legal basis: art. L136-6 and L136-7 I ter CSS; confirmed by DGFiP doctrine at **BOI-RSA-GEO-30** and the Conseil d'État ruling of 27 July 2015 (n° 334551).

> **Note**: this applies only to **frontaliers and detached workers actually enrolled in LAMal** during the Swiss work period. French residents who simply invest in Swiss securities but work in France remain subject to the full 30.0 % PFU.

---

## What is the PMP method?

PMP (*Prix Moyen Pondéré*) is the weighted average cost method required by French tax law (art. 150-0 D CGI) to compute capital gains on securities. Each buy updates the average cost per share; each sell computes the gain against that average.

---

## Why does the script say "PMP calculé sur X fichier(s) CSV" when I only asked for one year?

Because PMP requires the **full purchase history**, not just the target year. If you bought 10 shares in 2022, added 5 in 2023, and sold 8 in 2024, the correct cost basis for the 2024 sale depends on all the 2022 and 2023 buys. The script reads every `ACTIVITIES_REPORT-*.CSV` file in the transactions folder to build the complete history, then filters the output to the target year only.

---

## What exchange rate is used for CHF/USD → EUR conversion?

ECB (European Central Bank) rates fetched via `api.frankfurter.dev`. If a transaction falls on a weekend or public holiday, the last business day's rate is used — the standard DGFiP practice.

---

## Are broker commissions included in the cost basis?

It depends on the broker and the fee type:

**Yuh** — Yes. The cost basis of a buy = `abs(DEBIT)`, which already includes the Yuh transaction commission. Auto-exchange fees (`BANK_AUTO_ORDER_EXECUTED`) are also added to the cost basis of the corresponding buy order, as they are *frais d'acquisition* under the PMP method.

**Wise** — No. Art. 150-0 D CGI defines the capital gain as `prix de cession − prix de revient`. The *prix de revient* can only include the acquisition price plus **frais d'acquisition** — fees paid *at the moment of buying*. Wise's monthly platform fees (`FEE_CHARGE` rows) are *frais de gestion courants*, not frais d'acquisition, so they cannot be added to the cost basis under either tax regime (PFU or barème progressif).

The historical deduction for *frais de garde* that existed before 2018 applied only to *revenus de capitaux mobiliers* (dividends, interest), not to capital gains — and was suppressed by the Finance Law 2017 alongside the introduction of PFU.

Wise fees are logged in `<year>_fees.csv` for records but have no effect on the computed gain.

---

## What happens when an auto-exchange fee cannot be attributed to a specific buy?

It is reported in the "Frais d'autochange non attribués" section of the console summary and `README.md` with both its original CHF value and the BCE-converted EUR equivalent. A warning is printed if the ambiguity is caused by multiple buy orders in the same foreign currency on the same day. Truly unmatched fees (no buy found at all) are treated the same way.

---

## Does auto-exchange fee attribution apply to recurring invest orders?

Yes. Both `INVEST_ORDER_EXECUTED` and `INVEST_RECURRING_ORDER_EXECUTED` rows are treated as buy transactions for matching purposes. If a `BANK_AUTO_ORDER_EXECUTED` row on the same date shares the same foreign currency, the fee is attributed regardless of which invest activity type triggered it.

---

## How are crypto-ETPs handled?

Crypto-ETPs (WisdomTree, CoinShares, ETC Group, etc.) are classified as **valeurs mobilières** and their gains go on **form 2074**, not form 2086.

Legal basis:

- [Art. L. 54-10-1 CMF](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000038509570/) defines *actifs numériques* and explicitly excludes financial instruments within the meaning of [art. L. 211-1 CMF](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032469968).
- Crypto-ETPs are admitted to trading on regulated markets (LSE, Xetra, Euronext), carry an ISIN, and are issued by regulated entities — so they qualify as financial instruments and fall outside the [art. 150 VH bis CGI](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000038612228/) / form 2086 regime by statute.
- The DGFiP's own scope commentary confirms this at [BOI-RPPM-PVBMC-30-10](https://bofip.impots.gouv.fr/bofip/11967-PGP.html/identifiant=BOI-RPPM-PVBMC-30-10-20190902) (*Cession d'actifs numériques — Champ d'application*): tokens that qualify as financial instruments are excluded from the actifs numériques regime.

A precautionary `<year>_gains_2086.csv` is also produced in case the DGFiP ever issues a contrary ruling, but **do not file form 2086 for these instruments**. The list of crypto-ETP ISINs is maintained in `CRYPTO_ETP_ISINS` inside `src/yuh_csv_ifu.py` and must be updated when new ones are held.

---

## How are dividends classified between ligne 2DC and 2TR on form 2042?

The script derives the classification automatically from the ISIN:

- **ISIN prefix `FR`** → ligne **2DC** (eligible for the 40 % abatement under art. 158-3-2° CGI — French companies only)
- **All other prefixes** (IE, US, GB, CH, LU, DE, …) → ligne **2TR** (non-eligible)

This is already a maintained invariant since the ISIN is always present in `ticker_isin.py`. No manual classification is needed.

---

## How does the script determine whether foreign withholding tax (zone AA) applies to a dividend?

Zone AA is the IFU 2561 field for foreign withholding tax on dividends (*retenue à la source prélevée par l'État de la source*). It maps to **ligne 2AB** on form 2042 as a recoverable tax credit.

The script maps the two-letter ISIN country prefix to one of three regimes via the `WITHHOLDING_REGIME` dict:

| Regime | Prefixes | Behaviour |
|--------|----------|-----------|
| `zero` | IE, LU, GB, FR | Output confirms zone AA = 0 € automatically |
| `treaty_recoverable` | US, CH | ⚠ per-ticker warning; manual entry of `withholding_tax_native` required from the Yuh *relevé fiscal annuel* |
| `unknown` | all others | ℹ advisory; check the applicable tax treaty |

The recovered withholding goes on **ligne 2AB** of form 2042 (crédit d'impôt étranger).

---

## Why are Irish (IE) and Luxembourg (LU) ETF dividends shown as zero withholding?

Because the **fund domicile country** determines what is withheld at the investor level, not the country of the underlying holdings:

- **IE** — Ireland does not withhold tax on UCITS distributions paid to non-resident investors. This is the structural reason most European ETFs are domiciled in Ireland.
- **LU** — Luxembourg applies the same principle for UCITS funds.
- **GB** — The UK abolished dividend withholding tax entirely; distributions to non-residents are paid gross.
- **FR** — For a French tax resident, a French company's dividend is not "foreign withholding" — no foreign state takes a cut. Zone AA covers only tax withheld by a *foreign* country.

---

## What is zone DQ and how do I declare prélèvements sociaux on form 2042?

Zone DQ is the IFU 2561 field for the social contributions base (*montant brut des revenus distribués soumis aux prélèvements sociaux*). It is the line the **broker** fills on the IFU. Since Yuh does not withhold, the gross equals the net and `base_DQ_eur` in `<year>_dividendes.csv` equals the dividend amount.

For your **own form 2042** declaration:

- **Under PFU (default)**: the 17.2 % prélèvements sociaux are computed automatically by the DGFiP from the amounts you enter on lines 2TR / 2DC. No separate social contributions line to fill.
- **Under barème progressif** (opt-in): same 2TR / 2DC amounts. The CSG déductible portion (6.8 %) may additionally be reported on line **2CG**.

---

## What do the penalty flags do?

They estimate late-declaration interest on top of the tax owed:

| Flag | Scenario | Rate |
|------|----------|------|
| `-s` | Spontaneous correction | 10 % |
| `-f` | After formal notice | 40 % |
| `-ff` | Fraud | 80 % |

Pass the flag to any of the three scripts (`yuh_csv_ifu.py`, `wise_csv_ifu.py`, `unified_readme.py`).

---

## Can I override the assumed declaration deadline when calculating penalties?

Yes — pass `--declaration-deadline YYYY-MM-DD` alongside `-s`/`-f`/`-ff` or `-cldp`. The default deadline is **June 1 of the year following the tax year** (e.g. `2025-06-01` for 2024 income). Override it if your specific deadline was earlier, for example the paper deadline in mid-May or an online deadline for an earlier fiscal zone.

```bash
python src/yuh_csv_ifu.py 2024 -s --declaration-deadline 2025-05-15
```

---

## Who is supposed to file the IFU 2561 — the broker or me?

The IFU 2561 is filed by the **établissement payeur** (the broker), not by the individual investor. It is a legal obligation under art. 242 ter CGI that applies only to French-domiciled payers.

Yuh/Swissquote and Wise are Swiss brokers — they are not subject to French tax reporting obligations and **do not file an IFU** on your behalf. You must declare your income yourself via form **2042** (dividends) and **2074** (capital gains).

This project generates the data that a French broker *would* have put in an IFU, so you can fill in your own tax return correctly.

---

## What is the IFU 2561 filing deadline?

**15 February** of the year following the income year (e.g. 15 February 2025 for 2024 income). A one-day administrative tolerance may push this to the following Monday.

This deadline applies to the établissement payeur (broker). For your personal tax return (form 2042), the deadline is the standard late May / early June deadline set each year by the DGFiP for online declarations.

---

## I hold only ETFs, no individual stocks. Does the 40 % abattement ever apply to my dividends?

No. The 40 % abattement (IFU zone AY — *revenus distribués éligibles à l'abattement* / form 2042 ligne 2DC) applies exclusively to distributions from **companies** (*revenus distribués éligibles* under art. 158-3-2° CGI). ETF distributions are never eligible, regardless of how they are labelled by the broker.

With a 100 % ETF portfolio, all distributions go to **zone AZ** (*revenus distribués non éligibles à l'abattement*) **/ ligne 2TR** only. Zone AY stays zero and no split is needed.

---

## What is zone AN on the IFU 2561?

Zone AN (*montant brut des cessions de valeurs mobilières*) is the **total gross proceeds** from all securities sales during the year, expressed in euros. It must be reported even if the net gain is zero or negative.

In the script output, compute it by summing `credit_eur` across all sell rows in `<year>_transactions.csv`.

---

## Are penalty amounts rounded to the nearest euro?

Yes. The DGFiP rounds all tax amounts to the nearest euro. The penalty chain is:

```
net_gain_rounded  = round(net_gain)           # the integer entered on the form
tax_owed          = round(net_gain_rounded × 0.30)
late_interest     = round(tax_owed × 0.002 × months_delay)
surcharge         = round(tax_owed × penalty_rate)
total_due         = tax_owed + late_interest + surcharge
```

All three scripts (`yuh_csv_ifu.py`, `wise_csv_ifu.py`, `unified_readme.py`) follow this chain.

---

## What is the SIP?

**Service des Impôts des Particuliers** — the local French tax office handling individual taxpayers. It is where you go (in person, by phone, or via your online *espace particulier*) to regularize a late declaration, ask a tax question, or negotiate a payment plan.

---

## Does Wise provide raw transaction data for investments?

Yes, via two formats:

| Format | File pattern | Use |
|--------|-------------|-----|
| CSV | `wise_assets_statement_*.csv` | **Primary input** — complete raw history (BUY, SELL, FEE_CHARGE rows) including unrealized positions |
| PDF | `wise_tax_statement_*.pdf` | Cross-check only — pre-computed FIFO summary; does not include buys for positions still held at year-end |

The CSV is exported from the Wise account under Assets → Statement. The PDF is the annual tax report produced by Wise.

---

## Which Yuh activity types generate fees?

The main ones are:

| Activity type | What triggers it |
|---|---|
| `BANK_ORDER_EXECUTED` | Manual currency exchange |
| `BANK_AUTO_ORDER_EXECUTED` | Automatic CHF ↔ foreign currency exchange on invest orders |
| `INVEST_RECURRING_ORDER_EXECUTED` | Recurring invest order commission |
| `INVEST_ORDER_EXECUTED` | One-off invest order commission |

`REWARD_RECEIVED`, `PAYMENT_TRANSACTION_IN/OUT`, and `CASH_TRANSACTION_*` rows carry zero fees and do not appear in the `fees_by_activity.py` output.

---

## Can I optimise my Wise holdings for tax efficiency?

From a tax mechanics standpoint only (not investment advice):

- **Accumulating funds are already optimal**: `LU0852473015` (MSCI World) and `IE00B41N0724` (EUR Interest) reinvest internally — no dividend tax drag, gains taxed only on disposal.
- **Frequent small buy/sell cycles** (Wise's automatic rebalancing) do not create a tax inefficiency under PMP: partial sells against an average cost basis produce the same net gain as a single larger sell, mathematically.
- **Management fees** are the main cost drag, but as noted above they cannot offset the tax. This is a structural limitation of holding through a platform that charges external fees rather than embedding them in the NAV.

For questions about whether to switch platforms, change allocation, or restructure holdings, consult a *conseil en gestion de patrimoine* (CGP) who knows your full financial picture.
