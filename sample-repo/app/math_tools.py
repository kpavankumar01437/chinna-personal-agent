from .helpers import normalize_number


def parse_total(raw: str) -> float:
    return normalize_number(raw)
