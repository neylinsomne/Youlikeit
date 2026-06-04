# Agent Tasks · Catálogo central de delegación

> **Propósito**: este documento es el **punto de entrada único** para cualquier
> agente (humano o IA) que recoge una tarea en YouLikeIt. Cada dominio tiene
> alcance acotado, criterios de aceptación medibles y un único comando para
> verificar.
>
> **Metodología**: Domain-Driven Folders + Definition-of-Done + Single-Command
> Audit por dominio. Inspirado en Trunk-Based Development + Conway's Law: la
> estructura del repo refleja qué agente puede modificar qué.

---

## Mapa de dominios

| Dominio       | Owner agent            | Scope                                 | Handbook |
|---------------|------------------------|---------------------------------------|----------|
| **signals**   | Signals Agent          | Ingesta de fuentes → briefs por persona | [SIGNALS_AGENT.md](SIGNALS_AGENT.md) |
| **production**| Production Agent       | Rotator + render + EDL                | [PRODUCTION_AGENT.md](PRODUCTION_AGENT.md) |
| **scoring**   | Scoring Agent          | Hook scorer + A/B variants            | [SCORING_AGENT.md](SCORING_AGENT.md) |
| **qa**        | QA / Testing Agent     | pytest + invariantes + smoke E2E      | [QA_AGENT.md](QA_AGENT.md) |
| **docs**      | Docs Agent             | Dueño de `docs/` + gaps arquitectónicos | [DOCS_AGENT.md](DOCS_AGENT.md) |
| **analytics** | Analytics Agent        | Plausible self-host + bridge a signals  | [ANALYTICS_AGENT.md](ANALYTICS_AGENT.md) |
| **uploads**   | Uploads Agent          | YouTube + TikTok API integration      | _(pendiente — handler diferido)_ |
| **setup**     | Setup Agent            | OAuth, voces, descargas de assets     | _(pendiente)_ |

## Prompts paste-ready

Prompts auto-contenidos para delegar a una sesión fresca de agente
(Claude/GPT/etc.). Cada uno incluye rol, docs a leer, tarea, restricciones y DoD.

| Prompt | Para qué dominio | Cuándo usar |
|---|---|---|
| [prompts/DOCS_AUDIT_PROMPT.md](prompts/DOCS_AUDIT_PROMPT.md) | docs | Auditar coherencia, limpiar docs sueltos, llenar gaps arquitectónicos |
| [prompts/PLAUSIBLE_INTEGRATION_PROMPT.md](prompts/PLAUSIBLE_INTEGRATION_PROMPT.md) | analytics | Integrar Plausible self-host + bridge a signals |

---

## Reglas de delegación

### Antes de pedirle algo a un agente

1. **Identificar el dominio** revisando este catálogo. Si el cambio cruza
   2+ dominios, **subdividir** o usar el QA Agent como coordinador.
2. **Leer el handbook del dominio**. Define qué puede tocar, qué no,
   y cuál es el comando de verificación.
3. **Definir Definition-of-Done** explícita (ver plantilla abajo).
4. **Asignar el comando de verificación** del dominio como gate.

### Plantilla mínima de tarea a un agente

```markdown
## Tarea: <título corto>

**Dominio:** signals | production | scoring | qa | uploads | setup
**Handbook:** docs/agents/<DOMAIN>_AGENT.md

**Contexto (qué pasaba antes):**
- ...

**Cambio solicitado:**
- ...

**Out of scope (NO tocar):**
- ...

**Definition of Done:**
- [ ] Cambio implementado en archivos listados en el handbook
- [ ] Cobertura local del dominio ≥ baseline del handbook
- [ ] `scripts/testing/run_<domain>.ps1` → exit 0
- [ ] Si toca DB schema: migración idempotente añadida
- [ ] Si toca un alias/CATALOG: `validate_alias_map(CATALOG)` sin huérfanos
- [ ] Documentación actualizada (handbook + changelog si aplica)

**Comando de verificación (final):**
```
.\scripts\testing\run_<domain>.ps1
```
```

---

## Catálogo de tareas frecuentes

Tareas pre-canonizadas que un agente puede recoger sin contexto adicional.
Cada una con dominio, archivos afectados y DoD.

### 🟢 Tier 1 · Tareas seguras (≤ 1h, bajo riesgo)

| # | Tarea | Dominio | DoD |
|---|-------|---------|-----|
| T01 | Añadir 1 fuente RSS nueva a `market_signals.SOURCES` | signals | test del parser pasa; `refresh --sources <nueva>` ingiere |
| T02 | Añadir 5 aliases a `ALIAS_MAP` | signals | `validate_alias_map` 0 huérfanos; `alias_map_stats.coverage_pct` ≥ 80 |
| T03 | Añadir 1 serie al `CATALOG` | production | tests `TestCatalog` pasan; ≥1 alias añadido en simultáneo |
| T04 | Bumpear un threshold de `signals_validation` | qa | env var sugerida en handbook; PENDING_TESTS actualizado |
| T05 | Añadir 1 keyword a `PERSONA_ALIGNMENT.keywords_boost` | signals | distill regenera; `briefs_dashboard` muestra el efecto |
| T06 | Borrar 1 doc obsoleto al root del repo | docs | `git grep` 0 referencias; PR con justificación; CHANGELOG entry |
| T07 | Mover 1 doc al root hacia `docs/<categoría>/` | docs | enlaces rotos fijados; entry en `docs/README.md` |

