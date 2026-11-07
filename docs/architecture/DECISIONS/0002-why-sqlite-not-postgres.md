# 0002 · SQLite (no Postgres) como store

- **Status:** accepted
- **Date:** 2026-06-02 (decisión tomada antes; documentada retroactivamente)
- **Deciders:** owner del repo
- **Fuente original:** [MLOPS_FLOW.md § Decisiones de diseño 2](../MLOPS_FLOW.md)

## Context and Problem Statement

Todo el estado del sistema (señales, briefs, hook scores, analítica, etc. — ~36
tablas en `src/core/db.py`) necesita un store persistente. La elección es entre
una base embebida (SQLite) y un servidor (Postgres + pgvector).

## Decision Drivers

- Dev local sin fricción: que el pipeline corra sin levantar un servidor.
- Volumen actual: muy por debajo de lo que justifica un RDBMS servido.
- Lectura concurrente: scrapers + dashboard + render leyendo a la vez.
- Camino de migración futuro si el proyecto escala a "producto".

## Considered Options

1. **SQLite** (embebido, `WAL mode`).
2. **Postgres + pgvector** desde el día 1 (Docker).
3. SQLite ahora, con el schema diseñado para portar a Postgres después.

## Decision Outcome

Elegida la **opción 3**: SQLite con `WAL mode` (permite lectura concurrente),
manteniendo el `SCHEMA` lo bastante estándar para que el **mismo schema funcione
en Postgres** cuando haga falta.

### Consequences

**Buenas:**
- Corre sin servidor ni Docker para el dev local.
- Suficientemente rápido al volumen actual.
- `WAL mode` resuelve la lectura concurrente.

**Malas / trade-offs:**
- No escala a multi-tenant.
- El gatillo de migración (`T40` en AGENT_TASKS) es cruzar ~1M señales o
  necesitar pgvector para embeddings (dedupe capa 3) → migrar a Postgres + pgvector.
- Hasta entonces, evitar features SQLite-only que compliquen el port.

## More Information

- Tareas relacionadas: `T40 · Migrar a Postgres + pgvector` (Tier 3) en
  [AGENT_TASKS.md](../../agents/AGENT_TASKS.md).
- Contrato de tablas: [DATA_MODEL.md](../DATA_MODEL.md).
