"""Generate the supplier contract corpus, the platform's unstructured source.

Everything else in this project arrives as rows. Contracts do not: they are prose, and
what the business needs out of them (the delivery window a supplier actually committed
to, the penalty owed when it is missed) is buried in a clause rather than sitting in a
column. That gap is the reason this corpus exists. The warehouse already knows what
suppliers *did*; these documents are what they *promised*, and the interesting number is
the difference.

Two document types are written:

  * a master framework contract per supplier, and
  * an amendment for a few of them, which supersedes the delivery or penalty clause of
    the contract it references.

The amendments matter. With them, "what lead time applies to this supplier now" cannot be
answered by finding a merely relevant passage, because the original clause is still in the
corpus and still reads perfectly plausibly. Retrieval has to prefer the amendment, and
extraction has to respect effective dates.

Ground truth is written alongside the documents, to a separate file. It exists so the
extraction step can be scored rather than eyeballed, and nothing in the extraction path
is allowed to read it.

Run the dimension generator first, then:

    python ingestion/generate_supplier_documents.py
"""
from __future__ import annotations

import random
import textwrap
from datetime import date, timedelta

import pandas as pd

from config import HISTORY_START, N_CONTRACT_AMENDMENTS, RAW_DATA_DIR, SEED

MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

# Clause bodies are written as single lines and wrapped after substitution, so a short
# value cannot leave the ragged half-line that gives a filled-in template away.
WRAP_WIDTH = 88

# Amendments take effect part-way through the history window, so there is a before and an
# after inside the period the existing facts already cover.
AMENDMENT_OFFSET_DAYS = 45

PENALTY_CAPS_PCT = [5, 10, 15]
MIN_ORDER_QUANTITIES = [50, 100, 200, 500]
PAYMENT_TERMS_DAYS = [30, 45, 60]
QUALITY_TOLERANCES_PCT = [1.0, 2.0, 3.0]
NOTICE_PERIODS_DAYS = [30, 60, 90]

CONTRACT_TEMPLATE = """CONTRAT-CADRE D'APPROVISIONNEMENT
Référence : {reference}
Date d'effet : {effective_date}

ENTRE LES SOUSSIGNÉS

NovaSupply SAS, société par actions simplifiée au capital de 5 000 000 EUR, dont le siège social est situé 12 rue de la Logistique, 75012 Paris, immatriculée au RCS de Paris sous le numéro 892 451 337, ci-après dénommée « l'Acheteur »,

ET

{supplier_name}, dont le siège social est situé à {city} ({country}), ci-après dénommée « le Fournisseur »,

IL A ÉTÉ CONVENU CE QUI SUIT.

Article 1 - Objet
Le présent contrat-cadre définit les conditions dans lesquelles le Fournisseur approvisionne l'Acheteur en produits référencés à son catalogue, pour l'ensemble des magasins du réseau NovaSupply situés sur le territoire français. Chaque commande donne lieu à l'émission d'un bon de commande qui vaut acceptation des présentes conditions.

Article 2 - Délai de livraison
Le Fournisseur s'engage à livrer toute commande dans un délai maximum de {lead_time} jours ouvrés à compter de la réception du bon de commande. Le délai court à compter du premier jour ouvré suivant la transmission de la commande. Toute livraison partielle ne suspend pas le décompte du délai pour le solde de la commande.

Article 3 - Pénalités de retard
Tout dépassement du délai stipulé à l'article 2 ouvre droit, de plein droit et sans mise en demeure préalable, au versement d'une pénalité égale à {penalty_rate} % du montant hors taxes de la commande concernée par jour calendaire de retard. Le montant cumulé des pénalités ne peut excéder {penalty_cap} % du montant total hors taxes de ladite commande. Les pénalités sont déduites de plein droit des sommes dues au Fournisseur.

Article 4 - Quantité minimale de commande
Le Fournisseur peut conditionner l'acceptation d'une commande au respect d'une quantité minimale de {min_order_qty} unités par référence. En deçà de ce seuil, l'Acheteur et le Fournisseur conviennent d'un regroupement de références au sein d'une même expédition.

Article 5 - Conditions de paiement
Les factures du Fournisseur sont payables à {payment_terms} jours à compter de leur date d'émission, par virement bancaire. Aucun escompte n'est consenti pour paiement anticipé.

Article 6 - Qualité et retours
Le Fournisseur garantit un taux de non-conformité inférieur à {quality_tolerance} % des unités livrées. Au-delà de ce seuil, l'Acheteur peut retourner l'intégralité du lot aux frais du Fournisseur. Les produits frais et surgelés font l'objet d'un contrôle de la chaîne du froid à réception, dont le résultat est opposable au Fournisseur.

Article 7 - Durée et résiliation
Le présent contrat est conclu pour une durée d'un an, renouvelable par tacite reconduction. Chaque partie peut y mettre fin par lettre recommandée avec accusé de réception moyennant un préavis de {notice_period} jours.

Fait à Paris, le {effective_date}, en deux exemplaires originaux.
"""

