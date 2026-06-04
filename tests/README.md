# tests/ · Suite pytest por dominio

> Tests organizados en subcarpetas espejando los dominios.
> Configuración global vive en [conftest.py](conftest.py).

```
tests/
├── README.md             ← estás aquí
├── conftest.py           Fixtures compartidos (conn, sample_signals, mocked_http, frozen_time)
├── signals/              Dominio Signals (~70 tests)
│   ├── test_brief_resolver.py
│   ├── test_market_signals.py
│   ├── test_signals_distiller.py
│   └── test_signals_validation.py
├── production/           Dominio Production
│   └── test_content_rotator.py
├── scoring/              Dominio Scoring
│   └── test_hook_scorer.py
├── analytics/            Dominio Analytics (Plausible, 27 tests)
│   ├── conftest.py       Payloads sintéticos de la Stats API
│   ├── test_plausible_client.py
│   ├── test_internal_signals.py
│   ├── test_dashboard.py
│   └── test_unified_analytics.py   Vista conjunta (4 capas + rollup)
└── integration/          E2E cross-dominio
    └── test_integration_e2e.py
```

## Comandos rápidos

```powershell
# Suite completa (recursivo)
python -m pytest

# Solo un dominio
python -m pytest tests/signals/
python -m pytest tests/production/
python -m pytest tests/scoring/
python -m pytest tests/integration/

# Por marker
python -m pytest -m unit          # < 5s
python -m pytest -m integration   # < 15s
python -m pytest -m e2e           # < 5s

# Con coverage HTML
python -m pytest --cov --cov-report=html
```

## Convenciones

- **Test file naming**: `test_<module>.py` 1:1 con módulo en `src/apps/<dominio>/` (o `src/core/`, `src/utils/`)
- **Markers** (declarados en `pyproject.toml`):
  - `unit` → puro Python, sin I/O, < 50ms
  - `integration` → SQLite temp + HTTP mocks, < 2s
  - `e2e` → pipeline completo (puede ser lento)
  - `network` / `gpu` → opt-in, no corre por default
- **Fixtures**: declarar en `conftest.py` si es compartido entre dominios, en el test file si es específico
- **Mocks de HTTP**: `responses` (no monkeypatch ad-hoc)
- **Mocks de tiempo**: `freezegun`

## Defensas globales

`conftest.py` instala 2 autouse fixtures:
- `no_real_http` → bloquea llamadas HTTP reales sin marker `@pytest.mark.network`
- `clean_env` → borra API keys del environment

Si tu test necesita HTTP real → declarar `@pytest.mark.network`.

## Cobertura objetivo

Ver [docs/agents/QA_AGENT.md § Métricas globales](../docs/agents/QA_AGENT.md).

| Dominio | Coverage objetivo |
|---|---|
| signals | ≥ 80% |
| production | ≥ 70% |
| scoring | ≥ 60% |
| analytics (`plausible_client`, `internal_signals`, `unified_analytics`) | ≥ 80% |
| total `src/` | ≥ 75% |
