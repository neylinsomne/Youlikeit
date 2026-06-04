# Docs Audit Report · 2026-06-02

> Auditoría del Docs Agent. Dominio: `docs/`. Entregable de la tarea
> `docs/agents/prompts/DOCS_AUDIT_PROMPT.md`. Las correcciones de coherencia
> (Parte A) ya se aplicaron; los borrados/moves (Parte B) y docs nuevos
> (Parte C) están **propuestos** y esperan visto bueno del owner antes de
> ejecutarse en PRs.

## Resumen ejecutivo

- **17 docs auditados**: 13 `.md` al root del repo + 4 artefactos legacy en `docs/`.
- **2 correcciones de coherencia aplicadas** (Parte A): 6 paths legacy y 1 nombre
  de workflow corregidos en `MLOPS_FLOW.md`; 1 link placeholder arreglado en `DOCS_AGENT.md`.
- **Borrados propuestos: 6** (`ARCHITECTURE.md`, `DIAGRAMA_FLUJO_EDICION.md`,
  `FLUJO_PUBLICACION_CADA_3_DIAS.md`, `GUIA_EDICION_VIDEO.md`, `PLAN_FASE_2.md`,
  + los 4 artefactos TikTok en `docs/`).
- **Moves propuestos: 4** (`ARCHITECTURE_PERSONAS.md`, `COMANDOS_CLAUDE.md`,
  `GUIA_APIS_YOUTUBE_TIKTOK.md`, `METODOLOGIA_EDICION_DAVINCI.md`, `SETUP_CUENTAS.md`).
- **5 gaps arquitectónicos** con outline (DA02–DA06).
- **Meta de root**: pasar de **13 → 3** `.md` al root (`README.md`, `MANIFIESTO.md`, `ROADMAP.md`).
- **Bloqueo conocido**: mover `SETUP_CUENTAS.md` requiere actualizar una
  referencia en `scripts/legacy/exercises/ex34_oauth_manager.py` (fuera de scope docs → sub-tarea a setup/uploads).

---

## Parte A — Coherencia interna

| Check | Resultado |
|---|---|
| Cero paths legacy a `scripts/test_*` / verify-flow sin prefijo de dominio | ✅ 0 (tras fix) |
| Cero enlaces relativos `.md` rotos | ✅ 34 OK / 0 rotos (tras fix) |
| Todos los hijos directos de `docs/` listados en `docs/README.md` | ⚠️ Ver nota |
| Handbooks `docs/agents/*_AGENT.md` listados en `AGENT_TASKS.md § Mapa de dominios` | ✅ 6/6 |

### Correcciones aplicadas

1. **`docs/architecture/MLOPS_FLOW.md`** — 6 ocurrencias del runner de refresh
   sin prefijo de dominio → corregidas al path canónico `scripts/signals/…`
   (confirmado en `INTEGRATION_CHECKLIST.md`).
2. **`docs/architecture/MLOPS_FLOW.md`** — `.github/workflows/refresh_signals.yml`
   → `refresh-signals.yml` (el archivo real usa guion, no guion bajo).
3. **`docs/agents/DOCS_AGENT.md`** — el ejemplo de enlace en § Convenciones
   apuntaba a un `Y.md` placeholder inexistente; ahora apunta a un archivo real
   (`PENDING_TESTS.md`), para que el link-checker retorne 0.

### Notas / pendientes de Parte A

- **Hijos directos de `docs/` no listados en `docs/README.md`**: `callback/`,
  `privacy.html`, `terms.html`, `tiktok6Sqm…JXF.txt`. Son exactamente los 4
  artefactos legacy TikTok marcados para borrado en Parte B. Una vez borrados,
  el árbol de `README.md` queda completo y el check pasa. **No** se recomienda
  añadirlos al índice; se recomienda borrarlos.
- El falso positivo del comando de verificación en `DOCS_AUDIT_PROMPT.md`
  (verify-flow sin prefijo) es intencional: el prompt **nombra** ese
  path como ejemplo de lo que hay que evitar. No es un issue.

---

## Parte B — Auditoría de docs al root del repo

> Metadata: `wc -l` + `git log -1 --format=%cs` + `git grep` de referencias entrantes.
> Las "referencias entrantes" excluyen el self-link.

### ARCHITECTURE.md

