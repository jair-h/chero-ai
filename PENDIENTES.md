# Pendientes de Tentakl

## 🔑 Conectar Google Analytics (OAuth) — PENDIENTE de Jair
El código ya está listo (ver `integrations/README_ANALYTICS.md`). Falta que Jair,
**desde su laptop con la cuenta de Google de Tentakl**, haga una sola vez:

1. Google Cloud: crear proyecto → habilitar **Analytics Data API** + **Admin API**.
2. Crear **ID de cliente OAuth (web)** con la URL de la app como redirect.
3. Pegar en Streamlit Secrets:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REDIRECT_URI`
4. Avisar para **probar el flujo en vivo** y ajustar el redirect si hace falta.

> Ideal: cuenta de Google propia de Tentakl (no la personal), pero cualquiera
> que Jair controle permanentemente sirve para empezar.
