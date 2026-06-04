# Architecture Decision Records (ADRs)

Decisiones arquitectónicas no obvias de YouLikeIt, en formato
[MADR](https://adr.github.io/madr/). Documentamos **decisiones ya tomadas**
de forma retroactiva; estos archivos no deciden nada nuevo.

| # | Decisión | Estado |
|---|---|---|
| [0001](0001-why-algorithmic-not-llm.md) | Generación algorítmica, no LLM, en el camino crítico | accepted |
| [0002](0002-why-sqlite-not-postgres.md) | SQLite (no Postgres) como store | accepted |
| [0003](0003-why-fixed-catalog.md) | CATALOG fijo curado (los briefs solo dan boost) | accepted |

## Cómo añadir una ADR

1. Copiar el formato de una existente (Context → Drivers → Options → Outcome → Consequences).
2. Numerar secuencial (`000N-titulo-en-kebab.md`).
3. Estado: `proposed` → `accepted` / `rejected` / `superseded by 000M`.
4. Registrarla en la tabla de arriba.
