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
| [docs/architecture/](../architecture/) | Diseño del sistema (MLOPS_FLOW, ESTRATEGIA_CPS_HOOKS) |
| [docs/testing/](../testing/) | Verificación (INTEGRATION_CHECKLIST, PENDING_TESTS) |
| [docs/operations/](../operations/) | Runbook + on-call (vacío hoy) |
| [docs/agents/](../) | Handbooks por dominio + prompts paste-ready |

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

Pendientes de documentar (priorizar por impacto):

| Gap | Por qué importa | DoD |
|---|---|---|
| `docs/architecture/DATA_MODEL.md` | Schema canónico SQLite; hoy disperso entre db.py y handbooks | ER diagram (mermaid) + cada tabla con invariantes + owner |
| `docs/operations/RUNBOOK.md` | Qué hacer cuando algo se rompe en cron / scraper / render | 5 incidents top + step-by-step + rollback |
| `docs/architecture/DECISIONS/` (ADRs) | Por qué algorítmico vs LLM; por qué SQLite; por qué CATALOG fijo | 1 ADR por decisión non-obvious; formato ADR-MADR |
| `docs/operations/SECURITY.md` | Manejo de secrets, OAuth tokens, threat model | Lista de secrets + dónde viven + rotación + amenaza→mitigación |
| `docs/architecture/CONTRIBUTING.md` | Cómo añadir un módulo, qué tests escribir, workflow git | Workflow paso a paso + ejemplos + check final |
| `docs/CHANGELOG.md` | Trazabilidad de cambios entre sprints | Keep-a-changelog format desde el sprint actual |
| `docs/operations/COSTS.md` | Costo $ por persona/mes (LLM, scraping, deploy) | Tabla por proveedor + budget alerts |

### Gaps detectados por el Analytics Agent (2026-06-02)

| Gap | Por qué importa | DoD sugerido |
|---|---|---|
| Suite no corre en clone fresco | `pyproject` declara `asyncio_mode="auto"` + `--strict-config` pero `pytest-asyncio`/`responses` no se instalan solos → `INTERNALERROR` en TODO `pytest`. Falta paso `pip install -r requirements-dev.txt` documentado como **obligatorio** | QA Agent: doc + `run_tests.ps1 -Install` por default, o quitar `asyncio_mode` si no se usa async |
| `scene_moments` table ausente | Tests de `content_rotator` y `signals_distiller` fallan con `no such table: scene_moments` (no está en `db.py` SCHEMA). 10 tests rojos pre-existentes | Production/Signals Agent: añadir la tabla al SCHEMA o ajustar los tests |
| `run_signals.ps1` declara `-Verbose` sobre `[CmdletBinding()]` | Conflicto de parámetro (`ParameterNameAlreadyExistsForCommand`). `run_analytics.ps1` lo evitó usando `-Detailed` | QA Agent: renombrar el switch en `run_signals.ps1` |

## Docs candidatos a borrar / mover

Auditar uno por uno con criterio "es la fuente de verdad para alguien hoy?".

| Path | Estado sospechoso | Decisión recomendada |
|---|---|---|
| `ARCHITECTURE.md` (root) | Probable duplicado de `docs/architecture/MLOPS_FLOW.md` | Comparar; si duplica → borrar y redirect en README |
| `ARCHITECTURE_PERSONAS.md` (root) | ¿Se solapa con `src/apps/content/personas.py` docstring? | Si describe data viva → mover a `docs/architecture/PERSONAS.md`; si es historia → borrar |
| `COMANDOS_CLAUDE.md` (root) | Probable scratchpad del owner | Mover a `docs/_internal/` o borrar |
| `DIAGRAMA_FLUJO_EDICION.md` (root) | Probablemente reemplazado por MLOPS_FLOW | Comparar; merge en MLOPS_FLOW si vale |
| `FLUJO_PUBLICACION_CADA_3_DIAS.md` (root) | Reemplazado por rotator + content_rotation.yml | Decidir si la prosa aporta vs YAML del workflow |
| `GUIA_APIS_YOUTUBE_TIKTOK.md` (root) | Pendiente integración (uploads paused) | Mover a `docs/operations/UPLOADS.md` o `docs/_drafts/` |
| `GUIA_EDICION_VIDEO.md` (root) | Solapa con `METODOLOGIA_EDICION_DAVINCI.md` | Mergear y mover a `docs/architecture/EDITING.md` |
| `MANIFIESTO.md` (root) | Propiedad del owner | Dejar en root pero linkear desde docs/README |
| `METODOLOGIA_EDICION_DAVINCI.md` (root) | Posible legacy DaVinci (no usamos) | Si pipeline ya no usa DaVinci → mover a `docs/_archive/` |
| `PLAN_FASE_2.md` (root) | Probable plan ya ejecutado o reemplazado por roadmap | Comparar con ROADMAP y borrar el viejo |
| `ROADMAP.md` (root) | ¿Sincronizado con MLOPS_FLOW.md § Roadmap? | Si duplica → consolidar uno solo |
| `SETUP_CUENTAS.md` (root) | Setup de cuentas (OAuth, canales) | Mover a `docs/operations/SETUP_ACCOUNTS.md` |
| `README.md` (root) | Punto de entrada del repo | Auditar y mantener; linkear a `docs/README.md` |
| `docs/privacy.html` | Legacy del sitio TikTok review — la fuente viva está en `youlikeit-web/public/` | Borrar (duplica) |
| `docs/terms.html` | Idem | Borrar (duplica) |
| `docs/tiktok6SqmAImuROUyUPH61nJk6s8TjcqpaJXF.txt` | Verification file de TikTok | Verificar si TikTok aún lo requiere; si sí, mover a `youlikeit-web/public/`; si no, borrar |
| `docs/callback/index.html` | OAuth callback — duplica `youlikeit-web/public/callback/` | Borrar |

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
- [ ] **DA08** (nuevo): mover `SETUP_CUENTAS.md` requiere sub-tarea a setup/uploads
  para actualizar la referencia en `scripts/legacy/exercises/ex34_oauth_manager.py` (acoplamiento doc↔código).

---

*Owner: este agente. Última actualización: 2026-06-02.*
