def normalize_value(raw: str) -> float:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    return float(cleaned)
