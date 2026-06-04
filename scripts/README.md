# Scripts · Índice por dominio

> Punto de entrada recomendado: el CLI **`ylk`** (instalado con `pip install -e .`,
> ya incluido en la imagen Docker). Los scripts por dominio siguen disponibles para
> uso directo; `ylk` es un front-door delgado sobre ellos.

```
scripts/
├── README.md          ← estás aquí
├── _TEMPLATE_runner.py  plantilla para un runner nuevo (clónala)
├── signals/           Ingesta + distill + verify (dominio Signals)
├── production/        Rotator + render + batch orchestrator
├── scoring/           Hook scorer + A/B setup
├── analytics/         Plausible: setup + fetch stats + dashboard
├── testing/           Runners pytest por dominio + audit completo
├── setup/             Voces, OAuth, descargas iniciales
├── uploads/           Subida a YouTube / TikTok
└── legacy/            Pre-pytest + exercises ex00–ex40 + main.py — solo referencia
```

## CLI unificado `ylk`

```bash
ylk --help                         # lista dominios + verbos
ylk signals refresh --no-llm       # = scripts/signals/refresh_market_signals.py
ylk signals verify --cleanup
ylk signals dashboard --validate
ylk produce --series "Berserk" --persona deep_mind --dry-run
ylk rotate --personas deep_mind pop_oracle latam
ylk score --rescore
ylk analytics dashboard
```

Cada subcomando reenvía sus flags al runner subyacente (passthrough). El CLI vive
en [src/cli/](../src/cli/); agregar un comando es agregar una función en
`src/cli/commands/<dominio>.py`.

## Regla de oro — cómo agregar funcionalidad de forma organizada

Toda funcionalidad nueva es una **tupla de 4**, alineada por dominio:

| Capa | Dónde | Qué |
|---|---|---|
| Lógica | `src/apps/<dominio>/` | el código de negocio (importable, testeable) |
| Entrada | `ylk <dominio> <acción>` (o `scripts/<dominio>/`) | runner **delgado**: parsea args y llama a `apps/<dominio>` |
| Tests | `tests/<dominio>/` | pytest del dominio |
| Handbook | `docs/agents/<DOMINIO>_AGENT.md` | scope, DoD, comando de verificación |

Un **runner** no contiene lógica de negocio: orquesta y delega. Plantilla en
[`_TEMPLATE_runner.py`](_TEMPLATE_runner.py).

## Regla Docker (integraciones / dependencias)

- **Dependencias e integraciones de librerías van por Docker.** Una dep nueva se
  agrega a [`requirements.txt`](../requirements.txt) y se reconstruye la imagen
  (`docker compose build ytlab`). **Nunca** `pip install` suelto en el host.
- El paquete se instala editable en la imagen (`pip install -e .`), por eso los
  scripts importan `from apps.signals… import` sin trucos de `sys.path`.
- Forma canónica de correr un runner:
  ```bash
  docker compose run --rm ytlab ylk signals refresh --no-llm
  docker compose run --rm ytlab python scripts/production/produce_for_series.py --series "Berserk" --persona deep_mind
  ```

## Comandos esenciales

```powershell
.\scripts\testing\run_tests.ps1 -Mode quick      # verificación rápida (< 20s)
.\scripts\testing\run_all.ps1 -WithCoverage       # audit completo por dominios
.\scripts\testing\run_signals.ps1                 # un solo dominio
```

## Mapping con dominios y agentes

| Carpeta | Handbook del owner |
|---|---|
| `signals/` | [docs/agents/SIGNALS_AGENT.md](../docs/agents/SIGNALS_AGENT.md) |
| `production/` | [docs/agents/PRODUCTION_AGENT.md](../docs/agents/PRODUCTION_AGENT.md) |
| `scoring/` | [docs/agents/SCORING_AGENT.md](../docs/agents/SCORING_AGENT.md) |
| `analytics/` | [docs/agents/ANALYTICS_AGENT.md](../docs/agents/ANALYTICS_AGENT.md) |
| `testing/` | [docs/agents/QA_AGENT.md](../docs/agents/QA_AGENT.md) |
| `setup/` | _(pendiente)_ |
| `uploads/` | _(pendiente — diferido hasta TikTok review)_ |
| `legacy/` | nadie. Solo lectura. |

---

*Última actualización: 2026-06-03.*
