# Model Council

Model Council is a local-first web app that asks OpenAI, Claude, an Ollama model, and optionally an Azure OpenAI or compatible Responses API deployment for independent answers. After the first round, you select the useful responses and appoint one completed member to synthesize a final answer.

It is deliberately dependency-free: Python's standard library serves the UI and makes the provider requests. It needs no database, container runtime, or Node.js process.

## Run it

Requirements: Python 3.10+ and, optionally, a running [Ollama](https://ollama.com/) installation with at least one pulled model.

```bash
cd /home/abhishek/Desktop/Projects/model-council
python3 server.py
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Enter the cloud API keys and model names you want to use, then click **Convene council**.

## Deploy on a Linux host

The lowest-overhead deployment is the included systemd service. It keeps Model Council on loopback only, needs no Docker or database, and restarts after a reboot or failure.

```bash
cd /path/to/model-council
./scripts/bootstrap-ollama.sh       # installs Ollama only if absent; then starts it and pulls gemma4 if needed
sudo ./scripts/install-systemd-service.sh
```

Check it with:

```bash
systemctl status model-council
curl http://127.0.0.1:8787/api/health
```

The service listens only on `127.0.0.1`, by design. For secure remote access, use an authenticated reverse proxy with TLS or an SSH tunnel; do not expose the app directly to the public internet because users enter provider keys in the browser.

To stop or remove the service:

```bash
sudo systemctl disable --now model-council
sudo rm /etc/systemd/system/model-council.service
sudo systemctl daemon-reload
```

## Deploy on Google Cloud Run

Cloud Run is suitable for the cloud-provider-only, BYOK version of this app. It
does not include Ollama: the container has no local Ollama server, so disable
that card for this deployment.

The included `Dockerfile` runs the application as an unprivileged user on the
port supplied by Cloud Run. Before deploying, decide the exact HTTPS origin
users will open, such as `https://council.example.com`. The server accepts
browser API and WebSocket requests only from that origin when
`MODEL_COUNCIL_ALLOWED_ORIGINS` is set.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud run deploy model-council \
  --source . \
  --region asia-south1 \
  --port 8080 \
  --timeout 300 \
  --concurrency 4 \
  --max-instances 3 \
  --allow-unauthenticated \
  --set-env-vars MODEL_COUNCIL_ALLOWED_ORIGINS=https://council.example.com
```

Map `council.example.com` as a Cloud Run custom domain before using that
command. If you use the generated `run.app` URL instead, set the environment
variable to that exact HTTPS URL. Deploying the service again is enough to
change the value.

`--allow-unauthenticated` only makes the Cloud Run endpoint reachable; it does
not provide user authentication. For a shared deployment, put an authentication
layer in front of it (for example, an identity-aware proxy) and keep the origin
allowlist to the single public HTTPS origin. Do not add API keys as Cloud Run
environment variables: BYOK keys remain in the browser tab and are used only
for the active request.

This app permits a configurable compatible endpoint, which is useful for a
trusted personal deployment. For a shared or public deployment, disable that
option in the UI or restrict it to trusted provider hosts before launch.

## Azure and custom Responses API endpoints

Enable the **Azure & custom** member in the dashboard to add an Azure-hosted deployment as a fourth council member or chair. In Azure mode, enter:

- the Azure resource endpoint, such as `https://YOUR_RESOURCE.openai.azure.com/openai`;
- the Azure deployment name in **Deployment / model**;
- the Azure API key and API version.

The dashboard sends that configuration as a request-scoped call to
`/openai/responses?api-version=...`; it does not write keys or endpoint settings to disk.

For an API gateway or another OpenAI-compatible deployment, select **Compatible Responses API** and enter its complete `/responses` URL. The Advanced JSON panel accepts the same fields, including `headers` and `query_params`:

```json
{
  "label": "Azure production",
  "mode": "azure",
  "model": "council-deployment",
  "endpoint": "https://my-resource.openai.azure.com/openai",
  "auth_type": "api-key",
  "api_key": "",
  "query_params": { "api-version": "2025-04-01-preview" },
  "headers": {}
}
```

Supported authentication values are `api-key`, `bearer`, and `none`. JSON is applied only to the open browser tab; its key is still cleared with **Clear keys & results**.

For Ollama, use the bootstrap script above or start it and pull a model manually:

```bash
ollama serve
ollama pull gemma4
```

Gemma 4 (`gemma4`) is the preselected local model and uses Ollama's native chat API, including its system-message support. Use **Refresh** in the Ollama card to confirm it is installed. You can replace `gemma4` with any other installed Ollama model, including a Gemma 4 variant such as `gemma4:e2b`, `gemma4:e4b`, or `gemma4:12b`.

## How a round works

1. The app sends the original question independently to each enabled member, in parallel.
2. Ollama answers and Ollama-led syntheses stream through a local WebSocket, so text appears as it is generated instead of waiting for the full response.
3. It displays every answer, skip reason, or provider failure without discarding the successful answers.
4. You choose which completed answers are evidence for the final pass.
5. The selected chair receives the original question plus clearly delimited, untrusted council submissions and writes a synthesis.

The implementation uses OpenAI's [Responses API](https://developers.openai.com/api/docs/guides/text), Anthropic's [Messages API](https://platform.claude.com/docs/en/api/messages), and Ollama's native [streaming chat endpoint](https://docs.ollama.com/api/chat). OpenAI requests set `store: false`.

## Key handling and local safety

- The server binds to `127.0.0.1` by default.
- For a Cloud Run or reverse-proxy deployment, set
  `MODEL_COUNCIL_ALLOWED_ORIGINS` to a comma-separated list of exact HTTPS
  origins. When it is unset, only `http` loopback browser origins are accepted.
- API keys are read from the form only for the current request. They are never written to files, browser storage, cookies, databases, environment files, or request logs.
- The browser only talks to the local server; the local server makes provider requests.
- Ollama defaults to `http://127.0.0.1:11434` and rejects non-loopback URLs to avoid becoming an SSRF proxy. To intentionally use a remote Ollama host, launch with `MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA=1`.
- Responses support a safe Markdown subset (headings, lists, emphasis, quotes, code, and links). Provider HTML is never inserted into the page.
- The chair is instructed to treat council output as untrusted reference material, helping guard against prompt injection embedded in a member's answer.

Do not expose this server to a network unless you understand the risk of entering provider keys in a browser. A non-loopback bind requires an explicit `--allow-network` flag.

## Test it

The tests use mocks only; they do not contact OpenAI, Anthropic, or Ollama and do not require real keys.

```bash
python3 -m unittest discover -s tests -v
```

## Project layout

```text
model-council/
├── deploy/
│   └── model-council.service       # systemd service template (loopback only)
├── scripts/
│   ├── bootstrap-ollama.sh         # idempotently install/start Ollama and pull gemma4
│   └── install-systemd-service.sh  # install and start the Model Council service
├── server.py          # HTTP server, validation, security controls, provider adapters
├── static/
│   ├── index.html     # Local-first UI
│   ├── styles.css     # Responsive visual design
│   └── app.js         # Browser-only UI state; no storage use
└── tests/
    └── test_server.py # Adapter and council-flow tests
```
