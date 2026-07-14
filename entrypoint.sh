#!/bin/sh
set -eu

su www-data -s /bin/sh -c "sh /opt/nginx/nginx.sh" || echo "[entrypoint] nginx start failed (non-fatal for Ollama-local mode, continuing)"

# The proxy listens on localhost:11434 and forwards requests to LLM_SERVER_LOCAL_URL.
if [ "${provider:-}" = "Ollama-local" ]; then
  python3 /opt/llm_proxy.py &
  sleep 2
fi

# Scrub environment: only allowlisted, non-secret vars survive.
SAFE_VARS="HOME USER PATH HOSTNAME TERM LANG LC_ALL \
  PYTHONDONTWRITEBYTECODE PYTHONUNBUFFERED \
  HF_HOME SENTENCE_TRANSFORMERS_HOME HF_HUB_OFFLINE TRANSFORMERS_OFFLINE \
  OMEGACLAW_DIR MEMORY_DIR LLM_SERVER_LOCAL_URL TEST_SERVER_IP \
  OLLAMA_API_KEY ASI_API_KEY ASIONE_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY \
  provider LLM OMEGACLAW_AUTH_SECRET \
  ALIS_API_BASE_URL ALIS_API_TOKEN"

env_args=""
for var in $SAFE_VARS; do
  eval val=\${$var:-}
  if [ -n "$val" ]; then
    env_args="$env_args $var=$val"
  fi
done

exec env -i $env_args su nobody -s /bin/sh -c "sh run.sh run.metta $*"
