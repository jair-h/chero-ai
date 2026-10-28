# Pendientes de Tentakl

## 🎣 Gancho gratis (growth) — HECHO
Conectar tienda/Analytics ya NO requiere Pro: `FUNCION_PLAN_MIN["integraciones"] = "Free"`.
El anzuelo (conectar + Gemelo básico) es gratis para enganchar; se cobra la
PROFUNDIDAD (Autopiloto, historial+precisión del Gemelo, multi-cliente).

## 📲 Tarjeta compartible del Gemelo — HECHO
Rediseñada (insignia de veredicto en color, titular que se adapta honestamente),
mostrada al frente del resultado con botón de compartir. Branding tentakl.ai.

## 🎁 Referidos (invita y gana) — HECHO (sin SQL nuevo)
Cada usuario tiene su link `?ref=<token>` (en el sidebar: "Invita y gana"). Cuando
un amigo entra por el link y crea su cuenta, AMBOS ganan `CREDITOS_REFERIDO` (30)
créditos vía `creditos_extra`. Usa el email codificado en base64 como token.
Limitación conocida (MVP): no hay anti-abuso fuerte (no registra referido_por);
el bono se da una vez por alta. Mejoras futuras: registrar referido_por, tope de
referidos, y requerir que el nuevo haga una acción antes de premiar.

## 🔁 Growth — siguientes
Alerta semanal de retención por EMAIL/WhatsApp (la parte in-app ya está: aviso
de próxima campaña con cuenta regresiva en el Gemelo). El envío necesita un
servicio de correo (Resend/SendGrid) + disparador semanal — fase aparte.

## 🔵 Meta Ads — CÓDIGO LISTO, falta app de Jair + wiring UI
`integrations/meta_ads.py` (OAuth + gasto/ROAS por mes) con tests. Pasos de
configuración en `integrations/README_META_ADS.md`. PENDIENTE de Jair: crear la
app en Meta for Developers (App ID/Secret + redirect + permiso ads_read) y
pegar META_APP_ID / META_APP_SECRET / META_OAUTH_REDIRECT_URI en Streamlit.
PENDIENTE de código (cuando haya app): botón "Conectar con Meta" en
Integraciones + autollenar la inversión del Gemelo desde el gasto real.


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

## 🗄️ Crear tablas del Gemelo en Supabase — PENDIENTE de Jair
SQL listo en `core/README_GEMELO.md` (tablas `gemelo_datos` y `gemelo_simulaciones`).
Sin ellas el Gemelo funciona en memoria pero no guarda datos ni historial.
> El SQL ya incluye la columna `campana` (modo campaña). Si creaste la tabla
> antes, corre el `alter table ... add column campana` que está en el README.

## ✅ Modo campaña del Gemelo — HECHO (para todos los usuarios)
El Gemelo ya proyecta meses de campaña (Cyber, Black, Navidad, Día de la Madre...).
Cada negocio marca sus semanas de campaña en "📥 Mis datos" (casilla Campaña) y el
motor aprende SU multiplicador real (pico vs. mes normal). Si aún no hay campañas
marcadas, usa un benchmark del sector y lo avisa. Nuevo tipo de decisión
"🔥 ¿Cuánto venderé en campaña?" con slider de intensidad. Todo con rango (p10–p90).

## 🐛 Fallas a corregir (de la auditoría de funciones) — por hacer
1. **Scores inventados** en Auditoría Maestra (viralidad/demanda 0-100 sin fuente):
   etiquetarlos como "estimación de IA" o quitarlos (no presentarlos como dato duro).
2. **"Regenerar Plan Semanal"**: cobra el crédito ANTES de generar (si falla, cobró
   igual). Mover `consumir(1)` a después de generar, como el resto.
3. **Trends (pytrends)**: se bloquea seguido en la nube → Radar/Planificador quedan
   vacíos. Falta fallback claro y aviso al usuario.
4. **Scraping (403)**: Inteligencia Competitiva y Auditoría SEO fallan en webs que
   bloquean bots. Falta manejo y mensaje claro.
5. **Redundancia**: Simulador de Campaña se solapa con el Gemelo → fusionar o quitar.
6. **SEO keywords**: aclarar que son sugerencias de IA, no volumen real (hasta que
   se conecte data real — ver abajo).

## 🔎 SEO/SEM de verdad (hacerlo que funcione muy bien) — roadmap
Hoy el SEO genera keywords "del modelo" (sin datos reales). Para que sea neto SEO/SEM:
- **Fase 1 (gratis, alto valor):** Google Search Console (OAuth, keywords/posición
  reales del propio sitio) + auditoría on-page (scrape: title/meta/H1/estructura) +
  Google Trends (estacionalidad) + Google Autocomplete/"People also ask".
- **Fase 2 (pago barato):** DataForSEO (~$0.05/consulta) para volumen de búsqueda y
  CPC reales → investigación de keywords de verdad.
- **Fase 3:** Google Ads Keyword Planner (volumen/CPC/competencia) + armar campañas
  SEM (ad groups, match types, negativas, RSA) y luego publicarlas por API.

## 💲 Precios por país — cobro real (Stripe) — PENDIENTE de Jair
La app YA muestra precios por región (LatAm base; USA/España en USD más alto:
Starter $29 / Pro $59 / Agency $119). Falta crear en **Stripe** (o tu pasarela)
los mismos price points por región para que el COBRO coincida con lo mostrado.
Ajustar `PRECIOS_USA` y `_PAISES_ALTO_INGRESO` en app.py si cambias la tabla.

## 🔌 Integraciones pendientes (del mapa VE/HACE)
- VER: Search Console, Meta/Google/TikTok Ads (gasto/ROAS), Clarity (parcial).
- HACER: lanzar/ajustar ads, editar web (Shopify/WordPress/VTEX), publicar
  (redes/WhatsApp/email).

## ✅ Autollenado del Gemelo (ventas) — HECHO (WooCommerce)
El Gemelo ya trae las VENTAS reales por mes desde la tienda conectada
(`fetch_woocommerce_sales_by_month`), con el botón "📥 Traer mis ventas de mi
tienda" en Mis datos. Suma pedidos completed/processing, ignora cancelados.
PENDIENTE para completar el autollenado:
- **Inversión en ads** (aún a mano): falta conectar Meta/Google/TikTok Ads
  para traer gasto/ROAS y autollenar esa columna.
- **Shopify/otras**: hoy el autollenado de ventas es solo WooCommerce; falta
  el equivalente con la Orders API de Shopify y otras plataformas.