AMENDMENT_TEMPLATE = """AVENANT N° 1 AU CONTRAT-CADRE D'APPROVISIONNEMENT
Référence : {reference}
Contrat modifié : {base_reference}
Date d'effet : {effective_date}

ENTRE NovaSupply SAS, ci-après « l'Acheteur »,
ET {supplier_name}, ci-après « le Fournisseur ».

Les parties sont convenues de modifier le contrat-cadre référencé {base_reference} dans les conditions suivantes.

Article 1 - Modification du délai de livraison
Les stipulations de l'article 2 du contrat-cadre sont remplacées par les suivantes : le Fournisseur s'engage à livrer toute commande dans un délai maximum de {lead_time} jours ouvrés à compter de la réception du bon de commande.

Article 2 - Modification des pénalités de retard
Les stipulations de l'article 3 du contrat-cadre sont remplacées par les suivantes : tout dépassement du délai ouvre droit au versement d'une pénalité égale à {penalty_rate} % du montant hors taxes de la commande par jour calendaire de retard, plafonnée à {penalty_cap} % du montant total hors taxes de la commande.

Article 3 - Entrée en vigueur
Le présent avenant prend effet le {effective_date} et s'applique aux commandes émises à compter de cette date. Les autres stipulations du contrat-cadre demeurent inchangées.

Fait à Paris, le {effective_date}.
"""


def _seed() -> None:
    random.seed(SEED)


def _fr_date(day: date) -> str:
    """Dates as a French contract writes them, not as ISO-8601.

    The catalogue keeps the ISO value for downstream joins; only the prose is localised.
    """
    return f"{day.day} {MONTHS_FR[day.month - 1]} {day.year}"


def _fr_number(value: float | int) -> str:
    """French decimal separator: 1.3 reads as 1,3."""
    return str(value).replace(".", ",")


def _reflow(body: str) -> str:
    """Wrap the lines that substitution left over-long, and leave every other line alone.

    Only over-long lines are touched, which keeps the headings, the reference block and
    the signature line exactly where they were written.
    """
    lines = []
    for line in body.split("\n"):
        lines.append(textwrap.fill(line, width=WRAP_WIDTH) if len(line) > WRAP_WIDTH else line)
    return "\n".join(lines)


def load_suppliers() -> pd.DataFrame:
    return pd.read_csv(RAW_DATA_DIR / "suppliers" / "suppliers.csv")


def _terms(supplier: pd.Series) -> dict:
    """Draw the commercial terms a contract commits to.

    The delivery window is the supplier's nominal lead time rather than a fresh random
    number: the contract promises what the supplier is nominally capable of, so any breach
    later on comes from the reliability already simulated into the orders, not from terms
    rigged to be unmeetable.
    """
    return {
        "lead_time": int(supplier["nominal_lead_time_days"]),
        "penalty_rate": round(random.uniform(0.5, 2.0), 1),
        "penalty_cap": random.choice(PENALTY_CAPS_PCT),
        "min_order_qty": random.choice(MIN_ORDER_QUANTITIES),
        "payment_terms": random.choice(PAYMENT_TERMS_DAYS),
        "quality_tolerance": random.choice(QUALITY_TOLERANCES_PCT),
        "notice_period": random.choice(NOTICE_PERIODS_DAYS),
    }


