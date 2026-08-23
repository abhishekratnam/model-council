# Model Council

Model Council is a local-first web app that asks OpenAI, Claude, an Ollama model, and optionally an Azure OpenAI or compatible Responses API deployment for independent answers. After the first round, you select the useful responses and appoint one completed member to synthesize a final answer.

The application itself runs as a FastAPI service. For local development, Python dependencies are managed with `uv`, Uvicorn runs the FastAPI application, and Redis can run separately in Docker.

The application supports both host-native and Docker execution. The correct Redis and Ollama URLs depend on where the FastAPI process is running.

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

If the project does not already contain a `pyproject.toml`, initialize it first:

```bash
uv init
uv add -r requirements.txt
```

After that, use `uv run` for commands so the correct project environment is used automatically.

## 2. Start Redis separately with Docker

Run Redis as an independent container:

```bash
docker run -d   --name model-council-redis   -p 6379:6379   redis:7
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

The local application should use:

```text
redis://127.0.0.1:6379/0
```

If Redis is already running on port `6379`, do not start a second Redis container.

To stop Redis:

```bash
docker stop model-council-redis
```

To start the existing container again:

```bash
docker start model-council-redis
```

To remove it:

```bash
docker rm -f model-council-redis
```

## 3. Configure environment variables

Create or update your `.env` file with the values required by the application.

### FastAPI running directly on the host

When Uvicorn runs directly on your machine, use:

```env
MODEL_COUNCIL_REDIS_URL=redis://127.0.0.1:6379/0
MODEL_COUNCIL_OLLAMA_URL=http://127.0.0.1:11434
```

### FastAPI running inside Docker

When the FastAPI application runs inside Docker and Redis/Ollama run on the host machine, use Docker's host gateway:

```env
MODEL_COUNCIL_REDIS_URL=redis://host.docker.internal:6379/0
MODEL_COUNCIL_OLLAMA_URL=http://host.docker.internal:11434
```

`host.docker.internal` resolves to the host machine from inside the Docker container. In particular, `127.0.0.1` inside a container refers to the container itself, not the host.

For example, the application can also use:

```env
MODEL_COUNCIL_MEMORY_TTL=86400
MODEL_COUNCIL_MEMORY_MAX_ROUNDS=8
MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA=1
```

Keep provider API keys out of source control. Add `.env` to `.gitignore` if it is not already there.

Keep provider API keys out of source control. Add `.env` to `.gitignore` if it is not already there.

The browser-supplied provider keys should remain request-scoped and should not be committed to the repository.

## 4. Run the FastAPI application with Uvicorn

Start the application from the project root:

```bash
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787 --reload
```

Open:

```text
http://127.0.0.1:8787
```

For a non-reloading local process:

```bash
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787
```

The important pieces are:

- `fastapi_server` — the Python module containing the FastAPI application.
- `app` — the FastAPI application instance.
- `127.0.0.1` — keeps the development server local to the machine.
- `8787` — the application port.

## 5. Run Redis and FastAPI together

You can start Redis first:

```bash
docker start model-council-redis 2>/dev/null || docker run -d --name model-council-redis -p 6379:6379 redis:7
```

Then start FastAPI in another terminal:

```bash
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787 --reload
```

The resulting local architecture is:

```text
Browser
   │
   ▼
FastAPI / Uvicorn
127.0.0.1:8787
   │
   ▼
Redis
127.0.0.1:6379
   │
   └── Docker container
```

## 6. Ollama

Ollama is optional.

If Ollama is installed locally:

```bash
ollama serve
```

Pull a model, for example:

```bash
ollama pull gemma4
```

### FastAPI running directly on the host

Use the normal local Ollama address:

```text
http://127.0.0.1:11434
```

### FastAPI running inside Docker

Use:

```text
http://host.docker.internal:11434
```

Do **not** use `http://127.0.0.1:11434` from inside the container. There, `127.0.0.1` points back to the container itself.

For example, a Docker-based local setup can use:

```env
MODEL_COUNCIL_OLLAMA_URL=http://host.docker.internal:11434
```

The `host.docker.internal` hostname is the Docker-provided route from the container to the host machine.

Use **Refresh** in the Ollama card in the UI to check installed models.

If the application needs to connect to a different or remote Ollama server, configure that explicitly. Do not expose an Ollama endpoint publicly without appropriate network controls.

## 7. Provider configuration

The first council round can use the enabled providers independently.

Typical providers include:

- OpenAI Responses API
- Anthropic Messages API
- Ollama
- Azure OpenAI
- OpenAI-compatible Responses API deployments

For Azure or a compatible Responses API endpoint, configure the provider through the UI rather than storing credentials in the repository.

Supported authentication modes for compatible Responses API configurations are:

```text
api-key
bearer
none
```

## 8. How a round works

1. The app sends the original question independently to each enabled council member.
2. Responses are displayed as they arrive.
3. Successful answers remain available even when another provider fails or is skipped.
4. You select which completed answers should be used as evidence.
5. The selected chair receives the original question plus the selected council submissions and produces the final synthesis.

Ollama responses and Ollama-led synthesis can stream through the application's WebSocket connection.

## 9. Health check

Once the server is running, verify the API:

```bash
curl http://127.0.0.1:8787/api/health
```

If the application exposes the health endpoint, it should return a successful response.

## 10. Run tests

Run the test suite with:

```bash
uv run python -m unittest discover -s tests -v
```

The tests should use mocks and should not require real OpenAI, Anthropic, or Ollama credentials.

## 11. Docker Compose

`docker-compose.yml` can be used when you want the application itself containerized.

When FastAPI runs inside Docker while Redis and Ollama run on the host, use:

```text
FastAPI container
    │
    ├── redis://host.docker.internal:6379/0
    │
    └── http://host.docker.internal:11434
             │
             ├── Redis on host
             └── Ollama on host
```

For normal host-native local development, use:

```text
FastAPI / Uvicorn
    │
    ├── redis://127.0.0.1:6379/0
    │
    └── http://127.0.0.1:11434
```

If Redis is instead another container on the same Docker network, use the Redis service name rather than `localhost` or `host.docker.internal`, for example:

```text
redis://redis:6379/0
```

This keeps the application configuration explicit for each execution mode.

## 12. Security notes

The application is designed primarily as a local-first application.

For local development:

- Bind the FastAPI server to `127.0.0.1`.
- Do not expose the application directly to the public internet.
- Do not commit provider API keys.
- Keep Redis bound to the local machine unless remote access is explicitly required.
- Use an authenticated reverse proxy and TLS before exposing the application to other users.

Because users can enter provider API keys in the browser, public deployment requires additional authentication and network controls.

## Quick start

For a fresh local setup:

### Terminal 1 — Redis

```bash
docker run -d   --name model-council-redis   -p 6379:6379   redis:7
```

### Terminal 2 — FastAPI

```bash
cd /path/to/model-council
uv sync
uv run uvicorn fastapi_server:app --host 127.0.0.1 --port 8787 --reload
```

For this host-native setup, your `.env` should point to:

```env
MODEL_COUNCIL_REDIS_URL=redis://127.0.0.1:6379/0
MODEL_COUNCIL_OLLAMA_URL=http://127.0.0.1:11434
```

Then open:

```text
http://127.0.0.1:8787
```
