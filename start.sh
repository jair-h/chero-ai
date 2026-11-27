#!/usr/bin/env bash
set -e
# Railway/host arranque de Streamlit. Los secretos llegan por la variable
# STREAMLIT_SECRETS (contenido del secrets.toml) y se escriben al arrancar.
mkdir -p .streamlit
if [ -n "$STREAMLIT_SECRETS" ]; then
  printf '%s' "$STREAMLIT_SECRETS" > .streamlit/secrets.toml
fi
exec streamlit run app.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection true
