# Docs Agent · Handbook

> **Scope**: dueño único de `docs/`. Mantiene coherencia, identifica huecos de
> la base arquitectónica, decide qué borrar/refactorizar.
> Este agente **NO** modifica código en `src/`, NO toca tests, NO toca scripts.
> Solo escribe, refactoriza, borra documentación.

---

## Archivos bajo tu dominio

Todo bajo `docs/`:

| Path | Rol |
|---|---|
| [docs/README.md](../README.md) | Índice raíz |
| [docs/architecture/](../architecture/) | Diseño del sistema (SUPERCUT_ETL, STUDIO_API, DATA_MODEL, MLOPS_FLOW, ADRs) |
| [docs/testing/](../testing/) | Verificación (INTEGRATION_CHECKLIST, PENDING_TESTS) |
| [docs/operations/](../operations/) | INDEX_A_FILM, UPLOADS, TIKTOK_APP_REVIEW, RUNBOOK, SECURITY |
| [docs/agents/](../) | Handbooks por dominio + prompts paste-ready |

Además, por acuerdo con el owner, los Markdown fuera de `docs/`: `README.md`, `ROADMAP.md`,
`SETUP_CUENTAS.md`, `web/README.md`, `tests/README.md`, `scripts/README.md` y `youlikeit-web/*.md`.

Tu autoridad incluye:
- Crear nuevos handbooks de agente
- Refactorizar docs existentes (split/merge/rename)
- **Borrar docs obsoletos** previa justificación documentada en el PR
- Decidir cuándo un doc al root del repo debe moverse a `docs/`

## Archivos que NO puedes tocar

- Cualquier archivo bajo `src/`, `scripts/`, `tests/`, `data/`, `outputs/`
- `pyproject.toml`, `requirements*.txt`, GHA workflows
- `MANIFIESTO.md` (es propiedad del owner del canal — solo proponer cambios)

Si un cambio en docs requiere también cambio en código → abre sub-tarea para
el dominio dueño con la justificación de los docs.

---

## Responsabilidades exclusivas

1. **Audit periódico**: confirmar que toda referencia path/comando en docs
   sigue siendo válida después de movimientos de archivos.
2. **Identificar gaps arquitectónicos**: qué piezas críticas no están documentadas
   (ej. data model canónico, threat model, runbook on-call, ADRs).
3. **Mantener el catálogo de tareas** `AGENT_TASKS.md` sincronizado con la
   realidad del repo.
4. **Limpieza**: borrar docs duplicados / obsoletos con PR que justifique
   borrado y enlace a su reemplazo.
5. **Estilo y voz**: enforce convenciones (tablas Markdown, code fences con
   lenguaje, snippets con paths absolutos relativos al root).

---

## Convenciones de escritura

- **Idioma**: español neutro, técnico, directo. Sin emojis salvo ❌ ✅ ⚠️.
- **Code fences** con lenguaje declarado (` ```powershell `, ` ```python `).
- **Paths**: siempre desde root del repo, sin `./`. Ej: `scripts/signals/refresh_market_signals.py`.
- **Enlaces internos**: relativos, no absolutos. Ej: `[X](../testing/PENDING_TESTS.md)`.
- **Tablas**: para cualquier listado con ≥3 columnas o ≥4 filas.
- **DoD checklist**: usar `- [ ]` markdown task list.
- **Headers**: jerarquía respetada (no saltar de H1 a H3).
- **Líneas largas**: wrap a ~100 chars cuando sea narrativa, libre en tablas.

---

## Gaps arquitectónicos conocidos

Resueltos: DATA_MODEL, RUNBOOK, ADRs, SECURITY, CHANGELOG (2026-06-02) y, para el producto actual,
SUPERCUT_ETL, STUDIO_API revisado, INDEX_A_FILM, TIKTOK_APP_REVIEW, web/README y ADRs 0004–0008
(2026-11-04). Pendientes (priorizar por impacto):

| Gap | Por qué importa | DoD |
|---|---|---|
| Handbooks `SUPERCUT_AGENT`, `PUBLISH_AGENT`, `STUDIO_AGENT`, `WEB_AGENT` | Hoy esos dominios se apoyan en SUPERCUT_ETL / UPLOADS / STUDIO_API / web/README, sin DoD ni comando único | Estructura de § Crear nuevo handbook; listados en AGENT_TASKS |
| `docs/testing/INTEGRATION_CHECKLIST.md` del producto actual | El checklist describe el producto anterior | Checklist marcable: indexar → detectar → etiquetar → lección → render → revisión → publicar |
| Chequeo de deriva STUDIO_API ↔ OpenAPI | El contrato se escribe a mano; `/api/openapi.json` es la verdad del servidor | Script o test que compare rutas del contrato con el OpenAPI |
| `docs/architecture/CONTRIBUTING.md` | Cómo añadir un módulo, qué tests escribir, workflow git | Workflow paso a paso + ejemplos + check final |
| `docs/operations/COSTS.md` | Límites de los planes gratis (Groq, Gemini, YouTube, TikTok) y costo de Railway | Tabla por proveedor + qué hacer al llegar al límite |
| Métricas de calidad de momentos | precision@5 y F1 de planos no tienen doc de método | Sección en MOMENTS/MEDIA_AGENT con set, método y resultados |

