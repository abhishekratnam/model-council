


# Model Council

Model Council is a local-first web app that asks OpenAI, OpenRouter, Claude, an Ollama model, and optionally an Azure OpenAI or compatible Responses API deployment for independent answers. After the first round, you select the useful responses and appoint one completed member to synthesize a final answer.

The application itself runs as a FastAPI service. For local development, Python dependencies are managed with `uv`, Uvicorn runs the FastAPI application, and Redis can run separately in Docker.

The application supports both host-native and Docker execution. 

## Requirements

Install the following:

- Python 3.10+
- `uv`
- Docker
- API keys for any cloud providers you want to use
- Ollama only if you want to use a local Ollama model

You do **not** need to run the application with Docker Compose for local development.

## Project layout

```text
model-council/
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── Dockerfile
├── docker-compose.yml
├── fastapi_server.py
├── memory.py
├── requirements.txt
└── README.md
```

## 1. Install dependencies with uv

From the project directory:

```bash
cd /path/to/model-council
uv sync
```

The root `pyproject.toml` declares the application and test dependencies. `uv sync` installs them into the project environment; `uv run` then uses that environment automatically.

## 2. Start Redis separately with Docker

Run Redis as an independent container:

```bash
docker run -d \
  --name model-council-redis \
  -p 6379:6379 \
  redis:7
```

Verify that the container is running:

```bash
docker ps
```

You can also test Redis directly:

```bash
docker exec model-council-redis redis-cli ping
```

Expected output:

```text
PONG
```

To stop Redis:

```bash
docker stop model-council-redis
```

To start the existing container again:

```bash
docker start model-council-redis
```

## 3. Configure environment variables

Create or update your `.env` file with the values required by the application.

### FastAPI running directly on the host

When Uvicorn runs directly on your machine, use:

```env
MODEL_COUNCIL_REDIS_URL=redis://127.0.0.1:6379/0
MODEL_COUNCIL_OLLAMA_URL=http://localhost:11434
```

### FastAPI running inside Docker

When the FastAPI application runs inside Docker and Redis runs on the host machine, use Docker's host gateway for Redis:

```env
MODEL_COUNCIL_REDIS_URL=redis://host.docker.internal:6379/0
MODEL_COUNCIL_OLLAMA_URL=http://localhost:11434
```

*Note: You do **not** need to use `host.docker.internal` for Ollama. Because Ollama requests are relayed through the user's browser (see Section 6), FastAPI does not need direct network access to Ollama.*

For example, the application can also use:

```env
MODEL_COUNCIL_MEMORY_TTL=86400
MODEL_COUNCIL_MEMORY_MAX_ROUNDS=8
MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA=1
MODEL_COUNCIL_WORKSPACE_ROOT=/absolute/path/to/any/codebase,/absolute/path/to/another/repo
```

`MODEL_COUNCIL_WORKSPACE_ROOT` points Workspace mode (Section 9) at one or more codebase folders — separate several paths with commas. Each configured folder appears in the Workspace tab's **Root** picker, so switching codebases needs no restart. When the variable is empty, the code agent uses the `workspace/` folder inside this repository (created on demand). Browsers cannot browse your disk, so the picker only offers these server-configured roots and the server rejects anything outside the list.

Keep provider API keys out of source control. Add `.env` to `.gitignore` if it is not already there. The browser-supplied provider keys should remain request-scoped and should not be committed to the repository.

## 4. Run the FastAPI application with Uvicorn

Start the application from the project root:

```bash
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787 --reload --reload-dir app
```

Open:

```text
http://localhost:8787
```

For a non-reloading local process:

```bash
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787
```

## 5. Run Redis and FastAPI together

You can start Redis first:

```bash
docker start model-council-redis 2>/dev/null || docker run -d --name model-council-redis -p 6379:6379 redis:7
```

Then start FastAPI in another terminal:

```bash
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787 --reload --reload-dir app
```

## 6. Ollama (Local BYOK & Browser Relay)

Ollama is optional. Model Council uses a **WebSocket Browser Relay** to connect to local Ollama instances. 