- **Tamaño:** 405 líneas
- **Última modificación:** 2026-03-22
- **Referencias entrantes:** 0
- **Solapamiento con:** `docs/architecture/MLOPS_FLOW.md` + `ARCHITECTURE_PERSONAS.md` (~70%, estimado)
- **Decisión propuesta:** DELETE
- **Justificación:** Describe el pipeline mono-canal viejo ("enseñar lecciones
  de vida, 100% automatizado"), anterior al sistema multi-persona. Reemplazado
  por `MLOPS_FLOW.md`. Cero referencias entrantes.
- **Acción concreta:** `git rm ARCHITECTURE.md` + añadir redirect en `README.md` raíz → `docs/architecture/MLOPS_FLOW.md`.

### ARCHITECTURE_PERSONAS.md

- **Tamaño:** 503 líneas
- **Última modificación:** 2026-03-28
- **Referencias entrantes:** 0
- **Solapamiento con:** `MLOPS_FLOW.md` (~40%); el resto (diseño de personas + knowledge graph) es único
- **Decisión propuesta:** MOVE_TO(`docs/architecture/PERSONAS.md`) + trim del solapamiento
- **Justificación:** Es la única descripción narrativa del diseño multi-persona
  y el knowledge graph. Pertenece a `docs/architecture/`, no al root. Antes de
  mover, recortar las secciones que duplican `MLOPS_FLOW.md`.
- **Acción concreta:** `git mv ARCHITECTURE_PERSONAS.md docs/architecture/PERSONAS.md`; editar para quitar duplicados; linkear desde `docs/README.md`. ⚠️ Verificar contra `src/apps/content/personas.py` (fuente de verdad de los datos de persona) antes de afirmar comportamiento.

### COMANDOS_CLAUDE.md

- **Tamaño:** 249 líneas
- **Última modificación:** 2026-04-06
- **Referencias entrantes:** 0
- **Solapamiento con:** ninguno (es inventario de comandos/skills/agents de Claude Code del owner)
- **Decisión propuesta:** MOVE_TO(`docs/_internal/COMANDOS_CLAUDE.md`)
- **Justificación:** Scratchpad personal del entorno del owner, no documenta el
  producto. No merece estar al root pero no se borra sin permiso (puede ser útil al owner).
- **Acción concreta:** `git mv COMANDOS_CLAUDE.md docs/_internal/COMANDOS_CLAUDE.md`. (Alternativa: DELETE si el owner confirma que vive en `~/.claude/`.)

### DIAGRAMA_FLUJO_EDICION.md

- **Tamaño:** 23 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 (solo `README.md` raíz)
- **Solapamiento con:** `MLOPS_FLOW.md § flujo end-to-end` (reemplazado)
- **Decisión propuesta:** DELETE
- **Justificación:** Mermaid del pipeline de ejercicios viejo (ex04→ex09), no
  refleja el flujo signals→briefs→render actual.
- **Acción concreta:** `git rm DIAGRAMA_FLUJO_EDICION.md` + quitar el link en `README.md` raíz.

### FLUJO_PUBLICACION_CADA_3_DIAS.md

- **Tamaño:** 54 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 (solo `README.md` raíz)
- **Solapamiento con:** `content-rotation.yml` (GHA) + `content_rotator.py` (la prosa describe lo que hoy es código/YAML)
- **Decisión propuesta:** DELETE
- **Justificación:** El ciclo de 3 días hoy vive en el workflow y el rotator. La
  prosa no aporta sobre el YAML versionado.
- **Acción concreta:** `git rm FLUJO_PUBLICACION_CADA_3_DIAS.md` + quitar link en `README.md`. (Si el owner quiere conservar la narrativa: MERGE_INTO `MLOPS_FLOW.md § Operación`.)

### GUIA_APIS_YOUTUBE_TIKTOK.md

- **Tamaño:** 80 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 (solo `README.md` raíz)
- **Solapamiento con:** ninguno vivo (uploads está en pausa)
- **Decisión propuesta:** MOVE_TO(`docs/operations/UPLOADS.md`)
- **Justificación:** Contenido load-bearing para el dominio uploads (handler
  diferido). Pertenece a operations cuando se reactive la integración.
- **Acción concreta:** `git mv GUIA_APIS_YOUTUBE_TIKTOK.md docs/operations/UPLOADS.md`; linkear desde `docs/README.md`; mencionar en el futuro `UPLOADS_AGENT.md`.

### GUIA_EDICION_VIDEO.md

- **Tamaño:** 79 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 (solo `README.md` raíz)
- **Solapamiento con:** `METODOLOGIA_EDICION_DAVINCI.md` (~60%) — ambos describen edición manual ex09→pieza final
- **Decisión propuesta:** DELETE
- **Justificación:** Describe edición manual del pipeline de ejercicios viejo. El
  render hoy es algorítmico (FFmpeg NVENC en `video_director.py`), sin paso manual.
- **Acción concreta:** `git rm GUIA_EDICION_VIDEO.md` + quitar link en `README.md`.

### METODOLOGIA_EDICION_DAVINCI.md

- **Tamaño:** 92 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 (solo `README.md` raíz)
- **Solapamiento con:** `GUIA_EDICION_VIDEO.md`
- **Decisión propuesta:** MOVE_TO(`docs/_archive/METODOLOGIA_EDICION_DAVINCI.md`)
- **Justificación:** El pipeline ya **no usa DaVinci** (render automatizado). Es
  historia, no fuente de verdad. Archivar en vez de borrar por si se retoma edición manual de piezas largas.
- **Acción concreta:** `git mv METODOLOGIA_EDICION_DAVINCI.md docs/_archive/METODOLOGIA_EDICION_DAVINCI.md`. (Alternativa: DELETE si el owner confirma que DaVinci no vuelve.)

### PLAN_FASE_2.md

- **Tamaño:** 290 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 0
- **Solapamiento con:** `ROADMAP.md` + `MLOPS_FLOW.md § Roadmap` (plan ex24–ex35 ya ejecutado/superado)
- **Decisión propuesta:** DELETE
- **Justificación:** Plan de una fase ya ejecutada. El estado vivo está en
  `ROADMAP.md` y el roadmap de `MLOPS_FLOW.md`. Cero referencias entrantes.
- **Acción concreta:** `git rm PLAN_FASE_2.md`. (Si tiene valor histórico: MOVE_TO `docs/_archive/`.)

### ROADMAP.md

- **Tamaño:** 196 líneas
- **Última modificación:** 2026-03-26
- **Referencias entrantes:** 0
- **Solapamiento con:** `MLOPS_FLOW.md § Roadmap MLOps` (~50%)
- **Decisión propuesta:** KEEP (al root) + reconciliar
- **Justificación:** La métrica del handbook permite `ROADMAP.md` al root. Pero
  hay dos roadmaps; designar **uno** como fuente de verdad. Recomiendo: `ROADMAP.md`
  = roadmap de producto de alto nivel; `MLOPS_FLOW.md § Roadmap` = roadmap técnico-MLOps; añadir cross-link entre ambos para que no diverjan.
- **Acción concreta:** Editar `ROADMAP.md` para añadir link a `MLOPS_FLOW.md § Roadmap MLOps` y aclarar la división de responsabilidad. Sin git mv.

### SETUP_CUENTAS.md

- **Tamaño:** 122 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 — **`scripts/legacy/exercises/ex34_oauth_manager.py`** (código, no docs)
- **Solapamiento con:** ninguno (setup de OAuth/cuentas vivo)
- **Decisión propuesta:** MOVE_TO(`docs/operations/SETUP_ACCOUNTS.md`) — **bloqueado**
- **Justificación:** Doc vivo y útil; pertenece a operations. Pero está
  referenciado por código fuera de mi scope. Mover sin actualizar el código
  rompería esa referencia.
- **Acción concreta:** Abrir **sub-tarea a setup/uploads** para actualizar la
  ruta en `ex34_oauth_manager.py`; recién entonces `git mv`. Mientras tanto: KEEP al root y linkear desde `docs/README.md`.

### MANIFIESTO.md

- **Tamaño:** 84 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 1 — `src/integrations/llm_provider.py`
- **Solapamiento con:** ninguno
- **Decisión propuesta:** KEEP (al root)
- **Justificación:** Propiedad del owner del canal (restricción dura: no tocar).
  Referenciado por código. Se queda al root.
- **Acción concreta:** Solo añadir link desde `docs/README.md`. No editar contenido.

### README.md (root)

- **Tamaño:** 151 líneas
- **Última modificación:** 2026-03-18
- **Referencias entrantes:** 0 (es el punto de entrada)
- **Solapamiento con:** `docs/README.md` (índice) — distintos propósitos
- **Decisión propuesta:** KEEP + reescribir
- **Justificación:** El título actual ("YouTube Automatizacion - Ejercicios") y
  los links apuntan a los docs legacy que se van a borrar. Tras PR1 quedará con
  links rotos si no se reescribe.
- **Acción concreta:** Reescribir como entry-point del sistema multi-persona;
  linkear a `docs/README.md`, `MANIFIESTO.md`, `ROADMAP.md`; eliminar links a docs borrados.

### Artefactos legacy en `docs/` (no son root pero entran en la limpieza)

| Path | Decisión | Justificación |
|---|---|---|
| `docs/privacy.html` | DELETE | Duplica la fuente viva en `youlikeit-web/public/` |
| `docs/terms.html` | DELETE | Idem |
| `docs/callback/index.html` | DELETE | Duplica `youlikeit-web/public/callback/` |
| `docs/tiktok6Sqm…JXF.txt` | ⚠️ VERIFICAR con owner | Verification file de TikTok; si aún se requiere → mover a `youlikeit-web/public/`; si no → DELETE |

---

## Parte C — Gaps arquitectónicos (outlines)

### DA02 · `docs/architecture/DATA_MODEL.md`

- **Título / ubicación:** Data Model · YouLikeIt → `docs/architecture/DATA_MODEL.md`
- **Secciones (outline):**
  1. Propósito y alcance (SQLite WAL, fuente de verdad = `src/core/db.py` SCHEMA)
  2. ER diagram en mermaid (las **36 tablas** de `db.py`)
  3. Tablas core del flujo de información: `market_signals`, `persona_briefs`,
     `scraper_health`, `topic_clusters`, `hook_scores`, `ab_tests`
  4. Tablas de contenido/render: `shorts`, `short_clips`, `clip_library`, `quotes`, `subtitles`, `movies`
  5. Tablas de analítica: `analytics`, `retention_curves`, `retention_events`, `audience_*`, `competitor_videos`
  6. Tablas de control/ETL: `etl_runs`, `pipeline_runs`, `audit_log`, `model_snapshots`, `url_cache`, `user_tokens`, `users`
  7. Por tabla: columnas, invariantes (UNIQUE/FK), owner del schema, lectores declarados, ciclo de vida
  8. Invariantes globales (UTC, namespaces `verify_`, dedupe)
- **Load-bearing para:** signals, production, scoring, qa, analytics (todos leen DB).
- **Owner consultable:** QA Agent (dueño del contrato `SCHEMA`) + Signals Agent (tablas de ingesta).
- **Esfuerzo:** **L** (36 tablas; el ER diagram y el inventario por tabla son densos).

### DA03 · `docs/operations/RUNBOOK.md`

- **Título / ubicación:** Runbook On-Call · YouLikeIt → `docs/operations/RUNBOOK.md`
- **Secciones (outline):**
  1. Cómo usar este runbook (severidad, escalado)
  2. Incident 1 — Scraper caído > 24h (síntoma: `scraper_health.fail_rate` > 0.3)
  3. Incident 2 — Brief sin match (crece `unresolved_briefs_queue`)
  4. Incident 3 — Render falla (FFmpeg/NVENC error en `produce_for_series.py`)
  5. Incident 4 — GHA cron rojo (`refresh-signals.yml` / `content-rotation.yml`)
  6. Incident 5 — Hook score crash / gate bloqueando (`hook_scorer.py`)
  7. Plantilla por incident: síntoma → diagnóstico → fix → rollback
  8. Contactos / escalado
- **Load-bearing para:** operations, qa, signals, production.
- **Owner consultable:** owner del repo (operación) + cada Agent dueño del módulo del incident.
- **Esfuerzo:** **M**.

### DA04 · `docs/architecture/DECISIONS/` (ADRs, formato MADR)

- **Título / ubicación:** carpeta `docs/architecture/DECISIONS/` con `0001-*.md`, `0002-*.md`, `0003-*.md`
- **Secciones por ADR (MADR):** Context and Problem · Decision Drivers ·
  Considered Options · Decision Outcome · Consequences (good/bad) · More Information
- **ADRs iniciales (retroactivas):**
  - `0001-why-algorithmic-not-llm.md` — fuente: `MLOPS_FLOW.md § Decisión 1`
  - `0002-why-sqlite-not-postgres.md` — fuente: `MLOPS_FLOW.md § Decisión 2`
  - `0003-why-fixed-catalog.md` — fuente: `content_rotator.CATALOG` + `MLOPS_FLOW.md § Decisión 4`
- **Load-bearing para:** todos (explica el "por qué" no obvio del sistema).
- **Owner consultable:** owner del repo (decisiones ya tomadas; documentar, no decidir).
- **Esfuerzo:** **S** (las decisiones ya están escritas en prosa en `MLOPS_FLOW.md`; es reformatear a MADR).

### DA05 · `docs/operations/SECURITY.md`

- **Título / ubicación:** Security & Secrets · YouLikeIt → `docs/operations/SECURITY.md`
- **Secciones (outline):**
  1. Inventario de secrets (`GEMINI_API_KEY`, `TRAKT_CLIENT_ID`, OAuth YT/TT, `.env`, `tokens/`)
  2. Dónde vive cada secret (GHA secrets vs `.env` local vs `tokens/`)
  3. Política de rotación
  4. Threat model: amenaza → mitigación (token leak, scraper IP-ban, supply chain de deps)
  5. Qué NO commitear (`.gitignore` audit de `tokens/`, `.env`)
- **Load-bearing para:** setup, uploads, operations.
- **Owner consultable:** owner del repo + Setup Agent.
- **Esfuerzo:** **M**.

### DA06 · `docs/CHANGELOG.md`

- **Título / ubicación:** Changelog (keep-a-changelog) → `docs/CHANGELOG.md`
- **Secciones (outline):**
  1. Header keep-a-changelog + semver-ish por sprint
  2. `[Unreleased]`
  3. Sembrar última semana: signals layer, hook scorer, organización de `docs/`, reorg de `scripts/<dominio>/`
  4. Categorías: Added / Changed / Deprecated / Removed / Fixed
- **Load-bearing para:** docs, qa (trazabilidad entre sprints).
- **Owner consultable:** Docs Agent (este agente) lo mantiene.
- **Esfuerzo:** **S**.

---

## Parte D — Plan de ejecución

> Orden: borrados → moves → docs nuevos. Cada item espera aprobación del owner
> (los borrados son destructivos; algunos moves cruzan a código).

```markdown
1. [DA01] Aplicar fixes de coherencia (Parte A) · costo S · valor alto · ✅ HECHO
2. [DA01] PR1-cleanup: borrar 6 docs (ARCHITECTURE, DIAGRAMA, FLUJO_PUB,
   GUIA_EDICION, PLAN_FASE_2, + 3 artefactos TikTok html/callback) · costo S ·
   valor alto · bloquea: README raíz queda con links rotos → reescribir en el mismo PR
3. [DA01] PR1-cleanup: moves no-conflictivos (ARCHITECTURE_PERSONAS→docs/architecture/,
   COMANDOS_CLAUDE→docs/_internal/, GUIA_APIS→docs/operations/UPLOADS.md,
   METODOLOGIA_DAVINCI→docs/_archive/) · costo M · valor medio
4. [DA01] Decidir con owner: tiktok…txt (¿TikTok aún lo exige?) y SETUP_CUENTAS
   (requiere sub-tarea para tocar ex34_oauth_manager.py) · costo S · valor medio ·
   bloquea: move de SETUP_CUENTAS
5. [DA01] Actualizar README raíz + docs/README.md + AGENT_TASKS tras los borrados/moves;
   git grep 0 referencias colgantes · costo S · valor alto
6. [DA04] PR4-ADRs: 3 ADRs retroactivas (reformateo de MLOPS_FLOW § Decisiones) · costo S · valor alto
7. [DA06] PR5-CHANGELOG: sembrar con la última semana · costo S · valor medio
8. [DA03] PR3-RUNBOOK: top 5 incidents · costo M · valor alto
9. [DA02] PR2-DATA_MODEL: ER diagram + 36 tablas con invariantes · costo L · valor alto
10. [DA05] SECURITY.md: inventario de secrets + threat model · costo M · valor alto
```

### Recomendación de secuencia de PRs (vs. DoD del prompt)

| PR | Contenido | Costo | Estado |
|---|---|---|---|
| PR1 | cleanup (borrados + moves + README + índices) | M | ⏸ espera aprobación |
| PR4 | 3 ADRs MADR (más barato, desbloquea entendimiento) | S | ⏸ |
| PR5 | CHANGELOG sembrado | S | ⏸ |
| PR3 | RUNBOOK top 5 | M | ⏸ |
| PR2 | DATA_MODEL (el más caro, dejar de último) | L | ⏸ |

---

## Decisiones que requieren al owner antes de ejecutar

1. **Borrados destructivos** (6 docs): confirmar que no hay valor histórico que
   prefiera archivar en vez de borrar.
2. **`docs/tiktok…txt`**: ¿TikTok sigue exigiendo el verification file? Si sí, va
   a `youlikeit-web/public/`, no se borra.
3. **`SETUP_CUENTAS.md`**: el move toca una referencia en `src/` → necesita
   sub-tarea fuera del dominio docs.
4. **`MANIFIESTO.md`**: no se toca el contenido; solo se propone linkearlo.

---

*Generado por el Docs Agent · 2026-06-02. Parte A ejecutada; Partes B/C/D propuestas.*
