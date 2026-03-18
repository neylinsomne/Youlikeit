# Plan Fase 2: Lo que falta

## Resumen

12 nuevos ejercicios (ex24-ex35) organizados en 5 áreas + modificaciones
a 7 ejercicios existentes. Todo gratis, interpretable, sin redes neuronales.

---

## Fase 0: Infraestructura (hacer primero)

| # | Ejercicio | Qué hace | Complejidad |
|---|-----------|----------|-------------|
| ex34 | `oauth_manager.py` | Unificar OAuth de YouTube (upload + analytics) en un módulo compartido | Simple |
| -- | `db.py` modificaciones | Agregar tablas nuevas (retention, demographics, segments, tokens, curriculum) | Simple |

## Fase 1: Capa de Datos

| # | Ejercicio | Qué hace | Complejidad | Depende de |
|---|-----------|----------|-------------|------------|
| ex24 | `retention_curves.py` | YouTube Analytics API: retención segundo a segundo, detectar "cliffs" y "hooks" | Complejo | ex34 |
| ex26 | `audience_demographics.py` | Demographics (edad, país, género) + k-means clustering desde cero | Complejo | ex34 |
| ex35 | `data_export.py` | Exportar BD a CSV/JSON, backup, reporte "estado del canal" | Simple | db.py |

## Fase 2: Capa de Análisis

| # | Ejercicio | Qué hace | Complejidad | Depende de |
|---|-----------|----------|-------------|------------|
| ex25 | `algorithm_signals.py` | Regresión multivariada desde cero: qué señales importan para el algoritmo | Complejo | ex24 |
| ex27 | `geo_optimization.py` | Qué contenido funciona en cada país (ANOVA por geografía) | Medio | ex26 |
| ex31 | `lesson_taxonomy.py` | Clasificar frases por tipo de aprendizaje (pensamiento crítico, empatía, ética...) | Medio | db.py |

## Fase 3: Análisis Cruzado

| # | Ejercicio | Qué hace | Complejidad | Depende de |
|---|-----------|----------|-------------|------------|
| ex32 | `lesson_performance.py` | Cruzar tipos de lección con retención/engagement | Medio | ex31, ex24 |
| ex33 | `curriculum_planner.py` | Planificar calendario de contenido con diversidad pedagógica | Medio | ex32 |

## Fase 4: Dashboard y Frontend

| # | Ejercicio | Qué hace | Complejidad | Depende de |
|---|-----------|----------|-------------|------------|
| ex29 | `api_layer.py` | API REST unificada con auth por token, roles, paginación | Medio | db.py |
| ex28 | `dashboard_server.py` | Dashboard analítico completo (htmx + Canvas JS, sin React) | Complejo | ex29 |
| ex30 | `frontend.py` | Frontend separado, responsive, multi-página con htmx | Medio | ex29, ex28 |

---

## Grafo de dependencias

```
ex34 (oauth) ──┬── ex24 (retención) ──── ex25 (señales del algoritmo)
               │                    │
               └── ex26 (demographics) ── ex27 (geo optimization)
                                    │
db.py (schema) ────────────────────┤
               │                    │
               └── ex31 (lecciones) ── ex32 (perf. lecciones) ── ex33 (curriculum)
                                    │
               ex35 (export) ──────┤
                                    │
                              ex29 (API) ── ex28 (dashboard) ── ex30 (frontend)
```

---

## Tablas nuevas en la BD

### retention_curves
Retención segundo a segundo por video. Cada fila = un segundo del video
con el % de audiencia que sigue viendo y qué quote/categoría estaba
en pantalla en ese momento.

### retention_events
Eventos detectados en la curva: "cliff" (caída > 5%), "plateau" (estable),
"recovery" (subida), "hook_pass" (sobrevivió los primeros 3s).

### audience_demographics
Snapshots de demographics de YouTube Analytics: edad, país, género,
% de viewers, watch time.

### audience_segments
Segmentos descubiertos por k-means: nombre, centroide, tamaño,
características, contenido preferido.

