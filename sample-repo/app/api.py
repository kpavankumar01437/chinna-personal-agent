def greet_user(name: str) -> dict:
    return {"user": name}


def create_user(payload: dict) -> dict:
    return {"ok": True, "user": payload}
