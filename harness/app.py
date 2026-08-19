from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from harness.auth import new_session_token, verify_password
from harness.config import Config, load_config
from harness.isolation import Stage
from harness.provider import get_provider
from harness.runtime import NEXT_DOLLAR, execute_run
from harness.store import Store, User

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "harness_session"


class Credentials(BaseModel):
    username: str
    password: str


class RunRequest(BaseModel):
    repo_id: str
    objective: str = Field(min_length=1, max_length=20000)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(config.data_dir / "harness.db")
    store.initialize()
    provider = config.provider_instance or get_provider(config.provider_name)

    app = FastAPI(title="Agent Harness", docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.store = store
    app.state.provider = provider

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(detail, status_code=exc.status_code)
        return JSONResponse({"error": str(detail)}, status_code=exc.status_code)

    def current_user(request: Request) -> User:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail={"error": "authentication required"})
        user = store.user_for_session(token)
        if user is None:
            raise HTTPException(status_code=401, detail={"error": "authentication required"})
        return user

    def set_session(response: Response, user: User) -> None:
        token = new_session_token()
        store.create_session(user.id, token)
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=60 * 60 * 24 * 7,
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/login")
    def login_page() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/app.js")
    def app_js() -> FileResponse:
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/app.css")
    def app_css() -> FileResponse:
        return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.post("/api/signup")
    def signup() -> dict:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "accounts are not created in the browser; request access by email"
            },
        )

    @app.post("/api/login")
    def login(body: Credentials, response: Response) -> dict:
        user = store.get_user_by_username(body.username)
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail={"error": "invalid username or password"})
        set_session(response, user)
        return {"username": user.username, **_provider_public()}

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict:
        token = request.cookies.get(COOKIE)
        if token:
            store.delete_session(token)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    def _provider_public() -> dict:
        from harness.provider import live_endpoint, reasoning_effort_for

        name = getattr(provider, "name", config.provider_name)
        model = None
        reasoning = None
        if name != "deterministic":
            try:
                model = live_endpoint()[2]
            except RuntimeError:
                model = os.environ.get("HARNESS_MODEL")
            if model:
                reasoning = reasoning_effort_for(model)
        return {
            "provider": {"name": name, "model": model, "reasoning": reasoning},
            "mission": NEXT_DOLLAR,
        }

    @app.get("/api/me")
    def me(request: Request) -> dict:
        user = current_user(request)
        return {"username": user.username, **_provider_public()}

    @app.get("/api/repos")
    def repos(request: Request) -> dict:
        current_user(request)
        listed = [
            {"id": repo.id, "name": repo.name, "path": repo.name}
            for repo in store.list_repos(config.workspace_roots)
        ]
        return {"repos": listed}

    @app.get("/api/runs")
    def runs(request: Request) -> dict:
        user = current_user(request)
        return {"runs": [run.public_dict() for run in store.list_runs(user.id)]}

    @app.post("/api/runs", status_code=201)
    def create_run(body: RunRequest, request: Request) -> dict:
        user = current_user(request)
        repo = store.repo_by_id(body.repo_id, config.workspace_roots)
        if repo is None:
            raise HTTPException(status_code=404, detail={"error": "repository not found"})
        run = store.create_run(user.id, repo.id, body.objective.strip())
        thread = threading.Thread(
            target=execute_run,
            kwargs={
                "run_id": run.id,
                "store": store,
                "config": config,
                "provider": provider,
            },
            daemon=True,
        )
        thread.start()
        return run.public_dict()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, request: Request) -> dict:
        user = current_user(request)
        run = store.get_run(run_id)
        if run is None or run.user_id != user.id:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        return run.public_dict()

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str, request: Request) -> dict:
        user = current_user(request)
        run = store.get_run(run_id)
        if run is None or run.user_id != user.id:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        updated = store.request_stop(run_id)
        return (updated or run).public_dict()

    @app.post("/api/runs/{run_id}/publish")
    def publish_run(run_id: str, request: Request) -> dict:
        user = current_user(request)
        run = store.get_run(run_id)
        if run is None or run.user_id != user.id:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        if run.status != "completed" or not (run.verification or {}).get("passed"):
            raise HTTPException(
                status_code=400, detail={"error": "only a verified completed run can be published"}
            )
        if not run.stage_path:
            raise HTTPException(status_code=400, detail={"error": "run has no isolated stage"})
        repo = store.repo_by_id(run.repo_id, config.workspace_roots)
        if repo is None:
            raise HTTPException(status_code=404, detail={"error": "repository not found"})
        Stage(id=run.id, source=repo.path, root=Path(run.stage_path)).publish()
        store.add_event(run_id, "result", "Published verified files into the selected repository.")
        published = store.get_run(run_id)
        if published is None:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        return published.public_dict()

    return app