### Gaps de QA detectados por el Analytics Agent (2026-06-02)

| Gap | Estado (2026-11-04) |
|---|---|
| Suite no corre en clone fresco sin `requirements-dev.txt` | Mitigado: README, tests/README y CI instalan `requirements-dev.txt` explícitamente |
| `scene_moments` ausente del esquema | ✅ Resuelto: `get_db` crea las tablas de dominio vía `_DOMAIN_SCHEMA_ENSURERS` (incluye `thematic_classifier.init_db`) |
| `run_signals.ps1 -Verbose` choca con `[CmdletBinding()]` | ✅ Resuelto: el switch ahora es `-Detailed` |

## Docs candidatos a borrar / mover

Auditar uno por uno con criterio "es la fuente de verdad para alguien hoy?".

La limpieza de DA01 (2026-06-02) ya se ejecutó. Quedan:

| Path | Estado | Decisión recomendada |
|---|---|---|
| `SETUP_CUENTAS.md` (root) | Citado por código (`doctor.py`, `ex34_oauth_manager.py`) | Mantener en root (ver DA08) |
| `docs/_audit_report.md` | Audit histórico del 2026-06-02 | Mover a `docs/_archive/` con `git mv` y actualizar `docs/README.md` y CHANGELOG (DA11) |
| `youlikeit-web/` (README, PASOS_DEPLOY, `public/`) | Reemplazado por `web/` en Railway; ya tiene banner | Decidir con el owner si se archiva o se borra la carpeta |
| `tiktok6SqmAImuROUyUPH61nJk6s8TjcqpaJXF.txt` (root) | Copia del token que ya sirve `web/app/verification/` | Verificar que nada lo use y borrar (owner) |
| `docs/architecture/PERSONAS.md`, `ESTRATEGIA_CPS_HOOKS.md`, `ANALYTICS_COVERAGE.md` | Producto anterior | Mantener con banner legacy; mover a `_archive/` si el producto anterior se retira |

---

## Definition of Done por tipo de tarea

### Auditar coherencia de docs (recurrente)

- [ ] `grep -rEi '(scripts/(test_|verify_signals_flow|refresh_market_signals|briefs_dashboard|score_hooks))' docs/` → solo paths con `scripts/<dominio>/`
- [ ] `grep -rEi 'tests/test_' docs/` → solo paths con `tests/<dominio>/`
- [ ] Todo enlace relativo resuelve (`find docs/ -name '*.md' -exec markdown-link-check {} \;` si está instalado, o manual)
- [ ] `docs/README.md` lista todos los archivos hijos directos
- [ ] Cada handbook en `agents/` está listado en `AGENT_TASKS.md § Mapa de dominios`

### Borrar un doc

- [ ] PR con título `docs: remove <path> (replaced by <new>)`
- [ ] Body explica por qué + dónde vive la info ahora
- [ ] `git grep` no encuentra referencias al doc borrado
- [ ] CHANGELOG.md (si existe) tiene entrada

### Crear nuevo handbook de agente

- [ ] Estructura: Scope, Archivos bajo tu dominio, Archivos que NO puedes tocar, Contratos de datos, DoD por tipo de tarea, Comando único de verificación, Métricas, Anti-patrones, Tareas abiertas
- [ ] Listado en `AGENT_TASKS.md`
- [ ] Si introduce nuevo dominio: handbook + carpeta `scripts/<dominio>/` + `tests/<dominio>/` aunque sean stubs
- [ ] Owner declarado

### Llenar un gap arquitectónico

- [ ] Archivo creado en `docs/architecture/` o `docs/operations/`
- [ ] Linkeado desde `docs/README.md`
- [ ] Mencionado en handbooks que lo usen como referencia

---

## Comando único de verificación

```powershell
# No hay tests pytest del docs agent; la verificación es manual + grep:
python -c @"
import re, pathlib
docs = pathlib.Path('docs')
issues = []
for md in docs.rglob('*.md'):
    text = md.read_text(encoding='utf-8')
    # Paths viejos
    for m in re.finditer(r'scripts/(verify_signals_flow|refresh_market_signals|briefs_dashboard|score_hooks)\.py', text):
        issues.append(f'{md}: legacy path -> {m.group(0)}')
    # tests viejos
    for m in re.finditer(r'tests/test_(brief_resolver|market_signals|signals_distiller|signals_validation|content_rotator|hook_scorer|integration_e2e)\.py', text):
        issues.append(f'{md}: legacy tests path -> {m.group(0)}')
for i in issues: print(i)
print(f'\nTotal issues: {len(issues)}')
"@
```

Exit 0 si no hay legacy paths; cualquier output = trabajo pendiente.

---

## Métricas que sigues

