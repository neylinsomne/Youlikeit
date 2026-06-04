# Runbook On-Call · YouLikeIt

> Qué hacer cuando algo se rompe. Cada incident: **síntoma → diagnóstico → fix
> → rollback**. Ordenado por probabilidad. Comandos en PowerShell desde el root del repo.

## Cómo usar este runbook

1. Identifica el síntoma en la tabla de abajo.
2. Ve al incident, corre el **diagnóstico** antes de tocar nada.
3. Aplica el **fix** mínimo. Si empeora, aplica el **rollback**.
4. Registra lo ocurrido en [../CHANGELOG.md](../CHANGELOG.md) si cambió comportamiento.

| # | Síntoma rápido | Incident |
|---|---|---|
| 1 | No entran señales nuevas / un scraper falla seguido | [Scraper caído](#incident-1--scraper-caído--24h) |
| 2 | Crece `unresolved_briefs_queue`, briefs no se producen | [Brief sin match](#incident-2--brief-sin-match) |
| 3 | `produce_for_series.py` aborta en el render | [Render falla](#incident-3--render-falla-ffmpeg--nvenc) |
| 4 | Un workflow de GitHub Actions sale rojo | [GHA cron rojo](#incident-4--gha-cron-rojo) |
| 5 | El hook scorer crashea o bloquea producción | [Hook score crash](#incident-5--hook-score-crash--gate) |

---

## Incident 1 · Scraper caído > 24h

**Síntoma:** `market_signals.total_new_last_24h` < 100, o una fuente con
`scraper_health.fail_rate` > 0.3.

**Diagnóstico:**
```powershell
python scripts/signals/briefs_dashboard.py   # panel SCRAPER HEALTH: last_success, fail_rate
# Probar la fuente sospechosa aislada (HTTP real, sin LLM):
python scripts/signals/refresh_market_signals.py --no-llm --sources steam_charts
```

**Fix:**
- Si la fuente cambió su HTML/feed → ajustar el parser de esa fuente en
  `src/apps/signals/market_signals.py` (abrir sub-tarea al **Signals Agent**; docs no toca `src/`).
- Si es rate-limit / IP-ban transitorio → esperar y reintentar; bajar la frecuencia del cron.
- Si la fuente murió → quitarla de `SOURCES` y documentar.

**Rollback:** una fuente caída **no** bloquea el pipeline (contrato `() → list[Signal]`
fail-soft). Si un cambio al parser empeora la ingesta, revertir ese commit; el
resto de fuentes sigue alimentando briefs.

---

## Incident 2 · Brief sin match

**Síntoma:** `unresolved_briefs_queue` crece; el rotator no encuentra slug para briefs vivos.

**Diagnóstico:**
```powershell
python scripts/signals/briefs_dashboard.py --resolve-preview   # qué slug elegiría el resolver
python -m pytest tests/signals/test_brief_resolver.py::TestAliasMapIntegrity -v
```

**Fix:**
- Si un alias apunta fuera del CATALOG → corregir `ALIAS_MAP` / `CATALOG`
  (sub-tarea al **Signals/Production Agent**).
- Si es un tema nuevo legítimo → decisión humana: añadirlo al `CATALOG` con ≥1 alias
  (`T03`), o descartarlo desde la queue.
- Recordar: por diseño los briefs **solo dan boost**, no crean entradas
  (ver [ADR 0003](../architecture/DECISIONS/0003-why-fixed-catalog.md)).

**Rollback:** la queue es no-destructiva; vaciarla mal no pierde datos de producción.
Si un cambio al ALIAS_MAP rompe el smoke, revertirlo y re-correr el test de integridad.

---

## Incident 3 · Render falla (FFmpeg / NVENC)

**Síntoma:** `produce_for_series.py` aborta; no aparece el `.mp4` en `produced_videos/`.

**Diagnóstico:**
```powershell
docker ps                       # ¿servicios activos? el render necesita Docker/GPU
nvidia-smi                      # ¿GPU visible para NVENC?
```
Revisar el log de la corrida: ¿falta audio (edge-tts), imágenes (panel_matcher) o falla h264_nvenc?

**Fix:**
- NVENC no disponible → caer a encoder CPU (libx264) temporalmente, o reiniciar el contenedor GPU.
- Falta un asset (imagen/audio) → re-generar esa etapa; verificar `panel_matcher` y edge-tts.
- Cambios de pipeline de render → sub-tarea al **Production Agent**.

**Rollback:** el render es idempotente por serie/slug/vtype; re-correr sobrescribe
sin corromper estado. Revertir el commit del director si una edición rompió el render.

---

## Incident 4 · GHA cron rojo

**Síntoma:** `refresh-signals.yml`, `content-rotation.yml` o `pipeline.yml` sale rojo en Actions.

**Diagnóstico:**
```powershell
gh run list --workflow refresh-signals.yml
gh run view <run-id> --log-failed
gh workflow view refresh-signals.yml
```
Causas típicas: secret faltante/rotado (`GEMINI_API_KEY`, `TRAKT_CLIENT_ID`),
dep nueva sin instalar, o una fuente caída con `--fail-on-empty`.

**Fix:**
- Secret → revisar/rotar en GitHub Settings → Secrets (ver [SECURITY.md](SECURITY.md)).
- Dep → actualizar `requirements.txt` (sub-tarea al dominio dueño).
- `--fail-on-empty` disparado por ingesta vacía → tratar como [Incident 1](#incident-1--scraper-caído--24h).

**Rollback:** los crons son idempotentes; un run rojo no corrompe la DB. Re-disparar
con `workflow_dispatch` tras el fix. Si un cambio al YAML rompió el cron, revertir ese commit.

---

## Incident 5 · Hook score crash / gate

**Síntoma:** `score_hooks.py` crashea, o la producción se bloquea por el gate de hook.

**Diagnóstico:**
```powershell
python scripts/scoring/score_hooks.py --csv out/hook_scores.csv
python -m pytest tests/scoring/test_hook_scorer.py -v
```
Si el video no existe → el scorer debe devolver 0 (`TestScoreHookRobustness`), no crashear.

**Fix:**
- Video faltante / corrupto → re-renderizar antes de scorear (ver [Incident 3](#incident-3--render-falla-ffmpeg--nvenc)).
- Crash real en el scorer → sub-tarea al **Scoring Agent**.
- Hoy el gate corre con `block_on_fail=False`: **no** debería bloquear producción.
  Si alguien lo activó antes de calibrar `MIN_HOOK_SCORE` (>30 videos/persona/vtype),
  volverlo a `False`.

**Rollback:** poner `block_on_fail=False` desbloquea la producción al instante.
Los scores viven en `hook_scores` y se pueden regenerar con `--rescore`.

---

## Escalado

- Incident acotado a un dominio → sub-tarea al Agent dueño (ver [AGENT_TASKS.md](../agents/AGENT_TASKS.md)).
- Cruza 2+ dominios → coordinar vía QA Agent.
- Secrets / accesos comprometidos → [SECURITY.md](SECURITY.md) primero.