When a user enters `http://localhost:11434` (or `http://127.0.0.1:11434`) in the UI, council and Workspace mode send a WebSocket RPC message to the user's browser. The browser makes the request to local Ollama and streams the tokens back to the server. This keeps the same URL working when FastAPI runs inside Docker.

This means **local Ollama works seamlessly whether the app is running on your host, in Docker, or deployed to a production cloud server.**

### Setting up Ollama

If Ollama is installed locally, start it. **Important:** By default, Ollama blocks web browser requests (CORS). You must explicitly tell Ollama to allow requests from the Model Council web app.

**Mac/Linux:**
```bash
OLLAMA_ORIGINS="http://localhost:8787" ollama serve
```
*(Replace `http://localhost:8787` with your production domain, e.g., `https://your-app.com`, when deploying).*

**Windows (PowerShell):**
```powershell
$env:OLLAMA_ORIGINS="http://localhost:8787"; ollama serve
```

Pull a model, for example:

```bash
ollama pull gemma4
```

### UI Configuration
In the Model Council UI, set the "Local server" URL to:
```text
http://localhost:11434
```
*(Note: In modern browsers, `http://localhost` is treated as a secure context, while `http://127.0.0.1` may be blocked as "Mixed Content" if the app is served over HTTPS. Prefer `localhost` for the UI input).*

Use **Refresh** in the Ollama card in the UI to check installed models. If the application needs to connect to a remote Ollama server (e.g., via Ngrok or Tailscale), configure that URL explicitly. Remote URLs are called directly by the FastAPI server.

## 7. Provider configuration

The first council round can use the enabled providers independently.

Typical providers include:
- OpenAI Responses API
- OpenRouter Chat Completions API, with searchable model selection
- Anthropic Messages API
- Ollama
- Azure OpenAI
- OpenAI-compatible Responses API deployments

For Azure or a compatible Responses API endpoint, configure the provider through the UI rather than storing credentials in the repository.

## 8. How a round works

1. The app sends the original question independently to each enabled council member.
2. Responses are displayed as they arrive.
3. Successful answers remain available even when another provider fails or is skipped.
4. You select which completed answers should be used as evidence.
5. The selected chair receives the original question plus the selected council submissions and produces the final synthesis.

Ollama responses and Ollama-led synthesis stream through the application's WebSocket connection.

## 9. Workspace mode (single-provider code agent)

Workspace mode turns Model Council into a coding agent: choose one enabled provider and model
from the members panel (Ollama, OpenAI, OpenRouter, Claude, or Azure / custom). That single model
plans and drives the run while the agent explores a sandboxed codebase, stages changes, and asks
for approval before applying file edits or running commands.

1. Open the **Workspace · code agent** tab next to *Council debate*.
2. Enable and configure one provider in the members panel, then select its model under **Agent model**. Only that one model handles the run.
3. Browse the sandboxed file tree or search the code; click any file to read it with line numbers.
4. Describe the task (e.g. "Add a `remove_item` function to `shop/cart.py` with a test, then run pytest") and press **Run coder agent**.
5. The agent drafts an implementation plan first. Review it in the plan editor, make changes if needed, then approve it to continue or reject it to stop before implementation.
6. After approval, the agent reads project instructions and verifies the startup path. For web apps it starts the project on a fresh loopback port, checks that it responds, then stops that temporary process. After the requested changes, it repeats the check independently of any server already running on localhost.
7. The agent streams one JSON action per step (`list_tree`, `search`, `read_file`, `write_file`, `edit_file`, `run_command`, `done`, `fail`). Every proposed change appears as a unified diff and every command as a terminal card — **nothing is written or executed until you approve it**. **Stop** halts the run at the next step boundary.
8. After every run, `.model_council/plans/last_session.md` is updated at the selected workspace root, following the hidden plan-folder pattern used by tools such as ZCode. The next run receives that handoff alongside the current tree, then verifies its claims against the current files before editing.

### How it stays safe

