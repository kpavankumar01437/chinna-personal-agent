from app.math_tools import parse_total


def test_parse_total_normalizes_currency():
    assert parse_total("$1,240.50") == 1240.50
