# Gemelo Digital — guía técnica

Agente nuevo que **simula ventas** con un motor matemático (Monte Carlo), no con
IA. La IA solo explica el resultado en palabras.

## Arquitectura (capas separadas)
- `core/gemelo.py` — **motor matemático puro** (sin IA, sin Streamlit): curva de
  respuesta por canal, elasticidad de precio, Monte Carlo (500 sims, ±15%),
  calibración con datos reales, benchmarks de arranque en frío y reparto óptimo.
- `core/gemelo_card.py` — tarjeta PNG compartible (PIL).
- `core/gemelo_ui.py` — UI Streamlit (4 tabs). Recibe `supabase`, `generar_texto`
  y `log` inyectados para no crear imports circulares con `app.py`.
- `app.py` — solo engancha: botón en el home + sección `gemelo` que llama a
  `_gemelo_ui.render(...)`.

Se accede desde el home → botón **"🔮 Gemelo Digital — simula tus ventas"**.

## Supabase — crear estas 2 tablas (una sola vez)
Ejecuta este SQL en Supabase → SQL Editor. Sin estas tablas el Gemelo igual
funciona (en memoria), pero NO guarda datos ni historial de precisión.

```sql
create table if not exists gemelo_datos (
    id          bigint generated always as identity primary key,
    user_id     text not null,
    fecha       text,
    gasto_meta   double precision default 0,
    gasto_google double precision default 0,
    gasto_tiktok double precision default 0,
    ventas      double precision default 0,
    precio      double precision default 0,
    costo       double precision default 0,
    created_at  timestamptz default now()
);
create index if not exists idx_gemelo_datos_user on gemelo_datos(user_id);

create table if not exists gemelo_simulaciones (
    id          bigint generated always as identity primary key,
    user_id     text not null,
    fecha_sim   text,
    parametros_json text,
    resultado_json  text,
    ventas_reales_posterior double precision,  -- se llena luego para medir precisión
    created_at  timestamptz default now()
);
create index if not exists idx_gemelo_sim_user on gemelo_simulaciones(user_id);
```

## Modelo (resumen honesto)
- Respuesta por canal: `ventas = max_ventas * (1 - e^(-gasto/b))` (satura).
- Precio: `factor = (precio/precio_ref)^(-elasticidad)`.
- Atribución: las ventas semanales (totales) se reparten entre canales en
  proporción al gasto. Es una **aproximación**, no causalidad real — y así se le
  avisa al usuario.
- Con <4 semanas usa **benchmarks por sector** (retail_moda, food_beverage,
  servicios, ecommerce_general) y lo muestra como tal.
- Siempre entrega un **rango** (p10–p90), nunca un número exacto solo.

## Tests
`python tests/test_tentakl.py` cubre el motor (curva, elasticidad, validación,
calibración, Monte Carlo determinista, reparto óptimo, precisión) y la tarjeta.
