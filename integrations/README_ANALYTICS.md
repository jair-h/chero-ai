# Conexión de Google Analytics (OAuth) — guía de configuración

Esto se hace **UNA sola vez** (tú, como dueño de Tentakl). Después, cada
usuario conecta su Analytics con **un clic**, sin crear nada.

## 1. Crear la app OAuth en Google Cloud

1. Entra a <https://console.cloud.google.com>.
2. Crea un proyecto (o usa uno existente).
3. **APIs y servicios → Biblioteca** → habilita:
   - **Google Analytics Data API**
   - **Google Analytics Admin API**
4. **APIs y servicios → Pantalla de consentimiento OAuth**:
   - Tipo: *External*.
   - Agrega el scope: `.../auth/analytics.readonly`.
   - Mientras esté en modo *Testing*, agrega los correos de prueba.
   - Para abrirlo a todo el público, envía la app a *verificación* de Google
     (solo-lectura de Analytics suele aprobarse sin problema).
5. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente OAuth**:
   - Tipo: *Aplicación web*.
   - **URI de redirección autorizado:** la URL pública de tu app en
     Streamlit Cloud, por ejemplo `https://tentakl.streamlit.app/`
     (debe coincidir EXACTO con `GOOGLE_OAUTH_REDIRECT_URI`).
   - Copia el **Client ID** y el **Client Secret**.

## 2. Agregar los secrets en Streamlit Cloud

En **Manage app → Settings → Secrets**, agrega:

```toml
GOOGLE_OAUTH_CLIENT_ID = "xxxxxxxx.apps.googleusercontent.com"
GOOGLE_OAUTH_CLIENT_SECRET = "xxxxxxxx"
GOOGLE_OAUTH_REDIRECT_URI = "https://TU-APP.streamlit.app/"
```

## 3. Cómo lo vive el usuario

1. Gestión → Integraciones → **Conectar con Google**.
2. Inicia sesión con Google y autoriza (solo lectura).
3. Vuelve a Tentakl, pulsa **Actualizar**, y elige su propiedad GA4.
4. Listo: **Analizar mis métricas** trae datos reales (tráfico, fuentes,
   páginas top, dispositivos, países y tendencia diaria) — sin datos demo.

## Notas técnicas

- El `access_token` de Supabase (tabla `integraciones`) ahora guarda un
  **bundle JSON** `{access_token, refresh_token, expiry}`. Se renueva solo.
- El GA4 Data API usa el **ID numérico** de propiedad (ej. `123456789`),
  **no** el measurement ID `G-XXXX`. La selección de propiedad lo resuelve.
- Conexiones viejas con API Key se detectan como `api_key_legacy` y piden
  reconectar con Google (la API Key no sirve para el Data API).
