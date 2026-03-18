# Plan Fase 2: Lo que falta

## Resumen

12 nuevos ejercicios (ex24-ex35) organizados en 5 áreas + modificaciones
a 7 ejercicios existentes. Todo gratis, interpretable, modelos supervisados
e interpretables (Random Forest, DBSCAN), sin redes neuronales innecesarias.

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
| ex26 | `audience_demographics.py` | Demographics (edad, país, género) + DBSCAN clustering desde cero | Complejo | ex34 |
| ex35 | `data_export.py` | Exportar BD a CSV/JSON, backup, reporte "estado del canal" | Simple | db.py |

## Fase 2: Capa de Análisis

| # | Ejercicio | Qué hace | Complejidad | Depende de |
|---|-----------|----------|-------------|------------|
| ex25 | `algorithm_signals.py` | Random Forest desde cero: qué señales importan para el algoritmo (feature importance) | Complejo | ex24 |
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
Segmentos descubiertos por DBSCAN: nombre, core points, tamaño,
características, contenido preferido. Los outliers se marcan como
ruido (bots, viewers accidentales) y no contaminan los segmentos.

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

## Decisiones de diseño (estado del arte 2025-2026)

### Por qué htmx y no React/Vue
- Zero build step, zero node, zero npm
- El servidor retorna fragmentos HTML, htmx los intercambia
- 14KB totales. Sin framework JS
- Trade-off: las gráficas complejas necesitan Canvas vanilla (más código,
  pero cero dependencias)

### Por qué DBSCAN en vez de K-Means para segmentación

**Estado del arte:** Investigación de 2025 (Preprints.org, Towards AI)
demuestra que DBSCAN supera a K-Means en segmentación de audiencia cuando
los datos tienen ruido, outliers, y clusters de forma no-esférica.

| Criterio | K-Means | DBSCAN |
|----------|---------|--------|
| Clusters irregulares | No (solo esféricos) | Sí (cualquier forma) |
| Detecta outliers/bots | No (los fuerza a un cluster) | Sí (los marca ruido) |
| Definir # clusters | Sí (necesitas saber k) | No (lo descubre) |
| Pocos datos (<100) | Más estable | Necesita tuning |
| Interpretabilidad | Alta (centroides) | Media (densidades) |

**Para nuestra audiencia:** Los viewers NO forman clusters esféricos.
Habrá un grupo grande de casuales, grupos pequeños densos de superfans,
y ruido (bots, accidentales). DBSCAN detecta eso naturalmente.

**Implementación:** DBSCAN desde cero (~60 líneas Python) con auto-tuning
del parámetro eps usando el método del "knee" en la curva k-distance.
Sin sklearn. Fallback a agrupación simple si n < 20.

### Por qué Random Forest en vez de regresión lineal para señales

**Estado del arte:** Investigación en predicción de engagement en redes
sociales (Journal of Media Horizons 2025, Springer 2025) demuestra que
los modelos de ensemble (Random Forest, XGBoost) superan a la regresión
lineal porque el engagement es NO LINEAL:

- "Publicar a las 7pm + #villain" ≠ "publicar a las 7pm" + "#villain"
- Las interacciones entre features importan
- La regresión lineal no captura eso

| Modelo | Relaciones no-lineales | Interacciones | Overfitting (pocos datos) | Interpretable |
|--------|----------------------|---------------|--------------------------|---------------|
| Regresión lineal | No | No | Bajo | Total |
| **Random Forest** | **Sí** | **Sí** | **Bajo-Medio** | **Media-Alta** |
| XGBoost | Sí | Sí | Alto | Media |

**Decisión:** Random Forest como default (robusto con <200 datos).
XGBoost como opción cuando n > 500.

**Feature importance:** Random Forest da importancia por "impurity reduction"
(cuánto reduce la varianza cada feature al ser usada para splitear).
Esto responde directamente: "¿qué señal importa más para el algoritmo?"

**Implementación:** Random Forest desde cero (~150 líneas):
- Decision tree: recursive splitting con criterio de varianza
- Bagging: N árboles con bootstrap sampling
- Feature importance: promedio de impurity reduction por feature
- Sin sklearn. Si en el futuro se necesita más poder, agregar XGBoost
  como dependencia opcional.

