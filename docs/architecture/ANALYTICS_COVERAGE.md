# Cobertura analítica — qué teníamos, qué faltaba, qué suple Plausible

> **Legacy (2026-11-04).** Plausible se diseñó para el sitio estático `youlikeit.vara-alta.lat`
> (`youlikeit-web/`). El sitio vivo ahora es `web/` en Railway
> (<https://youlikeit-web-production.up.railway.app>) y **no está instrumentado** con Plausible.
> Instrumentarlo sería una tarea nueva (agregar el script en `web/app/templates/base.html` y
> declararlo en la política de privacidad).

> Owner: [Analytics Agent](../agents/ANALYTICS_AGENT.md) · 2026-06-02
> Relacionado: [MLOPS_FLOW.md](MLOPS_FLOW.md) (caja Sculley "Monitoring")

Este documento responde la pregunta: **¿qué analíticas ya teníamos, qué hueco
había, y cómo el dominio `analytics` (Plausible) lo complementa para cerrar el
loop?** Y define el modelo de **analítica conjunta** (nuestra + Plausible).

---

## 1. El embudo de contenido y dónde medíamos

El ciclo de vida de un short tiene 4 etapas. Antes de Plausible medíamos 3 de
las 4 — y nos faltaba justo la **parte alta del embudo** (el sitio público).

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │  DEMANDA            CALIDAD           DISTRIBUCIÓN        RESULTADO    │
  │  (qué hacer)        (pre-publish)     (publicar)         (medir)      │
  ├─────────────────────────────────────────────────────────────────────┤
  │                                                                       │
  │  Externa:           hook_scores  →    YouTube / TikTok  →  analytics  │
  │  market_signals                       (upload)             retention  │
  │  persona_briefs                                            demographics│
  │       │                                                               │
  │       │   ⟵──── faltaba ────⟶                                        │
  │       ▼                                                               │
  │  1ª PARTE (web):  ✅ NUEVO con Plausible                              │
  │  plausible_pageviews / plausible_events                               │
  │  (visitantes del sitio, CTAs, persona_click)                          │
  │                                                                       │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Lo que YA teníamos (antes de Plausible)

| Superficie | Tabla(s) | Escribe | Qué mide | Etapa |
|---|---|---|---|---|
| Demanda externa | `market_signals`, `persona_briefs`, `scraper_health` | `market_signals.py`, `signals_distiller.py` | Qué consume el mercado (Steam, Reddit, RSS…) → briefs por persona | Demanda |
| Calidad de hook | `hook_scores` | `hook_scorer.py` | Energía de audio + CPS + acento + LLM, gate pre-publish | Calidad |
| Performance plataforma | `analytics` | `ex19_analytics.py` | YT/TT: views, likes, retention_avg, retention_3s, CTR, engagement_rate | Resultado |
| Curvas de retención | `retention_curves`, `retention_events` | `ex24_retention_curves.py` | Retención segundo-a-segundo + cliffs/plateaus | Resultado |
| Demografía | `audience_demographics`, `audience_segments` | `ex26_audience_demographics.py` | Edad/género/país + clusters DBSCAN | Resultado |
| Benchmark | `competitor_videos` | `ex20_competitor_analysis.py` | Qué hace la competencia y por qué funciona | Resultado |
| Conocimiento | `knowledge_base`, `goals`, `learning_log` | ex21–ex33 | Insights acumulados + metas + auto-ajuste | Meta |

**Reporting que ya existía:**
- `scripts/signals/briefs_dashboard.py` — salud de scrapers + briefs por persona.
- `scripts/legacy/exercises/ex28_dashboard_server.py` — dashboard web (KPIs, retención, demografía).
- `scripts/legacy/exercises/ex35_data_export.py` — export CSV/JSON + `channel_report.txt`.
- `scripts/legacy/exercises/ex19_analytics.py` — reporte de texto top-performers.

---

## 3. Lo que FALTABA (el hueco)

Todo lo de arriba mide **demanda externa** (qué dice el mundo) y **resultado en
plataforma** (cómo le fue a un video YA publicado en YT/TT). **Cero visibilidad
de la parte alta del embudo: nuestro propio sitio público.**

Concretamente, antes de Plausible NO sabíamos:

1. **Quién visita `youlikeit.vara-alta.lat`** — visitantes, páginas, duración.
2. **Qué CTAs convierten** — quién hace click en "Preview dashboard", contacto, etc.
3. **Demanda de primera parte** (`own_engagement`) — qué le interesa a NUESTRA
   audiencia, medido en casa, no inferido de Reddit/Steam.
4. **Top-of-funnel → plataforma** — si el interés en el sitio anticipa el
   rendimiento del contenido publicado.

En el mapa Sculley, la caja **"Monitoring" estaba 🔴** justo por esto: medíamos
el resultado en plataforma (ajeno, post-hoc) pero no teníamos telemetría propia
de la entrada del embudo.

---

## 4. Lo que SUPLE Plausible (el complemento)

| Hueco | Cómo lo llena Plausible |
|---|---|
| Tráfico web propio | `plausible_pageviews` (visitantes, pageviews, bounce, duración por página) |
| Conversión de CTAs | `plausible_events` (`cta_click`, `persona_click`) vía `assets/analytics.js` |
| Demanda 1ª parte | `internal_signals.py` → `Signal(domain='internal', source_type='own_engagement')` |
| Monitoring 🔴→🟡 | self-host privacy-first (sin PII), dashboard CLI propio |

Plausible **no reemplaza** nada: **complementa** la entrada del embudo que no
teníamos. La demanda externa (market_signals) sigue diciendo "qué se habla
afuera"; Plausible añade "qué mira y clickea NUESTRA gente".

---

## 5. Analítica conjunta (nuestra + Plausible)

La vista **conjunta** une las 4 capas en un solo embudo por persona:

| Capa | Fuente | Pregunta que responde |
|---|---|---|
| Demanda externa | `market_signals`, `persona_briefs` | ¿De qué hablar? |
| **Demanda 1ª parte (web)** | `plausible_pageviews/events` | ¿Qué mira/clickea mi audiencia? **(NUEVO)** |
| Calidad | `hook_scores` | ¿El hook pasa el gate? |
| Distribución | `analytics` | ¿Cómo le fue en YT/TT? |

**Cómo verla:**

```powershell
# Vista CONJUNTA (nuestra + Plausible) — las 4 capas
python scripts/analytics/unified_dashboard.py
python scripts/analytics/unified_dashboard.py --json

# Vista SOLO PLAUSIBLE — únicamente el embudo web de 1ª parte
python scripts/analytics/unified_dashboard.py --source plausible

# (el dashboard original sigue existiendo para Plausible puro)
python scripts/analytics/analytics_dashboard.py
```

La agregación vive en `src/apps/analytics/unified_analytics.py` (funciones puras,
testeadas). Lee de todas las tablas en **solo-lectura**; no escribe ninguna
(salvo las `plausible_*` que son del dominio analytics).

### Per-persona rollup

Para cada persona (`deep_mind`, `pop_oracle`, `latam`) la vista conjunta cruza:
- **interés web** (pageviews de sus páginas en `PERSONA_PAGES` + `persona_click`),
- **backlog de briefs** (no consumidos en `persona_briefs`),
- **calidad** (pass-rate y score medio en `hook_scores`).

Así se ve, de un vistazo, qué persona tiene demanda propia + briefs listos +
hooks que pasan — es decir, dónde conviene producir a continuación.

---

## 6. Gaps que quedan (futuro)

Heredados del inventario, NO resueltos por Plausible (requieren otros agentes):

- **brief → short → performance**: trazar qué brief produjo qué short y cómo le
  fue (falta columna `persona`/`brief_id` en `shorts`/`analytics`). → Production.
- **cross-platform unificado**: YT + TT en filas separadas, sin KPI normalizado.
- **hook_score → retención real**: el pass/fail no se realimenta con el resultado.
- **persona_click → performance**: cuando existan páginas por-persona, cerrar el
  cruce web-interés ↔ resultado-plataforma a nivel persona.

Estos están registrados en [DOCS_AGENT.md § Gaps](../agents/DOCS_AGENT.md).
