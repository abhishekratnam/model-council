"""Local companion that grants the hosted browser app bounded workspace access.

Run with ``model-council-companion --origin https://council.example``. The
pairing code is printed only to this terminal; the resulting bearer token is
kept in the browser tab's session storage.
"""
import argparse
import asyncio
import hmac
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from model_council_companion.runtime import CouncilError
from model_council_companion import workspace


def create_companion_app(origin: str, pair_code: str | None = None) -> tuple[FastAPI, dict[str, Any]]:
    origin = origin.rstrip("/")
    state: dict[str, Any] = {
        "origin": origin,
        "pair_code": pair_code or secrets.token_urlsafe(24),
        "token": "",
        "root": "",
    }
    app = FastAPI(title="Model Council Local Companion", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[],
        max_age=300,
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if host not in {"localhost", "127.0.0.1", "[::1]"}:
            return JSONResponse(status_code=403, content={"error": "Local companion accepts loopback hosts only."})
        request_origin = request.headers.get("origin")
        if request_origin != origin:
            return JSONResponse(status_code=403, content={"error": "Browser origin is not paired with this companion."})
        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    def authorize(authorization: str | None) -> None:
        token = authorization.removeprefix("Bearer ") if authorization else ""
        if not state["token"] or not hmac.compare_digest(token, state["token"]):
            raise HTTPException(status_code=401, detail="Pair this browser with the local companion first.")

    @app.exception_handler(CouncilError)
    async def council_error_handler(_: Request, error: CouncilError):
        return JSONResponse(status_code=400, content={"error": str(error)})

    @app.post("/pair")
    async def pair(request: Request):
        body = await request.json()
        candidate = body.get("code", "") if isinstance(body, dict) else ""
        if not isinstance(candidate, str) or not hmac.compare_digest(candidate, state["pair_code"]):
            raise HTTPException(status_code=401, detail="Pairing code is incorrect.")
        state["token"] = secrets.token_urlsafe(32)
        state["pair_code"] = secrets.token_urlsafe(24)
        return {"token": state["token"], "paired": True}

    @app.get("/status")
    async def status(authorization: str | None = Header(default=None)):
        authorize(authorization)
        return {"paired": True, "root": state["root"], "connected": True}

    @app.post("/pick")
    async def pick(authorization: str | None = Header(default=None)):
        authorize(authorization)
        # Tk's native file dialog must run on the process main thread on macOS.
        folder = _choose_folder()
        if not folder:
            return {"selected": False, "root": state["root"]}
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise CouncilError("The selected path is not a folder.")
        state["root"] = str(root)
        return {"selected": True, "root": state["root"]}

    @app.post("/workspace/{operation}")
    async def workspace_operation(operation: str, request: Request,
                                  authorization: str | None = Header(default=None)):
        authorize(authorization)
        if not state["root"]:
            raise CouncilError("Choose a local workspace folder first.")
        body = await request.json()
        if not isinstance(body, dict):
            raise CouncilError("Request body must be a JSON object.")
        root = Path(state["root"])
        requested_root = body.get("workspace_root")
        if requested_root is not None and requested_root != str(root):
            raise CouncilError("The selected local folder changed during this run. Stop and start the Workspace run again.")
        actions = {
            "list_tree": lambda: workspace.list_tree(str(body.get("path", "") or ""), root),
            "search": lambda: workspace.search_workspace(body.get("query", ""), body.get("is_regex") is True, root),
            "read_file": lambda: workspace.read_file(
                body.get("path", ""), body.get("offset", 1), body.get("limit"), root),
            "stage_write": lambda: workspace.stage_write(body.get("path", ""), body.get("content"), root),
            "stage_edit": lambda: workspace.stage_edit(body.get("path", ""), body.get("find"), body.get("replace"), root),
            "apply_write": lambda: workspace.apply_write(body.get("path", ""), body.get("content", ""), root),
            "apply_edit": lambda: workspace.apply_edit(
                body.get("path", ""), body.get("find", ""), body.get("replace", ""), root),
            "run_command": lambda: workspace.run_command(body.get("command"), root, body.get("probe_url")),
            "read_session_log": lambda: {"content": workspace.read_agent_session_log(root)},
            "write_session_log": lambda: workspace.write_agent_session_log(body.get("content", ""), root),
        }
        action = actions.get(operation)
        if action is None:
            raise HTTPException(status_code=404, detail="Unknown workspace operation.")
        return await asyncio.to_thread(action)

    return app, state


def _choose_folder() -> str:
    """Open the operating system's folder chooser."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askdirectory(parent=root, title="Choose a Model Council workspace")
        finally:
            root.destroy()
    except Exception as error:
        raise CouncilError(f"Could not open the local folder picker: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Model Council local workspace companion.")
    parser.add_argument("--origin", required=True, help="Exact HTTPS origin of the hosted Model Council app")
    args = parser.parse_args()
    parsed_origin = urlsplit(args.origin)
    is_local_dev = args.origin in {"http://localhost:8787", "http://127.0.0.1:8787"}
    if (parsed_origin.scheme != "https" and not is_local_dev) or not parsed_origin.netloc or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
        parser.error("--origin must be HTTPS (HTTP is allowed only for local development).")
    app, state = create_companion_app(args.origin)
    print("Model Council local companion is listening on http://127.0.0.1:8766")
    print("Paired app origin: %s" % state["origin"])
    print("One-time browser pairing code: %s" % state["pair_code"])
    print("Keep this terminal open. Press Ctrl+C to stop the companion.")
    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="info")


if __name__ == "__main__":
    main()
