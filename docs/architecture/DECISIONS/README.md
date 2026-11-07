# Architecture Decision Records (ADRs)

Decisiones arquitectónicas no obvias de YouLikeIt, en formato
[MADR](https://adr.github.io/madr/). Documentamos **decisiones ya tomadas**
de forma retroactiva; estos archivos no deciden nada nuevo.

| # | Decisión | Estado |
|---|---|---|
| [0001](0001-why-algorithmic-not-llm.md) | Generación algorítmica, no LLM, en el camino crítico (producto anterior) | accepted (alcance acotado por 0007) |
| [0002](0002-why-sqlite-not-postgres.md) | SQLite (no Postgres) como store | accepted |
| [0003](0003-why-fixed-catalog.md) | CATALOG fijo curado (los briefs solo dan boost) | accepted (producto anterior) |
| [0004](0004-legit-sources-only.md) | Solo fuentes legítimas; Torrentio/qBittorrent congelado | accepted |
| [0005](0005-railway-only-for-public-site.md) | Railway solo para el sitio público; la producción es local | accepted |
| [0006](0006-no-mixed-music-drafts-60s.md) | Sin música mezclada, TikTok como borrador, lecciones ≤ 60 s | accepted |
| [0007](0007-swappable-local-api-ai.md) | IA intercambiable: local o por API | accepted |
| [0008](0008-per-film-audio-percentiles.md) | Señales de audio con percentiles por película | accepted |

## Cómo añadir una ADR

1. Copiar el formato de una existente (Context → Drivers → Options → Outcome → Consequences).
2. Numerar secuencial (`000N-titulo-en-kebab.md`).
3. Estado: `proposed` → `accepted` / `rejected` / `superseded by 000M`.
4. Registrarla en la tabla de arriba.
