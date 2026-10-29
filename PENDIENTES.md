# Pendientes de Tentakl

## ⏳ RECORDATORIO: correo hola@tentakl.ai es PROVISIONAL
Jair decide el correo real (puede ser gratis: reenvío del registrador o Zoho Mail
con dominio propio). Está en: política de privacidad, términos y el Libro de
Reclamaciones (fallback). Cambiarlo en esos 3 lugares cuando se decida.

## 📕 Libro de Reclamaciones (INDECOPI, Perú) — HECHO (código + tabla)
Formulario en la app (link en el pie → sección "reclamaciones"): tipo (Reclamo/
Queja), datos del consumidor, bien, detalle y pedido; genera un código y guarda
en Supabase. ✅ Tabla `reclamaciones` ya CREADA en Supabase (proyecto CHERO) con
RLS activado. No hay nada pendiente de Jair aquí.
Mejora futura: enviar copia por EMAIL al consumidor y a Tentakl (necesita
servicio de correo) y un panel admin para atender dentro de los 15 días hábiles.

## 🔐 Login "Entrar con Google" — HECHO (código, endurecido)
Botón en el sidebar que reusa la MISMA app OAuth de Google (scope básico
openid/email/profile). Da email VERIFICADO y lo deja logueado (persiste con ?u=).
PENDIENTE de Jair: en la pantalla de consentimiento OAuth de Google, poner el
estado de publicación en **"En producción"** (los scopes de login son NO
sensibles → NO requieren verificación de Google; solo analytics.readonly la
requiere). Con eso, cualquiera entra con Google.
✅ ENDURECIDO: el ?u= ya NO va en texto plano. Ahora es `email~firma` donde la
firma es HMAC-SHA256 (helpers `firmar_u`/`leer_u`). Si alguien pone
`?u=otro@correo` sin firma válida, se ignora → no puede suplantar a nadie.
OPCIONAL de Jair: agregar `SESSION_SECRET` en Streamlit Secrets (una frase
larga aleatoria) para una clave de firma dedicada; si no, usa como fallback el
secret de OAuth / la API key de Gemini (igual funciona).

## 🎣 Radiografía gratis de la web (gancho de entrada) — HECHO
En el inicio (modo simple, lo primero que ve el usuario): caja "🔍 Radiografía
gratis de tu web (10 segundos)". Pega su URL → score /100 por reglas + las 3
cosas más urgentes a corregir, al instante. GRATIS, sin IA, sin créditos, sin
configurar nada. Universal (cualquier negocio con web). Reusa integrations/seo.py.
Lleva a Power → Auditoría SEO para el detalle completo.

## 🎣 Gancho gratis (growth) — HECHO
Conectar tienda/Analytics ya NO requiere Pro: `FUNCION_PLAN_MIN["integraciones"] = "Free"`.
El anzuelo (conectar + Gemelo básico) es gratis para enganchar; se cobra la
PROFUNDIDAD (Autopiloto, historial+precisión del Gemelo, multi-cliente).

## 📲 Tarjeta compartible del Gemelo — HECHO
Rediseñada (insignia de veredicto en color, titular que se adapta honestamente),
mostrada al frente del resultado con botón de compartir. Branding tentakl.ai.

## 🎁 Referidos (invita y gana) — HECHO (con anti-abuso)
Cada usuario tiene su link `?ref=<token>` (en el sidebar: "Invita y gana"). Cuando
un amigo entra por el link y crea su cuenta, AMBOS ganan `CREDITOS_REFERIDO` (30)
créditos vía `creditos_extra`. Usa el email codificado en base64 como token.
✅ ANTI-ABUSO: tope de `REFERIDO_CAP` (20) referidos premiados por usuario; se
registra `referido_por` en el nuevo usuario y se cuenta en `referidos_dados` del
referente. No se puede auto-referir. Si el referente ya llegó al tope, no se
premia. Con esto, nadie puede fabricar créditos infinitos invitándose a sí mismo
o repitiendo cuentas sin control.
PENDIENTE de Jair: agregar 2 columnas a la tabla `usuarios` en Supabase para que
el tope y el registro persistan (si no existen, el código sigue funcionando pero
sin contar el tope):
```sql
alter table usuarios add column if not exists referidos_dados int default 0;
alter table usuarios add column if not exists referido_por text;
```

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

## 🔎 Search Console (SEO real, fase 1) — HECHO (código + tests)
`integrations/search_console.py` (reusa la MISMA app OAuth de Google que Analytics,
scope `webmasters.readonly`). Trae del sitio REAL del usuario: keywords por las que
lo encuentran, clics/impresiones/CTR/posición y páginas top. En Integraciones:
"🔎 Google Search Console (SEO)" → Conectar con Google → elegir sitio → ver reporte.
**Es GRATIS (no usa IA)**, coherente con el modelo de costo. Callback OAuth con
state `tentaklsc|<email>`, se guarda en `integraciones` (tipo `search_console`).
PENDIENTE de Jair (1 sola vez, en Google Cloud, misma cuenta que Analytics):
1. Habilitar **"Google Search Console API"** en el proyecto.
2. En la pantalla de consentimiento OAuth, **agregar el scope**
   `.../auth/webmasters.readonly` (es sensible → entra en la misma verificación
   que `analytics.readonly`; mientras tanto funciona con usuarios de prueba).
3. El sitio debe estar **verificado** en search.google.com/search-console con esa
   cuenta (si no, "no hay sitios verificados").

## 🔎 Auditoría on-page + ideas de keywords — HECHO (gratis, sin IA)
`integrations/seo.py`: (1) `auditar_onpage`/`fetch_y_auditar` → diagnóstico técnico
con score por REGLAS (title, meta, H1, H2, imágenes sin alt, viewport, canonical,
lang, HTTPS, cantidad de texto) + checklist de qué corregir ordenado por impacto;
(2) `sugerencias_google` → ideas de keywords del Autocompletar REAL de Google;
(3) `estacionalidad` → Google Trends con fallback claro si se bloquea (429).
En Power → "Auditoría SEO Completa": botones GRATIS "Diagnóstico rápido (URL)" e
"Ideas reales de Google" arriba; la auditoría narrativa por IA (3 créditos) queda
opcional abajo. Con tests (grupo [11]). Nada pendiente de Jair.

## 🔎 SEO/SEM de verdad (lo que falta) — roadmap
- **Fase 1 (gratis, alto valor):** ✅ Search Console + ✅ auditoría on-page +
  ✅ Autocomplete + ✅ Trends (con fallback). Opcional futuro: "People also ask".
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
