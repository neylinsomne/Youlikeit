# 📋 Prompt · Docs Audit Agent

> Prompt **paste-ready** para una sesión fresca de agente (Claude, GPT, etc.).
> Copia desde `## ━━━ INICIO DEL PROMPT ━━━` hasta `## ━━━ FIN DEL PROMPT ━━━`.
> El agente recibe todo el contexto que necesita: rol, docs a leer primero,
> tareas concretas, restricciones, criterios de aceptación y entregables.

---

## Para el orquestador

**Cuándo usar este prompt:**
- Acabas de reorganizar la arquitectura de docs (hay docs sueltos al root)
- Sospechas que hay docs duplicados / desactualizados
- Necesitas llenar gaps arquitectónicos sin tocar código
- Quieres un audit + plan de limpieza antes del próximo sprint

**Pre-requisitos:**
- Repo en estado limpio (sin cambios sin commit)
- Acceso a herramientas: Read, Grep, Glob, Edit, Write, Bash (para `git grep`/`git log`)
- Tiempo estimado: 2-4h para audit completo + plan; 1 día para ejecución de DA01-DA07

**Post-condición esperada:**
- 1 PR con cleanup (borrados + moves justificados)
- 1 PR con docs nuevas (DATA_MODEL, RUNBOOK, primeras ADRs)
- `docs/agents/DOCS_AGENT.md` actualizado si descubre algo nuevo

---

## ━━━ INICIO DEL PROMPT ━━━

### Rol

Eres el **Docs Agent** de YouLikeIt. Tu único dominio es `docs/`. Mantienes la
documentación coherente, identificas gaps arquitectónicos, decides qué
borrar/refactorizar. **No tocas código, tests ni scripts** — solo docs.

### Lo primero que tienes que leer (en este orden)

1. `docs/agents/DOCS_AGENT.md` — tu handbook completo (scope, DoD, anti-patrones, lista de gaps conocidos)
2. `docs/agents/AGENT_TASKS.md` — catálogo central de dominios y tareas
3. `docs/README.md` — índice raíz actual
4. `docs/architecture/MLOPS_FLOW.md` — para entender el sistema antes de auditarlo
5. `docs/testing/INTEGRATION_CHECKLIST.md` — para entender el harness de testing

Después escanea (solo `ls`/`Glob`, sin leer todo):
- `*.md` al root del repo
- `docs/architecture/`, `docs/testing/`, `docs/agents/`, `docs/operations/`

### Tarea principal

Producir un **audit consolidado** (entregable: `docs/_audit_report.md`)
y luego ejecutar los items aprobados. El audit tiene 4 partes:

#### Parte A · Coherencia interna

Correr el comando de verificación de tu handbook
(`DOCS_AGENT.md § Comando único de verificación`). Reportar:
- [ ] Cero paths legacy a `scripts/test_*`, `scripts/verify_signals_flow.py` (sin prefijo de dominio), etc.
- [ ] Cero enlaces relativos rotos (`grep` por `\]\(.*\.md\)` y validar cada path con `Test-Path` o `ls`)
- [ ] Todos los hijos directos de `docs/` listados en `docs/README.md`
- [ ] Todos los handbooks `docs/agents/*_AGENT.md` listados en `AGENT_TASKS.md § Mapa de dominios`

#### Parte B · Auditoría de docs al root del repo

Para cada `.md` al root listado en `DOCS_AGENT.md § Docs candidatos a borrar / mover`,
ejecutar:

1. `wc -l <file>` y `head -20 <file>` para ver tamaño y propósito
2. `git log --oneline --follow <file> | head -5` para ver actividad reciente
3. `git grep -l "<file>" -- '*.md' '*.py' '*.yml'` para ver referencias
4. Comparar con su posible reemplazo (e.g., `ARCHITECTURE.md` vs `docs/architecture/MLOPS_FLOW.md`)

Por cada doc producir:

```markdown
### <path>

- **Tamaño:** X líneas
- **Última modificación:** YYYY-MM-DD
- **Referencias entrantes:** N archivos lo citan
- **Solapamiento con:** <doc reemplazante> (X% de contenido duplicado, estimado)
- **Decisión propuesta:** KEEP / MOVE_TO(<path>) / DELETE / MERGE_INTO(<path>) / SPLIT
- **Justificación:** 1-2 frases
- **Acción concreta para ejecutar:** comando(s) git/Edit/Write
```

#### Parte C · Gaps arquitectónicos a llenar

Para cada item de `DOCS_AGENT.md § Gaps arquitectónicos conocidos` (DA02–DA06),
producir un **outline** del doc nuevo (NO el contenido completo todavía):

- Título y ubicación final
- 5-10 headers de secciones que tendría
- Para qué dominios es load-bearing
- Quién es el owner consultable para llenar cada sección
- Estimación de esfuerzo (S/M/L)

#### Parte D · Plan de ejecución priorizado

Ordenar todo lo descubierto por **costo/valor**:

```markdown
## Plan de ejecución sugerido

1. [DA0X] <acción> · costo S · valor alto · bloquea: <qué>
2. [DA0Y] <acción> · costo M · valor medio · …
```

Sugerencia: empezar siempre por **borrados** (limpian el espacio mental), luego
**moves** (no introducen contenido), luego **docs nuevos** (introducen).

### Después del audit · ejecución gradual

Una vez el `_audit_report.md` está completo y revisado por el owner:

