"""Référentiel CFLP — centres de rattachement (SOA inclus)."""
import re
import unicodedata

CFLP_CENTRES = [
    "MONATÉLÉ",
    "NANGA EBOKO",
    "ESESKA",
    "NGOUMOU",
    "SA'A",
    "NKOABANG",
    "MFOU",
    "NTUI",
    "MBALMAYO",
    "MBANKOMO",
    "MBANDJOCK",
    "OBALA",
    "AKONOLINGA",
    "BAFIA",
    "SOA",
]

CFLP_GROUPS = {
    "CFLP": CFLP_CENTRES,
}

# Alias rétrocompatibilité (code interne)
CDI_CFLP = CFLP_CENTRES
CDI_CFPL = CFLP_CENTRES
CDI_GROUPS = CFLP_GROUPS


def get_all_cflp_labels():
    return list(CFLP_CENTRES)


def get_all_cdi_labels():
    return get_all_cflp_labels()


def _normalize_key(value):
    if not value:
        return ""
    s = str(value).strip()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


_CFLP_LOOKUP = {}
for label in CFLP_CENTRES:
    _CFLP_LOOKUP[_normalize_key(label)] = label

_EXTRA_ALIASES = {
    "monatele": "MONATÉLÉ",
    "nangaeboko": "NANGA EBOKO",
    "eseska": "ESESKA",
    "ngoumou": "NGOUMOU",
    "sa": "SA'A",
    "saa": "SA'A",
    "nkoabang": "NKOABANG",
    "mfou": "MFOU",
    "ntui": "NTUI",
    "mbalmayo": "MBALMAYO",
    "mbankomo": "MBANKOMO",
    "mbandjock": "MBANDJOCK",
    "obala": "OBALA",
    "akonolinga": "AKONOLINGA",
    "bafia": "BAFIA",
    "soa": "SOA",
}
_CFLP_LOOKUP.update(_EXTRA_ALIASES)

# Alias interne
_CDI_LOOKUP = _CFLP_LOOKUP


def normalize_cdi(value):
    """Normalise un libellé vers le centre CFLP canonique (majuscules)."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    key = _normalize_key(raw)
    if key in _CFLP_LOOKUP:
        return _CFLP_LOOKUP[key]
    for alias, label in _CFLP_LOOKUP.items():
        if len(key) >= 4 and (key in alias or alias in key):
            return label
    return raw.upper()


def infer_cdi_from_text(text):
    """Déduit un centre CFLP à partir d'un libellé de localité (ville, lieu-dit, etc.)."""
    if not text:
        return ""
    norm_text = _normalize_key(text)
    if not norm_text:
        return ""
    for label in sorted(CFLP_CENTRES, key=lambda x: len(_normalize_key(x)), reverse=True):
        key = _normalize_key(label)
        if key and key in norm_text:
            return label
    return ""