### 🟡 Tier 2 · Tareas medianas (1-4h, riesgo medio)

| # | Tarea | Dominio | DoD |
|---|-------|---------|-----|
| T20 | Implementar nuevo invariante en `signals_validation` | qa | test añadido; `run_all_checks` lo incluye; doc thresholds actualizada |
| T21 | Añadir un dominio nuevo (e.g., `podcasts`) | signals | enum actualizado; ≥3 fuentes; aliases por persona; tests `TestDomainEnum` |
| T22 | Añadir layer 4 (embeddings) al `brief_resolver` | signals | sentence-transformers detrás de feature flag; benchmark vs layer 2 |
| T23 | Streamlit dashboard mínimo | qa | reemplaza `briefs_dashboard.py --validate`; auth básica |
| T24 | Calibrar `MIN_HOOK_SCORE` contra retention | scoring | notebook + valor justificado; `block_on_fail=True` activado |
| T25 | Self-host Plausible (Fase 1) | analytics | docker-compose + Tunnel route; `/api/health` 200 |
| T26 | Bridge Plausible → market_signals (Fase 4) | analytics | tabla + `internal_signals.py`; coordinación enum con signals |
| T27 | ✅ `docs/architecture/DATA_MODEL.md` | docs | HECHO (2026-06-02): ER mermaid + ~40 tablas |
| T28 | ✅ `docs/operations/RUNBOOK.md` | docs | HECHO (2026-06-02): top 5 incidents |

### 🔴 Tier 3 · Tareas estructurales (≥ 4h, alto riesgo)

| # | Tarea | Dominio | DoD |
|---|-------|---------|-----|
| T40 | Migrar a Postgres + pgvector | qa | docker-compose + Flyway + dual-driver en `db.py`; tests pasan en ambos |
| T41 | Bandit Thompson sobre `PERSONA_ALIGNMENT` | scoring | módulo bandit; updater nightly GHA; rollback feature-flag |
| T42 | Reescribir orquestador con Celery + Redis | production | tasks idempotentes; reintento por stage; UI mínima de queue |
| T43 | Benchmark vs AutoClip (5 videos/persona) | qa | reporte cuantitativo; decisión documentada |
| T44 | Plausible full integration (Fases 1-6) | analytics | DoD completa de `prompts/PLAUSIBLE_INTEGRATION_PROMPT.md` |
| T45 | ✅ `docs/architecture/DECISIONS/` con ADRs MADR | docs | HECHO (2026-06-02): 3 ADRs (algorítmico, SQLite, CATALOG fijo) |

---

## Anti-patrones (qué un agente NO debe hacer)

- ❌ Tocar archivos fuera del scope de su handbook sin abrir una sub-tarea
  para el dominio dueño.
- ❌ Saltarse el comando de verificación porque "es un cambio chico".
- ❌ Cambiar el contrato de datos (`SCHEMA` en `db.py`) sin migración Flyway
  o pasos de migración en el handbook QA.
- ❌ Eliminar tests sin reemplazarlos por algo equivalente o mejor.
- ❌ Push de cambios al CATALOG sin actualizar ALIAS_MAP simultáneamente.
- ❌ Introducir nueva dep en `requirements.txt` sin justificar en el PR.

---

## Onboarding rápido (5 minutos)

Cuando un agente entra fresco:

```powershell
# 1. Sanity check de la estructura
ls docs/architecture docs/testing docs/agents

# 2. Verificar que el flujo info corre
.\scripts\testing\run_tests.ps1 -Mode quick

# 3. Leer el handbook del dominio que te asignaron
code docs/agents/<DOMAIN>_AGENT.md

# 4. Smoke E2E contra DB real (si tu dominio toca data)
python scripts/signals/verify_signals_flow.py --cleanup
```

Si los 4 pasos pasan → el repo está en estado coherente y puedes empezar.
Si alguno falla → primera tarea es **diagnóstico**, no implementación.

---

## Referencias cruzadas

- [docs/architecture/MLOPS_FLOW.md](../architecture/MLOPS_FLOW.md) — mapa Sculley completo del sistema
- [docs/testing/INTEGRATION_CHECKLIST.md](../testing/INTEGRATION_CHECKLIST.md) — checklist marcable por sección
- [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) — items diferidos con DoD individual

---

*Mantenedor: Owner del repo. Última actualización: 2026-06-02.*