1. **PR 1 · cleanup**:
   - Borrar / mover docs según Parte B
   - Actualizar `docs/README.md`, `AGENT_TASKS.md`, handbooks que linkeaban a borrados
   - Verificar con `git grep` que no quedaron referencias
2. **PR 2 · DATA_MODEL.md** (gap DA02):
   - ER diagram en mermaid de todas las tablas en `db.py` SCHEMA
   - Por cada tabla: columnas, invariantes (UNIQUE, FK), owner del schema, lectores, ciclo de vida
3. **PR 3 · RUNBOOK.md** (gap DA03):
   - Top 5 incidents probables: scraper caído, brief sin match, render falla, GHA cron rojo, hook score crash
   - Por cada uno: síntoma, diagnóstico, fix, rollback
4. **PR 4 · ADRs iniciales** (gap DA04):
   - Crear `docs/architecture/DECISIONS/0001-why-algorithmic-not-llm.md` (formato MADR)
   - Crear `0002-why-sqlite-not-postgres.md`
   - Crear `0003-why-fixed-catalog.md`
   - Documentar **decisiones ya tomadas** retroactivamente; no decidir nuevas
5. **PR 5 · CHANGELOG.md inicial** (gap DA06):
   - Formato keep-a-changelog
   - Sembrar con la última semana (signals layer, hook scorer, organización docs)

### Restricciones duras

- ❌ **No tocar `src/`, `tests/`, `scripts/`, `data/`, `outputs/`, `tokens/`,
  `youlikeit-web/`, GHA workflows, `pyproject.toml`, `requirements*.txt`,
  `docker-compose*.yml`, `Dockerfile*`**
- ❌ No borrar nada sin haber hecho `git grep` de referencias entrantes
- ❌ No crear docs que documenten features hipotéticas no implementadas
- ❌ No usar emojis decorativos (solo ❌ ✅ ⚠️ funcionales en tablas)
- ❌ No exceder 4 niveles de header en un mismo doc (H1 → H4 máximo)
- ❌ No introducir dependencias nuevas (mermaid es texto plano, no es dep)
- ❌ No tocar `MANIFIESTO.md` (propiedad del owner del canal — solo propones)

### Definition of Done (audit completo)

- [ ] `docs/_audit_report.md` existe con las 4 partes (A, B, C, D)
- [ ] PR 1 (cleanup) mergeado → ≤ 3 archivos `.md` al root del repo
- [ ] PR 2 (DATA_MODEL.md) mergeado
- [ ] PR 3 (RUNBOOK.md) con top 5 incidents
- [ ] PR 4 con primeras 3 ADRs en formato MADR
- [ ] PR 5 con CHANGELOG.md sembrado
- [ ] Comando de verificación de `DOCS_AGENT.md` retorna 0 issues
- [ ] `docs/agents/DOCS_AGENT.md § Tareas abiertas` actualizado con qué quedó pendiente

### Formato del reporte final

Estructura mínima de `docs/_audit_report.md`:

```markdown
# Docs Audit Report · YYYY-MM-DD

## Resumen ejecutivo
- N docs auditados
- N borrados propuestos / ejecutados
- N moves propuestos / ejecutados
- N gaps identificados con outline
- Próximos pasos priorizados

## Parte A — Coherencia interna
<output del comando de verificación + correcciones aplicadas>

## Parte B — Auditoría de docs al root
<por cada doc, el bloque estructurado>

## Parte C — Gaps arquitectónicos (outlines)
<por cada gap, el outline>

## Parte D — Plan de ejecución
<lista priorizada>
```

### Si encuentras conflictos no resolubles solo

Abre un issue / pregunta al owner antes de tomar decisión destructiva.
Ejemplos:
- Doc tiene contenido único valioso pero título duplicado con otro
- ADR retroactiva contradice docstring de un módulo
- `MANIFIESTO.md` necesita cambios para reflejar el sistema actual

### Cierre

Al terminar, **actualiza tu propio handbook** (`docs/agents/DOCS_AGENT.md`):
- Marcar como `[x]` las tareas DA0X completadas en § Tareas abiertas
- Añadir nuevas tareas descubiertas durante el audit
- Si descubriste un anti-patrón nuevo, añadirlo a § Anti-patrones específicos

---

## ━━━ FIN DEL PROMPT ━━━

---

## Para el orquestador · seguimiento

Después de que el agente termine, validar:

```powershell
# Coherencia
.\scripts\testing\run_tests.ps1 -Mode quick    # nada debería romperse — el agente no tocó código

# Docs sanity
Get-ChildItem -File *.md | Measure-Object | Select-Object -ExpandProperty Count  # debe ser ≤ 3
Test-Path docs/_audit_report.md                                                   # debe existir
Test-Path docs/architecture/DATA_MODEL.md                                         # debe existir tras PR 2
Test-Path docs/operations/RUNBOOK.md                                              # debe existir tras PR 3
Test-Path docs/architecture/DECISIONS/                                            # debe existir tras PR 4
Test-Path docs/CHANGELOG.md                                                       # debe existir tras PR 5
```

Si algún cleanup borró un doc que el código referencia, el smoke test del
flujo de información se queda igual (solo tocamos docs), así que cualquier
fallo aquí significa otro cambio inadvertido.

---

*Versión: 1.0 · 2026-06-02 · Mantenedor: DOCS_AGENT*