def _amended_terms(terms: dict) -> dict:
    """Tighten the delivery window and reprice the penalty, the way a renegotiation would."""
    return {
        **terms,
        "lead_time": max(1, terms["lead_time"] - random.randint(1, 3)),
        "penalty_rate": round(min(3.0, terms["penalty_rate"] + random.uniform(0.3, 1.0)), 1),
        "penalty_cap": random.choice(PENALTY_CAPS_PCT),
    }


def _render(template: str, **values) -> str:
    """Substitute, localising the numbers on the way in, then re-wrap."""
    localised = {
        key: _fr_number(value) if isinstance(value, float) else value
        for key, value in values.items()
    }
    return _reflow(template.format(**localised))


def generate_documents(suppliers: pd.DataFrame):
    """Build every document plus the catalogue and ground-truth rows describing them."""
    documents, catalogue, truth = [], [], []

    amended_ids = set(
        random.sample(suppliers["supplier_id"].tolist(), N_CONTRACT_AMENDMENTS)
    )
    amendment_date = HISTORY_START + timedelta(days=AMENDMENT_OFFSET_DAYS)

    for _, supplier in suppliers.iterrows():
        supplier_id = supplier["supplier_id"]
        reference = f"CTR-2026-{supplier_id.split('-')[1]}"
        terms = _terms(supplier)

        documents.append((
            f"{reference}.txt",
            _render(
                CONTRACT_TEMPLATE,
                reference=reference,
                effective_date=_fr_date(HISTORY_START),
                supplier_name=supplier["supplier_name"],
                city=supplier["city"],
                country=supplier["country"],
                **terms,
            ),
        ))
        catalogue.append({
            "document_id": reference,
            "supplier_id": supplier_id,
            "document_type": "contrat_cadre",
            "supersedes": None,
            "effective_date": HISTORY_START.isoformat(),
            "file_name": f"{reference}.txt",
        })
        truth.append({"document_id": reference, "supplier_id": supplier_id, **terms})

        if supplier_id not in amended_ids:
            continue

        amendment_reference = f"{reference}-A1"
        amended = _amended_terms(terms)
        documents.append((
            f"{amendment_reference}.txt",
            _render(
                AMENDMENT_TEMPLATE,
                reference=amendment_reference,
                base_reference=reference,
                effective_date=_fr_date(amendment_date),
                supplier_name=supplier["supplier_name"],
                lead_time=amended["lead_time"],
                penalty_rate=amended["penalty_rate"],
                penalty_cap=amended["penalty_cap"],
            ),
        ))
        catalogue.append({
            "document_id": amendment_reference,
            "supplier_id": supplier_id,
            "document_type": "avenant",
            "supersedes": reference,
            "effective_date": amendment_date.isoformat(),
            "file_name": f"{amendment_reference}.txt",
        })
        truth.append({
            "document_id": amendment_reference, "supplier_id": supplier_id, **amended
        })

    return documents, pd.DataFrame(catalogue), pd.DataFrame(truth)


def main() -> None:
    _seed()
    suppliers = load_suppliers()
    documents, catalogue, truth = generate_documents(suppliers)

    out_dir = RAW_DATA_DIR / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    for file_name, body in documents:
        (out_dir / file_name).write_text(body, encoding="utf-8")

    catalogue.to_csv(out_dir / "catalogue.csv", index=False, encoding="utf-8")
    # Leading underscore, and never read by the extraction step. This is the answer key.
    truth.to_csv(out_dir / "_ground_truth.csv", index=False, encoding="utf-8")

    amendments = int((catalogue["document_type"] == "avenant").sum())
    print(f"wrote {len(documents):>4} documents -> {out_dir}")
    print(f"      {len(documents) - amendments:>4} contracts, {amendments} amendments")
    print(f"wrote {len(catalogue):>4} rows      -> {out_dir / 'catalogue.csv'}")


if __name__ == "__main__":
    main()