| Métrica | Baseline | Cómo medir |
|---|---|---|
| Docs sin enlaces rotos | 100% | grep recursivo de paths/enlaces |
| Handbooks por dominio | 1:1 con scripts/<dominio>/ y tests/<dominio>/ | `ls docs/agents/*_AGENT.md \| wc -l` vs `ls -d scripts/*/` |
| Gaps abiertos | ≤ 5 al rato | sección "Gaps arquitectónicos" arriba |
| Docs al root del repo | ≤ 3 (README + MANIFIESTO + ROADMAP/CHANGELOG) | `ls *.md \| wc -l` |
| Edad doc más vieja sin tocar | ≤ 90 días | `git log -1 --format=%cd <doc>` |

---

## Anti-patrones específicos

- ❌ Borrar un doc sin verificar `git grep` por referencias
- ❌ Crear doc nuevo sin linkearlo desde `docs/README.md`
- ❌ Duplicar info entre handbooks (single-source-of-truth)
- ❌ Documentar features hipotéticas no implementadas (genera deuda mental)
- ❌ Usar emoji decorativo (solo ❌ ✅ ⚠️ funcionales)
- ❌ Saltarse el CHANGELOG cuando exista
- ❌ Cambiar un handbook ajeno sin coordinarse con el owner
- ❌ Mover/renombrar un doc citado por código (`git grep` en `*.py`) sin abrir
  sub-tarea al dominio dueño — rompe la referencia silenciosamente (ej. `SETUP_CUENTAS.md` ↔ `ex34_oauth_manager.py`)
- ❌ Documentar el contrato de una API desde el plan y no desde el código: STUDIO_API se escribió antes
  de implementar y derivó (estados de publicación, códigos `409`/`422`/`503`). Revisar contra el código
  (o `/api/openapi.json`) después de cada merge.
- ❌ Copiar cifras de una corrida real sin fecha ni fuente: cada número medido lleva fecha y dónde se midió.

---

## Tareas abiertas conocidas

Tracking explícito acá (no duplicado en PENDING_TESTS porque eso es de QA):

- [x] **DA01**: Auditar y limpiar los docs al root — **ejecutado** (PR1).
  Borrados: ARCHITECTURE, DIAGRAMA_FLUJO_EDICION, FLUJO_PUBLICACION_CADA_3_DIAS,
  GUIA_EDICION_VIDEO, PLAN_FASE_2 + 4 artefactos TikTok en `docs/`. Movidos:
  ARCHITECTURE_PERSONAS→architecture/PERSONAS, COMANDOS_CLAUDE→_internal/,
  GUIA_APIS→operations/UPLOADS, METODOLOGIA_DAVINCI→_archive/. Root: 13→4
  (README, MANIFIESTO, ROADMAP, SETUP_CUENTAS — este último bloqueado, ver DA08).
- [x] **DA02**: `docs/architecture/DATA_MODEL.md` — ER mermaid + ~40 tablas con invariantes/owner/lectores.
- [x] **DA03**: `docs/operations/RUNBOOK.md` — top 5 incidents (síntoma→diagnóstico→fix→rollback).
- [x] **DA04**: `docs/architecture/DECISIONS/` — 3 ADRs MADR (algorítmico, SQLite, CATALOG fijo) + índice.
- [x] **DA05**: `docs/operations/SECURITY.md` — inventario de secrets + threat model.
- [x] **DA06**: `docs/CHANGELOG.md` — keep-a-changelog, sembrado con la última semana.
- [x] **DA07**: Auditar coherencia post-reorganización — comando de verificación
  retorna **0 issues** tras fix (6 paths legacy + 1 workflow name en `MLOPS_FLOW.md`,
  1 link placeholder en este handbook). 34 links OK / 0 rotos.
- [ ] **DA08**: mover `SETUP_CUENTAS.md` requiere actualizar las referencias en
  `src/cli/commands/doctor.py` y `scripts/legacy/exercises/ex34_oauth_manager.py` (acoplamiento
  doc↔código). Decisión actual: se queda en el root.
- [x] **DA09** (2026-11-04): docs al día con la rama `feat/supercut-media`: README, ROADMAP,
  SETUP_CUENTAS, SECURITY, UPLOADS, RUNBOOK (incidentes 6–15), CHANGELOG, MLOPS_FLOW, DATA_MODEL
  (tablas nuevas + `web.db`), STUDIO_API (comportamiento implementado), docs nuevos SUPERCUT_ETL,
  INDEX_A_FILM, TIKTOK_APP_REVIEW, `web/README.md`, ADRs 0004–0008, `tests/README.md`,
  `scripts/README.md`, banners en `youlikeit-web/*.md` y en los docs legacy.
- [ ] **DA10**: handbooks de supercut, publish, studio y web (ver § Gaps).
- [ ] **DA11**: `git mv docs/_audit_report.md docs/_archive/` (no se movió en DA09 por instrucción).
- [ ] **DA12**: reescribir `docs/testing/INTEGRATION_CHECKLIST.md` y `PENDING_TESTS.md` para el producto actual.
- [x] **DA13**: propuesta de actualización del MANIFIESTO escrita en
  `docs/_internal/MANIFIESTO_PROPUESTA.md`. Pendiente: decisión del owner.

---

*Owner: este agente. Última actualización: 2026-11-04.*
