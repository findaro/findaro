import hashlib
import secrets


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def new_key(kind: str) -> str:
    return f"fdr_{kind}_{secrets.token_urlsafe(24)}"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
