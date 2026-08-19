from __future__ import annotations

from harness.auth import hash_password, validate_password, validate_username
from harness.store import Store, User


def create_account(store: Store, username: str, password: str) -> User:
    username = validate_username(username)
    password = validate_password(password)
    if store.get_user_by_username(username):
        raise ValueError("username already taken")
    return store.create_user(username, hash_password(password))