### user_tokens
Tokens de autenticación para la API REST. Simple token-based auth
con `secrets.token_hex()`.

### curriculum_plan
Plan de contenido con diversidad pedagógica: query sugerida, tipo de
aprendizaje objetivo, categoría, emoción, estado (planned/in_progress/completed).

### Columnas nuevas en quotes
- `learning_type`: critical_thinking, emotional_intelligence, ethics,
  creativity, resilience, self_awareness, empathy, decision_making
- `life_lesson`: texto libre con la lección extraída
- `curriculum_area`: character, relationships, society, self, conflict

---

## Dependencias nuevas

Ninguna nueva. Solo descomentar las que ya están en requirements.txt:

```
google-api-python-client>=2.100.0
google-auth-oauthlib>=1.1.0
google-auth-httplib2>=0.2.0
```

El frontend usa htmx desde CDN (14KB, un `<script>` tag). Las gráficas
son Canvas API vanilla. Zero build step.

---

## Decisiones de diseño

### Por qué htmx y no React/Vue
- Zero build step, zero node, zero npm
- El servidor retorna fragmentos HTML, htmx los intercambia
- 14KB totales. Sin framework JS
- Trade-off: las gráficas complejas necesitan Canvas vanilla (más código,
  pero cero dependencias)

### Por qué k-means desde cero
- ~40 líneas de Python con stdlib + math
- Completamente interpretable
- Para 3-6 clusters con unos cientos de puntos, converge en milisegundos

### Por qué regresión multivariada desde cero
- Ecuaciones normales: `β = (X^T X)^{-1} X^T y`
- Inversión de matrices con Gauss-Jordan (~30 líneas)
- Con <15 features y >30 datos, no hay overfitting
- Completamente interpretable: sabes exactamente cuánto aporta cada señal

### YouTube Analytics API vs Data API v3
- Data API v3 (ya usada en ex19): views, likes, comments. NO da retención
- Analytics API (nueva): retención segundo a segundo, demographics, watch time
- Ambas gratis. Analytics tiene ~200 requests/día (más que suficiente)
- Requiere habilitar YouTube Analytics API en Google Cloud Console (una vez)

---

## Modificaciones a ejercicios existentes

| Ejercicio | Qué cambiar |
|-----------|-------------|
| **ex12** | Extraer OAuth a ex34 compartido |
| **ex19** | Agregar Analytics API para retención, watch time, subscribers |
| **ex21** | Consumir lesson performance (ex32) y geo data (ex27) |
| **ex17** | Integrar geographic overlay y curriculum plan |
| **main.py** | Agregar ex24-ex35, nuevos CLI args |
| **run-content-flow.ps1** | Agregar ex24, ex26, ex25, ex31, ex32 al flujo |
| **docker-compose.yml** | Puerto para dashboard (8001) |

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| YouTube Analytics no da retención para videos con pocas views | Manejar gracefully, usar solo Data API como fallback |
| K-means inestable con pocos datos | Validar tamaño mínimo de clusters, fallback a agrupación simple |
| Regresión con features correlacionadas | Detectar determinante ~0, eliminar features colineales |
| Dashboard lento con muchos videos | Limitar a últimos 50, paginar |
| Curriculum planner sin datos de lecciones | Round-robin uniforme hasta acumular datos |

---

## Orden de implementación recomendado

1. **ex34 + db.py** (1 sesión) - infraestructura
2. **ex24 + ex26** en paralelo (2 sesiones) - recolección de datos
3. **ex31** (1 sesión) - taxonomía de lecciones
4. **ex25 + ex27** en paralelo (2 sesiones) - análisis
5. **ex32 + ex33** secuencial (1 sesión) - lecciones + curriculum
6. **ex35** (1 sesión) - exportación
7. **ex29** (1 sesión) - API REST
8. **ex28 + ex30** (2 sesiones) - dashboard + frontend

Total: ~11 sesiones de trabajo.