### Capa de regresión lineal: NO se elimina

La regresión lineal se MANTIENE en ex23 para:
- **Tendencias temporales** (views over time) - aquí SÍ es lineal
- **Proyección de metas** - regresión simple funciona
- **Baseline** para comparar contra Random Forest (si RF no mejora
  significativamente vs lineal, usar lineal por Occam's razor)

### YouTube: Satisfaction-Weighted Discovery (2025)

**Cambio fundamental:** YouTube pasó de optimizar watch time absoluto
a optimizar SATISFACCIÓN. Un Short donde el viewer ve el 100% y da like
envía una señal MÁS FUERTE que un video largo con 40% de retención.

**Señales rankeadas por importancia (2025-2026):**

| Señal | Peso | Accesible via API? | Ejercicio |
|-------|------|--------------------|-----------|
| Retención % completa | Alto | Sí (Analytics API) | ex24 |
| Hook (primeros 8s) | Alto | Sí (retención a 3s y 8s) | ex24 |
| Session continuation | Alto | No directamente | -- |
| Re-watches | Medio | No directamente | -- |
| Engagement rate | Medio | Sí (Data API) | ex19 |
| CTR | Medio | Sí (Analytics API) | ex24 |
| Satisfacción post-view | Alto | No (encuestas internas) | -- |

**Benchmarks 2025:**
- Retención promedio YouTube: 23.7%
- Retención "buena": 50-60%
- Retención "algoritmo te empuja": 70%+
- +10 puntos de retención = +25% impresiones
- 55% de viewers se van en el primer minuto
- 8 segundos = ventana de decisión del viewer

**Implicación para el pipeline:**
El hook (ex18 narración intro) es la pieza MÁS crítica. ex22 (A/B testing)
debe priorizar testear variantes de hook:
- Hook con pregunta vs hook con afirmación
- Hook con texto en pantalla vs solo audio
- Hook de 2s vs hook de 4s

### YouTube Analytics API vs Data API v3
- Data API v3 (ya usada en ex19): views, likes, comments. NO da retención
- Analytics API (nueva): retención segundo a segundo, demographics, watch time
- Ambas gratis. Analytics tiene ~200 requests/día (más que suficiente)
- Requiere habilitar YouTube Analytics API en Google Cloud Console (una vez)

### Teoría estadística: varianza y pérdida de información

**Principio rector:** Siempre reportar cuánto NO sabemos.

Para cada modelo:
- **R²**: cuánta varianza explica el modelo (lo que sabemos)
- **1 - R²**: cuánta varianza NO explica (lo que no sabemos / ruido)
- **Information gain**: cuánta incertidumbre reduce cada feature
- **Residual analysis**: ¿los errores son aleatorios o tienen patrón?
  Si tienen patrón, hay una señal que no estamos capturando
- **Cross-validation**: ¿el modelo generaliza o memoriza? (k-fold con k=5)
- **Effect size (Cohen's d)**: ¿la diferencia es prácticamente significativa
  o solo estadísticamente significativa? p < 0.05 no basta si d < 0.2

Esto se implementa en ex23 y ex25. Cada reporte incluye:
1. Qué sabemos (métricas, R², importancia)
2. Qué NO sabemos (varianza no explicada, residuos)
3. Qué deberíamos investigar (features faltantes sugeridas)

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
| DBSCAN con eps mal calibrado | Auto-tuning con k-distance knee method. Fallback a agrupación simple si n < 20 |
| Random Forest overfitting con <30 datos | Limitar max_depth=5, min_samples_leaf=3. Fallback a regresión lineal si n < 30 |
| Features correlacionadas en el modelo | Calcular correlación entre features, eliminar una de cada par con r > 0.85 |
| Dashboard lento con muchos videos | Limitar a últimos 50, paginar |
| Curriculum planner sin datos de lecciones | Round-robin uniforme hasta acumular datos |
| Varianza no explicada alta (R² bajo) | Reportar explícitamente. Sugerir features adicionales que podrían ayudar |
| p-value significativo pero effect size pequeño | Reportar Cohen's d junto con p-value. No aplicar cambios si d < 0.2 |

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
