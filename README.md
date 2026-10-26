# Model Council

Model Council is a browser-based app with two modes:

- **Council** sends a question to multiple model providers independently. You choose which completed answers to give a chair model, which writes the final synthesis.
- **Workspace** uses one selected model as a coding agent. It reviews a codebase, proposes a plan for your approval, stages file changes as diffs, and requests approval for commands and changes outside the approved plan.

The app runs locally with FastAPI, or can be hosted so users can connect a local folder through the companion program. Provider credentials are entered in the browser and sent with requests; they are not configured as server environment variables.

## Requirements

- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/) for local development
- Docker, if you want to run Redis or the app in a container
- API credentials for the cloud providers you plan to use
- [Ollama](https://ollama.com/) and a downloaded model if you want to use a local model

Redis is optional. Without it, the app still runs, but conversation history and usage analytics that depend on Redis are unavailable.

## Run locally

Install the project and development dependencies:

```bash
uv sync --extra web --extra dev
```

Start the app from the repository root:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload --reload-dir app
```

Open [http://localhost:8787](http://localhost:8787). The API health endpoint is [http://localhost:8787/api/health](http://localhost:8787/api/health).

The default Redis URL is `redis://127.0.0.1:6379/0`. To enable Redis-backed history and analytics, run Redis separately, for example:

```bash
docker run -d --name model-council-redis -p 6379:6379 redis:7
```

To point the app at a different Redis instance, set `MODEL_COUNCIL_REDIS_URL` in `.env`. Other server settings include:

| Setting | Purpose | Default |
| --- | --- | --- |
| `MODEL_COUNCIL_REDIS_URL` | Redis connection for history and usage analytics | `redis://127.0.0.1:6379/0` |
| `MODEL_COUNCIL_MEMORY_TTL` | History retention in seconds | `86400` |
| `MODEL_COUNCIL_MEMORY_MAX_ROUNDS` | Maximum saved rounds per session | `8` |
| `MODEL_COUNCIL_WORKSPACE_ROOT` | Server-side Workspace folders; separate multiple roots with commas | Repository `workspace/` folder |
| `MODEL_COUNCIL_ALLOWED_ORIGINS` | Additional browser origins allowed by the server | Empty |
| `MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA` | Permit direct server connections to remote Ollama URLs | `false` |
| `MODEL_COUNCIL_ALLOW_NETWORK` | Permit binding the app to a non-loopback address | `false` |

Keep `.env` and API credentials out of source control. The app refuses non-loopback binds unless `MODEL_COUNCIL_ALLOW_NETWORK=1` is set.

## Providers and Council mode

The app supports OpenAI Responses, OpenRouter, Anthropic Messages, Ollama, Azure OpenAI, and compatible Responses API endpoints. Enable and configure providers in the browser UI. OpenRouter models can be refreshed and searched from the provider card; the Azure/custom card accepts a deployment or model, endpoint, and authentication settings.

For each Council round, enabled providers answer independently and stream results as they complete. Failed or skipped members do not discard successful answers. Select one or more completed submissions and choose a chair to synthesize them. When members disagree, the chair reports the conflict and gives its own evidence-based synthesis. Redis enables saved conversation history between rounds.

## Ollama

For a local Ollama server, start Ollama with the app origin allowed by its browser CORS policy. For local development:

```bash
OLLAMA_ORIGINS="http://localhost:8787" ollama serve
```

Pull a model, then in the UI set the Ollama server URL to `http://localhost:11434` and refresh the model list:

```bash
ollama pull gemma4
```

For local Ollama URLs, the browser relays requests over the app's WebSocket connection. This works when FastAPI is in Docker or hosted, because the browser user's machine contacts its own Ollama server. For a remote Ollama URL, the FastAPI server connects directly; set `MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA=1` only when that is intended. Use HTTPS for the hosted app and add its exact origin to `OLLAMA_ORIGINS` on the machine running Ollama.

## Workspace mode

Workspace is a single-model coding agent, not a multi-model council. Select an enabled provider and model in **Agent model**, choose a folder, describe the task, and start a run.

### Plan and implementation flow

1. The agent receives a bounded file tree, the task, project documentation, and the previous session handoff when available.
2. It detects Python, Rust, Go, or JavaScript/TypeScript from project manifests and file extensions. If a workspace contains multiple supported languages, task references can select the target. If the category is still ambiguous, the plan asks you to add an explicit `Project category: python|rust|golang|javascript` choice before implementation.
3. The agent reads Markdown project material through the selected workspace backend. It keeps shared agent rules and the selected language guide, selects task-relevant sections from workspace Markdown, removes duplicate content, and limits the context sent to the model. Workspace documents are treated as untrusted reference material.
4. Review, edit, then approve or reject the generated plan. Paused plans can be resumed, discarded, or rejected from the app's plan controls.
5. After approval, the agent explores and implements in bounded steps. Proposed file edits appear as diffs. Files and commands listed in the approved plan can proceed under that approval; out-of-plan edits and commands require another confirmation. You can stop a run at a step boundary.
6. The agent performs a startup/preflight check before implementation and again after changes. For web apps, the check uses a fresh loopback port and stops the temporary server after checking its response.
7. The run writes `.model_council/plans/last_session.md` in the selected workspace. Later runs receive it as untrusted historical context and verify its claims against current files.

The agent defaults to 20 steps and allows up to 40. File browsing is bounded by tree depth and size; hidden paths, binary files, symlink escapes, and files over 120 KB are refused. Commands have a timeout and capped output and run with the permissions of the server process or local companion. A workspace path boundary does not sandbox shell commands from accessing other paths; review command approvals carefully.

### Choose a workspace location

**Server folder:** With a local app, the default is the repository's `workspace/` folder. Set `MODEL_COUNCIL_WORKSPACE_ROOT` to one or more server-side folders to make them available in the Workspace folder picker. When the app runs in Docker, mount the target folder into the container and set the variable to its container path. Commands then run inside the container, so the required language runtimes and tools must be installed there.

**Local folder with the companion:** For a hosted app, the companion lets the browser app work with a folder on the user's computer. The companion serves only on loopback, checks the configured app origin, and requires a pairing token. File context and task prompts are sent through the hosted app to the selected model provider.

Install and start the companion on the computer that has the folder:

```bash
python -m pip install model-council-companion
model-council-companion --origin https://your-app.example.com
```

Keep the terminal open. In **Workspace → Local folder**, enter the one-time pairing code printed in the terminal, pair the browser, then choose a folder. For local app development, install the package from this repository with `python -m pip install -e .` and run:

```bash
model-council-companion --origin http://127.0.0.1:8787
```

On Linux, the operating system's Tk package may be needed for the folder chooser. The companion runs commands with the local user's permissions; use it only with folders and commands you trust.

## Docker Compose

The included Compose file runs the web app and expects Redis on the host by default. Start it with:

```bash
docker compose up --build
```

The Compose configuration publishes port `8787`, binds the app to the container interface, and sets the network-bind opt-in. For server-side Workspace access to another codebase, uncomment and configure the workspace volume and `MODEL_COUNCIL_WORKSPACE_ROOT` entries in `docker-compose.yml`. Ollama running on the browser user's machine can still use the browser relay at `http://localhost:11434`.

For a hosted deployment, put TLS and authentication in front of the app, configure `MODEL_COUNCIL_ALLOWED_ORIGINS` for the app's browser origin, and set appropriate Ollama origins on users' local Ollama installations. The app is designed for local-first use and does not provide user authentication itself.

## Tests

Install development dependencies if you have not already, then run:

```bash
uv run pytest tests -v
```

The tests mock model-provider calls and do not require real provider credentials, Redis, or Ollama.
