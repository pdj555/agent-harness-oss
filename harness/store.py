from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from harness.auth import hash_session


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    created_at: str


@dataclass
class Repo:
    id: str
    name: str
    path: Path


@dataclass
class Run:
    id: str
    user_id: str
    repo_id: str
    objective: str
    status: str
    plan: list[str] = field(default_factory=list)
    investigating: str = ""
    active_work: str = ""
    events: list[dict] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    review: dict | None = None
    verification: dict | None = None
    blockers: list[str] = field(default_factory=list)
    result: str | None = None
    diff: str = ""
    stage_path: str | None = None
    stop_requested: bool = False
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("user_id", None)
        data.pop("stage_path", None)
        return data


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def create_user(self, username: str, password_hash: str) -> User:
        user = User(
            id=uuid4().hex,
            username=username,
            password_hash=password_hash,
            created_at=_now(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.password_hash, user.created_at),
            )
            self._conn.commit()
        return user

    def get_user_by_username(self, username: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return _user_from_row(row) if row else None

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_from_row(row) if row else None

    def create_session(self, user_id: str, token: str, days: int = 7) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (
                    hash_session(token),
                    user_id,
                    now.isoformat(),
                    (now + timedelta(days=days)).isoformat(),
                ),
            )
            self._conn.commit()

    def user_for_session(self, token: str) -> User | None:
        hashed = hash_session(token)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT users.* FROM users
                JOIN sessions ON sessions.user_id = users.id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (hashed, now),
            ).fetchone()
        return _user_from_row(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (hash_session(token),)
            )
            self._conn.commit()

    def list_repos(self, roots: list[Path]) -> list[Repo]:
        repos: list[Repo] = []
        for root in roots:
            resolved = root.resolve()
            if not resolved.is_dir():
                continue
            digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
            repos.append(Repo(id=f"{resolved.name}-{digest}", name=resolved.name, path=resolved))
        return repos

    def repo_by_id(self, repo_id: str, roots: list[Path]) -> Repo | None:
        for repo in self.list_repos(roots):
            if repo.id == repo_id:
                return repo
        return None

    def create_run(self, user_id: str, repo_id: str, objective: str) -> Run:
        now = _now()
        run = Run(
            id=uuid4().hex,
            user_id=user_id,
            repo_id=repo_id,
            objective=objective,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        self._write_run(run)
        return run

    def get_run(self, run_id: str) -> Run | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row) if row else None

    def list_runs(self, user_id: str) -> list[Run]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def request_stop(self, run_id: str) -> Run | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "stopped"}:
            return run
        return self.update_run(run_id, stop_requested=True, status="stopping")

    def add_event(self, run_id: str, kind: str, detail: str) -> Run:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        events = list(run.events)
        events.append({"kind": kind, "detail": detail, "at": _now()})
        return self.update_run(run_id, events=events)

    def update_run(self, run_id: str, **fields) -> Run:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        for key, value in fields.items():
            if not hasattr(run, key):
                raise AttributeError(key)
            setattr(run, key, value)
        run.updated_at = _now()
        self._write_run(run, insert=False)
        return run

    def _write_run(self, run: Run, insert: bool = True) -> None:
        payload = {
            "plan": run.plan,
            "investigating": run.investigating,
            "active_work": run.active_work,
            "events": run.events,
            "files_changed": run.files_changed,
            "checks": run.checks,
            "review": run.review,
            "verification": run.verification,
            "blockers": run.blockers,
            "result": run.result,
            "diff": run.diff,
            "stage_path": run.stage_path,
            "stop_requested": run.stop_requested,
        }
        with self._lock:
            if insert:
                self._conn.execute(
                    """
                    INSERT INTO runs
                    (id, user_id, repo_id, objective, status, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.id,
                        run.user_id,
                        run.repo_id,
                        run.objective,
                        run.status,
                        json.dumps(payload),
                        run.created_at,
                        run.updated_at,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, payload = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (run.status, json.dumps(payload), run.updated_at, run.id),
                )
            self._conn.commit()


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def _run_from_row(row: sqlite3.Row) -> Run:
    payload = json.loads(row["payload"])
    return Run(
        id=row["id"],
        user_id=row["user_id"],
        repo_id=row["repo_id"],
        objective=row["objective"],
        status=row["status"],
        plan=payload.get("plan") or [],
        investigating=payload.get("investigating") or "",
        active_work=payload.get("active_work") or "",
        events=payload.get("events") or [],
        files_changed=payload.get("files_changed") or [],
        checks=payload.get("checks") or [],
        review=payload.get("review"),
        verification=payload.get("verification"),
        blockers=payload.get("blockers") or [],
        result=payload.get("result"),
        diff=payload.get("diff") or "",
        stage_path=payload.get("stage_path"),
        stop_requested=bool(payload.get("stop_requested")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