- **Path jail**: every path is resolved inside the workspace root; dotfiles (`.git`, `.env`), symlink escapes, binary files, and files over 120 KB are refused.
- **Staged diffs**: `write_file`/`edit_file` only stage a diff. The server applies it after you click **Approve**, and `edit_file` re-validates at apply time.
- **Command allowlist**: approved argv lists only, with no shell, destructive tokens, or shell operators; commands time out and output is truncated. Web startup probes are limited to loopback hosts and stop the temporary process after the response check.
- **Bounded runs**: default 20 steps (max 40), per-step model timeout, 5-minute confirmation timeout, and a context-window trimmer for the selected model.
- Commands run with the server's environment, so tools like `pytest` must be installed in the Python environment that runs the server.

### Running Workspace mode in Docker

Two things change when the app runs in a container:

1. **Ollama is on the host.** Keep the UI's "Local server" field set to `http://localhost:11434` (or `http://127.0.0.1:11434`). Council and Workspace requests are relayed through the browser, so the URL points to the host Ollama even when FastAPI runs inside Docker. `host.docker.internal` is only needed if you intentionally configure a direct server-to-Ollama connection.
2. **The workspace folder must be mounted into the container** and commands run *inside* the container. Set `MODEL_COUNCIL_WORKSPACE_ROOT=/workspace` and mount your codebase at `/workspace` (see the commented volume in `docker-compose.yml`); `pytest`/`python` must exist in the image's environment.

For the smoothest Workspace-mode experience, run the app host-native (`uv run` / `.venv`) — Ollama, your codebase, and your Python tools are then all in the same environment.

Feasibility note: `qwen3-coder:30b` (MoE, ~3B active parameters, Q4_K_M ≈ 17 GB) runs comfortably on a 24 GB Apple-Silicon Mac when the context window is kept at ~16k tokens; `qwen3-coder:next`-class 80B models need ≥32 GB.

## 10. Health check

Once the server is running, verify the API:

```bash
curl http://localhost:8787/api/health
```

## 11. Run tests

Run the integration suite with:

```bash
uv run pytest tests -v
```

The default `dev` dependency group includes pytest and its HTTP test client. Tests use mocked model providers and do not require real API keys, Redis, Ollama, or a separately running app server.

## 12. Docker Compose

`docker-compose.yml` can be used when you want the application itself containerized.

When FastAPI runs inside Docker while Redis runs on the host, use:

```text
FastAPI container
    │
    └── redis://host.docker.internal:6379/0
```

*Note: Ollama does not need to be mapped here because the browser handles Ollama requests directly.*

For normal host-native local development, use:

```text
FastAPI / Uvicorn
    │
    ├── redis://127.0.0.1:6379/0
    │
    └── Browser Relay -> http://localhost:11434 (Ollama)
```

If Redis is another container on the same Docker network, use the Redis service name:

```text
redis://redis:6379/0
```

## 13. Security notes

The application is designed primarily as a local-first application.

For local development:
- Bind the FastAPI server to `127.0.0.1`.
- Do not expose the application directly to the public internet without TLS.
- Do not commit provider API keys.

For production deployment:
- Use an authenticated reverse proxy and TLS before exposing the application to other users.
- Because users can enter provider API keys in the browser, public deployment requires additional authentication and network controls.
- Users connecting local Ollama must run it with `OLLAMA_ORIGINS="https://your-production-domain.com" ollama serve`.

## Quick start

For a fresh local setup:

### Terminal 1 — Redis

```bash
docker run -d \
  --name model-council-redis \
  -p 6379:6379 \
  redis:7
```

### Terminal 2 — Ollama

```bash
OLLAMA_ORIGINS="http://localhost:8787" ollama serve
```

### Terminal 3 — FastAPI

```bash
cd /path/to/model-council
uv sync
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787 --reload --reload-dir app
```

For this host-native setup, your `.env` should point to:

```env
MODEL_COUNCIL_REDIS_URL=redis://127.0.0.1:6379/0
MODEL_COUNCIL_OLLAMA_URL=http://localhost:11434
```

Then open:

```text
http://localhost:8787
```

## Running the test suite

With uv, install and run the suite using the commands above. For a pip-managed virtual environment, install the development requirements and run pytest:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -v
```

The server preflight test starts its own short-lived HTTP server on a free loopback port.
