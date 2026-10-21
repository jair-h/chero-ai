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

## 🗄️ Crear tablas del Gemelo en Supabase — PENDIENTE de Jair
SQL listo en `core/README_GEMELO.md` (tablas `gemelo_datos` y `gemelo_simulaciones`).
Sin ellas el Gemelo funciona en memoria pero no guarda datos ni historial.

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

## 🔌 Integraciones pendientes (del mapa VE/HACE)
- VER: Search Console, Meta/Google/TikTok Ads (gasto/ROAS), Clarity (parcial).
- HACER: lanzar/ajustar ads, editar web (Shopify/WordPress/VTEX), publicar
  (redes/WhatsApp/email).
- Autollenado del Gemelo desde las APIs de ads (que deje de pedir datos a mano).
