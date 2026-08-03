import re


NIU_REGEX = re.compile(r'^[PM]\d{12}[A-Za-z]$')


def normalize_niu(niu) -> str:
    """Nettoie et normalise un NIU (suppression espaces, majuscules)."""
    if niu is None or (isinstance(niu, float) and str(niu) == 'nan'):
        return ''
    s = str(niu).strip().upper().replace(' ', '')
    return s


def is_valid_niu(niu: str) -> bool:
    if not niu or not isinstance(niu, str):
        return False
    niu = normalize_niu(niu)
    if len(niu) != 14:
        return False
    return bool(NIU_REGEX.match(niu))
