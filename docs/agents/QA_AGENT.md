# QA / Testing Agent · Handbook

> **Scope**: harness de testing, coverage, invariantes runtime, smoke E2E,
> coordinación de tareas cross-dominio.
> Este agente **es el único** autorizado a tocar `conftest.py`, `pyproject.toml`,
> el runner unificado y los thresholds de coverage.

---

## Archivos bajo tu dominio

| Archivo | Rol |
|---|---|
| [pyproject.toml](../../pyproject.toml) | Config pytest + coverage + ruff |
| [requirements-dev.txt](../../requirements-dev.txt) | Deps de testing |
| [tests/conftest.py](../../tests/conftest.py) | Fixtures globales (conn, sample_signals, mocked_http, frozen_time) |
| [scripts/testing/run_tests.ps1](../../scripts/testing/run_tests.ps1) | Runner unificado (quick/unit/integration/e2e/coverage/all) |
| [scripts/testing/run_signals.ps1](../../scripts/testing/run_signals.ps1) | Test runner del dominio signals |
| [scripts/testing/run_production.ps1](../../scripts/testing/run_production.ps1) | Test runner del dominio production |
| [scripts/testing/run_scoring.ps1](../../scripts/testing/run_scoring.ps1) | Test runner del dominio scoring |
| [docs/testing/INTEGRATION_CHECKLIST.md](../testing/INTEGRATION_CHECKLIST.md) | Checklist marcable de integraciones |
| [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) | Items diferidos con DoD |

## Archivos que NO puedes tocar directamente

- Tests específicos de un dominio sin coordinar con su owner
- Modules de `src/core/`, `src/utils/`, `src/apps/`, `src/integrations/` salvo para fixtures de test
- CATALOG, ALIAS_MAP, weights, scoring → coordinar con dominio dueño

Tu rol es **infraestructura de testing**, no implementación de lógica.

---

## Responsabilidades exclusivas

1. **Mantenimiento de `conftest.py`** y fixtures compartidos
2. **Configuración de markers** (unit/integration/e2e/network/gpu/slow)
3. **Coverage thresholds** y reportes HTML
4. **Smoke E2E runner** (`verify_signals_flow.py` mantenido por Signals; runner por QA)
5. **CI/CD config** (GHA workflows de testing, no de producción)
6. **Coordinación cross-dominio** cuando un cambio toca 2+ dominios
7. **Audit periódico**: correr `run_tests.ps1 -Mode all` y reportar regresiones

---

## Definition of Done por tipo de tarea

### Añadir nuevo fixture global

- [ ] Fixture en `conftest.py` con docstring explicando uso
- [ ] Naming consistente (snake_case, descriptivo)
- [ ] Cleanup automático (yield + teardown si tiene side effects)
- [ ] Ejemplo de uso en al menos 1 test existente
- [ ] Coverage no baja por la introducción

### Añadir nuevo marker pytest

- [ ] Declarado en `pyproject.toml [tool.pytest.ini_options].markers`
- [ ] Documentado en docstring del marker (qué cubre, cuándo usar)
- [ ] Actualizado en `INTEGRATION_CHECKLIST.md` si afecta la suite default

### Subir coverage threshold

- [ ] `pyproject.toml` `fail_under` actualizado solo si la suite actual lo cumple
- [ ] CI workflow refleja el cambio
- [ ] Documentación en `INTEGRATION_CHECKLIST.md` § "Coverage thresholds bloqueantes"

### Configurar GHA workflow nuevo

- [ ] YAML válido (`gh workflow view` pasa)
- [ ] Concurrency group para evitar runs simultáneos donde no debe
- [ ] Cache de dependencias activado
- [ ] Permissions mínimas necesarias (no `write-all`)
- [ ] Artifact upload con retention adecuada

---

## Comando único de verificación

```powershell
# Audit completo (lo más cercano a "todo verde")
.\scripts\testing\run_tests.ps1 -Mode all
```

Esto corre:
1. pytest suite completa con coverage HTML
2. `verify_signals_flow.py --cleanup`

Para audits parciales:
```powershell
.\scripts\testing\run_tests.ps1 -Mode quick     # < 20s
.\scripts\testing\run_signals.ps1               # solo signals
.\scripts\testing\run_production.ps1            # solo production
.\scripts\testing\run_scoring.ps1               # solo scoring
.\scripts\testing\run_tests.ps1 -Mode coverage  # HTML report
```

---

## Métricas globales que sigues

| Métrica | Baseline | Cómo medir |
|---|---|---|
| Coverage total `src/{core,utils,apps,integrations}/` | ≥ 75% | `pytest --cov` |
| Tiempo suite completa | < 60s | `pytest --durations=10` |
| Tests count | ≥ 88 | output de `pytest --collect-only -q` |
| Flaky tests | 0 | run 3x; cualquiera que cambie de resultado → quarantine |
| Coverage HTML generado | sí | `Test-Path htmlcov/index.html` |

---

## Anti-patrones específicos

- ❌ Eliminar fixtures sin sustituir y notificar al owner
- ❌ Mergear cambios donde ALGÚN test falla (incluso unrelated)
- ❌ Saltar el smoke E2E porque "no toca ese dominio" — el smoke siempre corre
- ❌ Cambiar `addopts` en `pyproject.toml` sin discutir con owners
- ❌ Quitar `no_real_http` autouse (es la defensa contra fugas de red)
- ❌ Dejar `xfail` o `skip` sin entry en `PENDING_TESTS.md`

---

## Protocolo de tarea cross-dominio

Cuando un cambio cruza 2+ dominios, QA Agent es el coordinador:

1. **Trianglar** el cambio: qué módulos toca, qué tests afecta
2. **Sub-tareas** abiertas por dominio con su DoD
3. **Orden de ejecución** definido (deps entre cambios)
4. **Comando de verificación final**: `run_tests.ps1 -Mode all`
5. **Sign-off** de cada owner antes de merge
6. **Audit post-merge** corriendo el modo `all` en main

---

## Tareas abiertas conocidas

Ver [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) items:
- **#2** Smoke alias_map_consistency en CI (ya está como test, falta GHA)
- **#4** Calibración thresholds en `signals_validation`
- **#8** Streamlit dashboard
- **#9** Migración a Postgres + pgvector
- **#10** Benchmark vs AutoClip (coordinación general)

---

*Owner: este agente. Última actualización: 2026-06-02.*
