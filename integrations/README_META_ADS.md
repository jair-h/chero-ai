# Conexión de Meta Ads (Facebook/Instagram) — guía de configuración

Igual que Analytics: se hace **UNA sola vez** (tú, dueño de Tentakl). Después
cada usuario conecta sus ads con **un clic** y el Gemelo se autollena con el
gasto real (y el ROAS).

El código ya está listo en `integrations/meta_ads.py`. Falta la parte tuya:

## 1. Crear la app en Meta for Developers
1. Entra a <https://developers.facebook.com/> → **Mis apps → Crear app**.
2. Tipo: **Negocio** (Business).
3. En la app, agrega el producto **Marketing API**.
4. **Configuración → Básica:** copia el **App ID** y el **App Secret**.
5. **Facebook Login → Configuración:** agrega como **URI de redireccionamiento
   OAuth válido** la URL de tu app (ej. `https://tentakl.streamlit.app/`), igual
   que hiciste con Google. Debe coincidir EXACTO con `META_OAUTH_REDIRECT_URI`.
6. Permiso necesario: **`ads_read`**. En modo desarrollo funciona para ti y los
   testers que agregues; para abrirlo a todos, Meta pide **App Review** (igual
   que la verificación de Google).

## 2. Agregar los secrets en Streamlit Cloud
En **Manage app → Settings → Secrets**:

```toml
META_APP_ID = "xxxxxxxxxx"
META_APP_SECRET = "xxxxxxxxxxxxxxxxxxxx"
META_OAUTH_REDIRECT_URI = "https://TU-APP.streamlit.app/"
```

## 3. Cómo lo vive el usuario (cuando se conecte la UI)
1. Integraciones → **Conectar con Meta**.
2. Autoriza (solo lectura de ads) y elige su **cuenta publicitaria**.
3. El Gemelo trae su **gasto por mes** (y ROAS) → autollena la inversión en ads,
   que hoy se pone a mano.

## Notas técnicas
- Token de larga duración (~60 días); se renueva volviendo a conectar.
- Gasto por mes via `act_<id>/insights` con `time_increment=monthly`.
- ROAS de compra desde `purchase_roas` (0 si la cuenta no mide compras).
- Sin datos inventados: si la API falla, devuelve error claro.
