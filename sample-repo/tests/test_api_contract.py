from app.api import create_user, greet_user


def test_greet_user_returns_contract_message():
    assert greet_user("Ada") == {"message": "Hello, Ada"}


def test_create_user_requires_email():
    assert create_user({"name": "Maya"}) == {"ok": False, "error": "email is required"}


def test_create_user_returns_normalized_user():
    assert create_user({"name": "Maya", "email": " maya@example.com "}) == {
        "ok": True,
        "user": {"name": "Maya", "email": "maya@example.com"},
    }
