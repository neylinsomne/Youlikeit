# Runbook On-Call · YouLikeIt

> Qué hacer cuando algo se rompe. Cada incident: **síntoma → diagnóstico → fix
> → rollback**. Comandos en PowerShell desde el root del repo.
> Incidentes 1–5: producto anterior (señales, render por persona, hooks). Incidentes 6–15: ETL de
> lecciones, estudio y sitio (aprendidos en la corrida real del 2026-11-04). Última revisión: 2026-11-04.

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
| 6 | Una obra no tiene citas/trama, o son de otra película | [Anclas vacías o equivocadas](#incident-6--anclas-wikiquote--wikipedia-vacías-o-equivocadas) |
| 7 | La extracción de un tramo falla con HTTP 500 | [Internet Archive 500](#incident-7--internet-archive-responde-500) |
| 8 | Un master de IA "dura 5 s" o el rango no salta | [Master MPEG-PS sin índice](#incident-8--master-mpeg-ps-de-dvd-sin-índice) |
| 9 | Etiquetado o guion lento / falla con Groq | [Groq 429 / 400 / fuera de vocabulario](#incident-9--groq-429-400-json_validate_failed-o-valores-fuera-del-vocabulario) |
| 10 | El ASR local espera la GPU para siempre | [GPU lock tomado](#incident-10--gpu-lock-tomado) |
| 11 | Un job del estudio quedó "running" o la lección en "rendering" | [Job colgado](#incident-11--job-del-estudio-colgado) |
| 12 | El estudio responde 401 / 403 / 503 o el front no carga datos | [Estudio no autoriza](#incident-12--el-estudio-responde-401--403--503) |
| 13 | Render falla o "no hay suficientes obras" | [Render / plan de lección](#incident-13--render-o-plan-de-lección-falla) |
| 14 | No se puede enviar a TikTok desde el estudio | [Puente de TikTok](#incident-14--puente-de-tiktok-falla) |
| 15 | El sitio público no responde | [Railway caído](#incident-15--sitio-público-caído-railway) |

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

## Incident 6 · Anclas Wikiquote / Wikipedia vacías o equivocadas

**Síntoma:** `ylk moments show <asset>` no trae `quote` ni `plot` en las anclas, o las citas son de un
remake, de otra película o de una persona.

**Causas conocidas (ya corregidas en el código):**
- La búsqueda de texto completo de Wikiquote prioriza páginas de personas → ahora se prueban primero
  títulos exactos (`Title (YEAR film)`, `Title (film)`, `Title`).
- El año de estreno difiere entre fuentes (Internet Archive vs Wikipedia) → se acepta ±2 años.
- Una respuesta vacía (fallo de red o de búsqueda) quedaba cacheada → ahora vence a los 7 días.

**Diagnóstico:**
```powershell
ylk media assets                                  # título y año con que se registró la obra
ylk moments show <asset> --top 5                   # ¿hay anclas?
```

**Fix:** registrar la obra con el título canónico de Wikipedia y su año
(`ylk media add … --title "..." --year NNNN`) y re-detectar bajando de nuevo las anclas:
`ylk moments detect <asset> --refresh`.

**Rollback:** re-detectar solo reemplaza los momentos `candidate`; los etiquetados se conservan.

---

## Incident 7 · Internet Archive responde 500

**Síntoma:** el render o el preview fallan con `No se pudo extraer el segmento de ninguna fuente`, o el
progreso dice "master no disponible, uso el proxy".

**Diagnóstico:** nodos de IA que responden 500 a ratos para un archivo concreto (visto con el master de
una película mientras su proxy funcionaba).

**Fix:** automático: `extract_segment_resilient` reintenta el master 3 veces con espera y cae al proxy
(misma línea de tiempo). Si fallan ambos, esperar unos minutos y volver a encolar el job.

**Rollback:** no aplica (no cambia estado; un render fallido vuelve la lección a `draft`).

---

## Incident 8 · Master MPEG-PS de DVD sin índice

**Síntoma:** `ffprobe` del master informa una duración absurda (p. ej. 5 s para 90 min) o la extracción
por rango devuelve el comienzo de la película.

**Causa:** contenedores sin índice (`.mpeg`, `.mpg`, `.ts`, `.m2ts`, `.vob`) no permiten saltar por rango.

**Fix:** el selector de master de `archive_org.py` ya prefiere el derivado h.264 indexado del **mismo**
original con resolución equivalente. Un asset registrado antes del arreglo conserva el master viejo:
volver a registrar el ítem (`ylk media add archive_org <id> --title ... --year ...`, crea un asset con
el master nuevo) e indexar ese.

**Rollback:** el asset viejo sigue en la DB; no usarlo en lecciones.

---

## Incident 9 · Groq 429, 400 `json_validate_failed` o valores fuera del vocabulario

**Síntoma:** `ylk moments label` o "Generar con IA" tardan mucho, o el reporte trae errores de lotes.

**Comportamiento actual (no es una falla):**
- `429` (límite por minuto del plan gratis): se espera lo que indica `Retry-After` o el "try again in
  Xs" del cuerpo (máximo 90 s) y se reintenta hasta 5 veces. El ASR de Groq también espera en `429`.
- `400 json_validate_failed` (el modelo emitió JSON inválido): se reintenta hasta 2 veces.
- Valores fuera del vocabulario (p. ej. un tropo puesto en `beat`): se descartan **por ítem**; un lote
  que igual no valida se descarta y se sigue con el siguiente.

**Fix si se agotan los reintentos:** esperar un minuto y relanzar (el etiquetado es idempotente), bajar
`--batch`, o usar otro proveedor (`--provider gemini`, u `ollama` con permiso de GPU). Revisar el modelo
con `GROQ_LLM_MODEL` (por defecto `openai/gpt-oss-120b`; `llama-3.3-70b-versatile` ya no existe).

**Rollback:** no aplica; sin LLM quedan las etiquetas débiles y la plantilla de guion.

---

## Incident 10 · GPU lock tomado

**Síntoma:** el ASR local queda esperando "slot de GPU" y no avanza.

**Diagnóstico:** el lock es `%TEMP%\youlikeit-gpu.lock` y guarda el PID dueño.
```powershell
Get-Content "$env:TEMP\youlikeit-gpu.lock"        # "<pid> <etapa> <epoch>"
Get-Process -Id <pid>                               # ¿sigue vivo?
nvidia-smi
```

**Fix:** si el PID ya no existe, el lock se toma solo (detección por PID; antes había que esperar el
vencimiento por antigüedad, 8 h). Si el proceso existe pero está colgado, terminarlo; borrar el archivo
a mano solo si nada usa la GPU. Alternativa sin GPU: `--asr-backend groq`.

**Rollback:** no aplica.

---

## Incident 11 · Job del estudio colgado

**Síntoma:** un job sigue `running` sin progreso, o una lección quedó en `rendering`.

**Fix:** reiniciar el estudio (`.\scripts\ops\studio.ps1 -Stop` y luego `.\scripts\ops\studio.ps1`). Al
arrancar, los jobs `running` pasan a `error` (interrumpido) y las lecciones `rendering` vuelven a `draft`.
Volver a encolar desde la UI. Hay un solo worker: un job largo (indexar con red lenta) retrasa a los demás.

**Rollback:** no aplica; la cola vive en `studio_jobs` y sobrevive a reinicios.

---

## Incident 12 · El estudio responde 401 / 403 / 503

| Síntoma | Causa | Fix |
|---|---|---|
| `401` en todo | Falta `STUDIO_TOKEN`, o Vite arrancó antes de cambiar el `.env` | Revisar `.env` y reiniciar `studio.ps1` (Vite lee el `.env` al arrancar) |
| `403` "Origen no permitido" | Pedido desde otra página u otro puerto | Usar `http://127.0.0.1:5180`; si hace falta otro origen, `STUDIO_ALLOWED_ORIGINS` |
| `503` "La API del estudio no responde" (del proxy) | La API no está corriendo | `.\scripts\ops\studio.ps1`; logs en `%TEMP%\youlikeit-studio` |
| `503` al publicar o conectar | Falta `WEB_BASE_URL`/`STUDIO_API_KEY`, `client_secrets.json` o `TOKEN_ENC_KEY` | Completar el `.env` ([SETUP_CUENTAS.md](../../SETUP_CUENTAS.md)) |

---

## Incident 13 · Render o plan de lección falla

| Síntoma | Causa | Fix |
|---|---|---|
| `409` "No hay suficientes obras" al armar | Menos de 2 obras con ese tema y confianza | Indexar/etiquetar más obras o bajar `min_confidence` |
| Render en error por la voz | edge-tts necesita internet; si la voz falla, el render falla a propósito | Reintentar con red, o renderizar sin narración |
| Render en error por ffmpeg | Fuente TTF, filtros o un tramo inaccesible | Ver `error` del job; el directorio de trabajo se conserva en `media_cache/work/` si falla |
| `409` al editar o renderizar | La lección está `rendering` o `published` | Esperar el render; una publicada no se edita |

**Rollback:** un render fallido devuelve la lección a `draft`; la receta no se pierde.

---

## Incident 14 · Puente de TikTok falla

| Síntoma | Causa | Fix |
|---|---|---|
| `502` al listar cuentas con "HTTP 401" | `STUDIO_API_KEY` distinta en `.env` y Railway | Igualarlas |
| `502` con "HTTP 503" | El puente está apagado: key ausente o < 32 caracteres en Railway | Cargar una key válida en Railway |
| Job en error `reconnect_required` | TikTok rechazó el refresh token | Reconectar la cuenta en `/studio` del sitio |
| Job en error con un código de TikTok | p. ej. `spam_risk_too_many_pending_share` (5 borradores pendientes en 24 h) | Terminar o descartar borradores en la app y reintentar |
| "upload_url rechazada" | El puente devolvió un host que no es `*.tiktokapis.com` | Revisar el sitio (posible compromiso); no se subió nada |

---

## Incident 15 · Sitio público caído (Railway)

**Diagnóstico:**
```powershell
curl https://youlikeit-web-production.up.railway.app/healthz      # {"ok": true}
railway logs --service youlikeit-web
```

**Fix:** Railway reinicia ante fallas (hasta 5 veces, `web/railway.json`). Si el deploy nuevo rompe,
volver a desplegar la versión anterior desde el panel de Railway o con `railway up --no-gitignore` desde
el commit bueno ([web/README.md](../../web/README.md)). `web.db` vive en el volumen `/data` y no se
pierde con un redeploy.

**Rollback:** redeploy del commit anterior. Si se rotó `TOKEN_ENC_KEY`, las cuentas deben reconectarse.

---

## Escalado

- Incident acotado a un dominio → sub-tarea al dueño (ver [AGENT_TASKS.md](../agents/AGENT_TASKS.md)):
  media → [MEDIA_AGENT.md](../agents/MEDIA_AGENT.md), moments → [MOMENTS_AGENT.md](../agents/MOMENTS_AGENT.md).
- Cruza 2+ dominios → coordinar vía QA Agent.
- Secrets / accesos comprometidos → [SECURITY.md](SECURITY.md) primero.
