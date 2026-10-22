# Model Council Companion

The companion runs on a user's computer and lets a hosted Model Council browser app work with a folder selected on that computer. It runs locally and sends file context to the hosted app and configured model provider as needed for a Workspace run.

## Install

```bash
python -m pip install model-council-companion
```

Python 3.10 or later is required. On Linux, Tk support may need to be installed separately for the native folder chooser.

## Run and pair

Start the companion with the exact HTTPS origin of the hosted Model Council app:

```bash
model-council-companion --origin https://your-app.example.com
```

For local development, `http://localhost:8787` and `http://127.0.0.1:8787` are also accepted. The companion prints a one-time pairing code and listens on `127.0.0.1:8766`. Keep its terminal open. In the app's Workspace tab, enter the code, pair, and select a folder.

The companion only accepts requests from the configured app origin, requires a pairing token, and serves on loopback. Workspace file and command actions remain subject to the app's plan review, diff approval, and command approval flows. Commands run with the local user's permissions, in the selected folder as their working directory.

## Development

From this repository, run `python -m app.companion --origin https://your-app.example.com` to use the same companion code during development.

## Publish a release

After creating the `model-council-companion` project on PyPI and checking that the name is available to your account, build and validate the artifacts:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Upload the checked artifacts with a PyPI API token:

```bash
python -m twine upload dist/*
```
