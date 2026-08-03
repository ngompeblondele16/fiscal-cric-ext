"""Constantes métier — classification RECHERCHEV (processus Excel CRIC EXT)."""

# Organisation utilisatrice de l'application
ORGANISATION_NAME = "Centre Régional des Impôts du Centre Ext"
ORGANISATION_SHORT = "CRIC EXT"

# Seuil « néant » : montant DÉCLARÉ (consolidé) de 0 à 10 FCFA inclus.
MONTANT_NEANT_MAX = 10.0

# États stockés en base (Contribuable.etat)
ETAT_DEFAILLANT = 0    # #N/A RECHERCHEV — absent du consolidé (n'a pas déclaré)
ETAT_NEANT = 1         # Présent, montant déclaré 0 à 10 FCFA
ETAT_RELICATAIRE = 2   # A déclaré (montant > 10) mais rien payé
ETAT_DECLARANT = 3     # A déclaré et payé (montant consolidé > 10, montant payé > 0)

ETAT_LABELS = {
    ETAT_DEFAILLANT: 'Défaillant',
    ETAT_NEANT: 'Néant',
    ETAT_RELICATAIRE: 'Relicataire',
    ETAT_DECLARANT: 'Déclarant',
}


def classify_from_declaration(montant_declare, montant_paye=None, found_in_consolidated=True, **_ignored):
    """
    RECHERCHEV phase 2 — fichier en ligne vs consolidé (montant déclaré + payé).

    1. #N/A (NIU absent du consolidé) → défaillant (0)
    2. Montant 0 à 10 FCFA → néant (1)
    3. Montant > 10 et rien payé → relicataire (2)
    4. Montant > 10 et payé (> 0) → déclarant (3)
    """
    if not found_in_consolidated:
        return ETAT_DEFAILLANT
    montant = float(montant_declare or 0)
    if montant <= MONTANT_NEANT_MAX:
        return ETAT_NEANT
    paye = 0.0 if montant_paye is None else float(montant_paye or 0)
    if paye <= 0:
        return ETAT_RELICATAIRE
    return ETAT_DECLARANT


def classify_from_declared_amount(montant_declare, found_in_consolidated):
    return classify_from_declaration(montant_declare, None, found_in_consolidated)
