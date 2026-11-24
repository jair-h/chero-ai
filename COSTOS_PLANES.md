# Tentakul — Costos reales por plan y estrategia de precios

> Objetivo: saber **cuánto me cuesta** cada plan en IA, el **margen**, y cómo
> está armado para que la mayoría elija el **plan Pro ($39)**.

## Precios de los modelos (nov 2026 — verificar en las webs oficiales)
- **Texto — Gemini 2.5 Flash:** $0.30 / 1M tokens entrada · **$2.50 / 1M salida**
- **Texto — Gemini 2.5 Flash-Lite:** $0.10 / 1M · $0.40 / 1M (para tareas ligeras)
- **Imagen — gpt-image-2 (1024×1024):** low **$0.006** · medium **$0.053** · high **$0.211**

## Cuánto cuesta 1 crédito de texto
Un crédito = 1 llamada de texto. Estimado típico ~2,000 tokens entrada + ~2,000 salida
en Gemini 2.5 Flash:
- Entrada: 2,000 × $0.30/1M = $0.0006
- Salida:  2,000 × $2.50/1M = $0.0050
- **≈ $0.006 – $0.008 por crédito** (menos si usa Flash-Lite; más si la respuesta es larga).

Se usa **$0.007/crédito** como estimado medio abajo.

## Límites por plan (fuente: planes_config / fallback)
| Plan | Precio | Créditos/mes | Imágenes/mes | Calidad img |
|---|---|---|---|---|
| Free | $0 | 20 | 2 | low |
| Starter | $19 | 200 | 5 | medium |
| **Pro** | **$39** | **500** | **20** | **high** |
| Agency | $79 | 1,500 | 100 | high |

(La imagen cuesta **5 créditos** + 1 del límite de imágenes. El **límite de imágenes**
es lo que de verdad protege el margen, porque una imagen HIGH cuesta $0.211 real.)

## Costo e margen por plan (PEOR CASO: usa TODO el mes)
| Plan | Imágenes ($) | Texto restante ($) | **Costo IA máx/mes** | Precio | **Margen bruto** |
|---|---|---|---|---|---|
| Free | 2×low = $0.01 | 20×$0.007 = $0.14 | **~$0.15** | $0 | — (costo de adquisición) |
| Starter | 5×med = $0.27 | 175×$0.007 = $1.23 | **~$1.50** | $19 | **~$17.5 (92%)** |
| **Pro** | 20×high = $4.22 | 400×$0.007 = $2.80 | **~$7.00** | $39 | **~$32 (82%)** |
| Agency | 100×high = $21.10 | 1000×$0.007 = $7.00 | **~$28.10** | $79 | **~$51 (64%)** |

> Esto es el **peor caso** (cliente que exprime todo, maximizando imágenes HD).
> El uso típico es mucho menor → el margen real suele ser aún mayor.

### Restar la comisión de la pasarela (Mercado Pago ~3.5–4% + IGV)
- Starter: −~$0.8 → **neto ~$16.7**
- Pro: −~$1.6 → **neto ~$30.4**
- Agency: −~$3.1 → **neto ~$47.8**

**Conclusión:** márgenes sanos en los 3 planes, incluso en el peor caso. El mayor
costo es la **imagen HIGH** en Pro/Agency; el **límite mensual de imágenes** lo contiene.
(Idea: si Agency se vuelve muy intensivo en imágenes, revisar si 100 HD es mucho.)

## Por qué la mayoría debería caer en **Pro ($39)** — y cómo reforzarlo
La escalera de beneficios ya empuja al medio:
- **Free** — ver datos + Gemelo básico. Solo para probar (gancho).
- **Starter $19** — contenido con IA + Gemelo, 200 créditos. **SIN Autopiloto, SIN Gemelo
  completo (historial/precisión), SIN multi-cliente.** Es "el de prueba".
- **Pro $39** — **+ Autopiloto + Gemelo COMPLETO + 500 créditos + 20 imágenes HD.** Es
  "el completo para un negocio real". → marcar **MÁS POPULAR / Recomendado**.
- **Agency $79** — **+ multi-cliente** (varios negocios), 1,500 créditos, 100 imágenes.
  Sirve de **ancla alta**: hace que $39 se vea razonable.

Tácticas (psicología de precios):
1. **Starter limitado a propósito** (sin Autopiloto/Gemelo completo) → el que va en serio salta a Pro.
2. **Pro = "Más popular"** destacado visualmente (ya en el landing).
3. **Agency como ancla** → $39 parece la opción sensata.
4. **Valor por crédito:** Pro 500/$39 = **$0.078/créd** vs Starter 200/$19 = **$0.095/créd**.
   Pro rinde más por crédito **y** desbloquea todo. Comunicarlo.
5. El **recomendador de plan** ya sesga al medio (Pro) a propósito.

## Notas
- El código usa precios $19/$39/$79; el landing muestra $20/$40/$80 (redondeado). Decidir uno.
- En Mercado Pago Perú se cobra en **soles**: $39 ≈ S/145 aprox (según tipo de cambio). Para
  internacional (USD) se usará Paddle más adelante.
