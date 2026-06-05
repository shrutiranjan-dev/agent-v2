#!/usr/bin/env bash
set -euo pipefail

ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
ollama pull llama3.1:8b

if ollama pull deepseek-coder-v2:16b; then
  echo "Pulled deepseek-coder-v2:16b"
else
  echo "deepseek-coder-v2:16b unavailable; continuing"
fi

