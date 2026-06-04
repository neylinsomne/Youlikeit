# Security & Secrets · YouLikeIt

> Inventario de secrets, dónde viven, cómo se rotan, y threat model.
> **No commitear secrets.** Si algo de esto aparece en `git log`, tratarlo como
> comprometido y rotar. Verifica el inventario real contra `.env`,
> `.gitignore` y los GitHub Secrets del repo; este doc es el contrato, no el dump.

## Inventario de secrets

| Secret | Para qué | Dónde vive | Obligatorio |
|---|---|---|---|
| `GEMINI_API_KEY` | LLM para `suggested_angle` en briefs | `.env` (local) + GitHub Secrets (CI) | Solo si se corre distill con LLM |
| `TRAKT_CLIENT_ID` | Fuente de release tracking (signals) | `.env` + GitHub Secrets | Opcional (fuente) |
| OAuth YouTube (client + refresh token) | Upload de Shorts (en pausa) | `tokens/` (local, gitignored) | Solo al reactivar uploads |
| OAuth TikTok | Inbox de TikTok (pendiente review) | `tokens/` (local, gitignored) | Solo al reactivar uploads |
| TMDB API key | Enriquecer metadata de películas | `.env` | Opcional |
| Plausible API key | Stats API (analytics) | `.env` / GitHub Secrets | Solo con analytics activo |

> La lista de secrets exactos es la que esté en `.env.example` + el panel de
> GitHub → Settings → Secrets. Mantener este cuadro sincronizado con ambos.

## Dónde vive cada cosa

- **Local dev:** `.env` (debe estar en `.gitignore`) + `tokens/` para OAuth.
- **CI (GitHub Actions):** GitHub Secrets, inyectados como env en los workflows
  (`refresh-signals.yml` usa `GEMINI_API_KEY`, `TRAKT_CLIENT_ID`).
- **Nunca:** en `data/shorts_pipeline.db`, en logs, ni en `raw_*` de tablas.

## Qué NO se commitea (verificar en `.gitignore`)

- [ ] `.env`
- [ ] `tokens/` (OAuth de YT/TT)
- [ ] `data/*.db` (puede contener URLs/metadata sensibles, no secrets pero sí ruido)
- [ ] cualquier `*credentials*.json` / `*client_secret*.json`

## Política de rotación

| Evento | Acción |
|---|---|
| Secret aparece en un commit | Rotar de inmediato en el proveedor + actualizar `.env` y GitHub Secrets + reescribir historia si es viable |
| Salida de un colaborador | Rotar OAuth tokens y API keys compartidas |
| Rotación periódica | API keys cada 90 días; refresh tokens OAuth según expiración del proveedor |

## Threat model (amenaza → mitigación)

| Amenaza | Mitigación |
|---|---|
| Leak de API key en repo/log | `.gitignore` estricto; secrets solo por env; este doc; rotación al detectar |
| Refresh token OAuth robado | `tokens/` gitignored y fuera de backups públicos; scope mínimo; rotación |
| IP-ban / rate-limit de un scraper | `scraper_health` monitorea fail_rate; backoff; fuentes fail-soft (no tumban el pipeline) |
| Supply chain (dep maliciosa) | No introducir deps sin justificar en PR (anti-patrón en AGENT_TASKS); pin de versiones en `requirements*.txt` |
| PII en analítica | Plausible sin IPs/UA/PII; `plausible_*.raw_props` no guarda PII (GDPR end-to-end) |
| Secret expuesto en CI logs | No `echo` de secrets; GitHub enmascara secrets registrados; revisar `permissions:` del workflow |

## Relacionado

- [RUNBOOK.md § Incident 4 (GHA cron rojo)](RUNBOOK.md) — secrets faltantes/rotados.
- [ANALYTICS_AGENT.md](../agents/ANALYTICS_AGENT.md) — privacidad de Plausible.
- [SETUP_CUENTAS.md](../../SETUP_CUENTAS.md) — alta de cuentas y obtención de keys.
