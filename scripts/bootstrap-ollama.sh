#!/usr/bin/env bash
# Install and prepare the local model runtime used by Model Council.
# Usage: ./scripts/bootstrap-ollama.sh [model]

set -Eeuo pipefail

MODEL="${1:-gemma4}"
OLLAMA_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"

if ! command -v ollama >/dev/null 2>&1; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to install Ollama. Install curl and run this script again." >&2
    exit 1
  fi
  echo "Ollama is not installed. Installing it from ollama.com…"
  curl -fsSL https://ollama.com/install.sh | sh
fi

ollama_ready() {
  curl --fail --silent --show-error --max-time 3 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1
}

if ! ollama_ready; then
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    echo "Starting the Ollama system service…"
    sudo systemctl enable --now ollama
  else
    echo "Starting Ollama in the background…"
    nohup ollama serve >"${TMPDIR:-/tmp}/model-council-ollama.log" 2>&1 &
  fi

  for _ in {1..20}; do
    if ollama_ready; then break; fi
    sleep 1
  done
fi

if ! ollama_ready; then
  echo "Ollama did not become ready at ${OLLAMA_URL}. Check its service logs and try again." >&2
  exit 1
fi

if ollama list | awk 'NR > 1 { print $1 }' | grep --fixed-strings --line-regexp --quiet "${MODEL}"; then
  echo "Ollama model '${MODEL}' is already available."
else
  echo "Pulling '${MODEL}' for Model Council. This can take a while on the first run…"
  ollama pull "${MODEL}"
fi

echo "Ollama is ready with '${MODEL}'."
