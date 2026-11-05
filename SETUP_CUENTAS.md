# Cuentas y API Keys necesarias

Todo es gratis. Ninguna pide tarjeta de crédito.

> **Verificar en cualquier momento:** `ylk doctor` (hace una llamada mínima a cada
> servicio y muestra OK / INVALID / MISSING sin imprimir valores). La página **Inicio** del estudio
> muestra además qué credenciales locales están presentes y para qué sirve cada una.
> Las keys viven en `.env` en la RAÍZ del repo (gitignored). Plantilla: `.env.example`.
> Las del sitio público viven en las **variables de Railway** (servicio `youlikeit-web`), no en el `.env`.

## Estado al 2026-11-04 y qué hacer (por prioridad para las lecciones)

| Credencial | Estado | Acción |
|---|---|---|
| `.env` raíz | OK | Editar ahí todo lo local. |
| `GROQ_API_KEY` | OK (usada en la corrida real del 2026-11-04: ASR + etiquetado) | — |
| `STUDIO_TOKEN` / `STUDIO_API_KEY` / `WEB_BASE_URL` | Configuradas el 2026-11-04 (el estudio se usó en la corrida real) | `STUDIO_API_KEY` debe ser **igual** en `.env` y en Railway. Revisar en **Inicio** del estudio. |
| Variables de Railway (`PUBLIC_BASE_URL`, `CONTACT_EMAIL`, `TOKEN_ENC_KEY`, `SESSION_SECRET`, `STUDIO_API_KEY`) | Cargadas | — |
| `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` | Cargadas en Railway (Sandbox), cuenta conectada; acceso limitado por `ALLOWED_TIKTOK_OPEN_IDS` | Keys del **Sandbox** de [developers.tiktok.com/apps](https://developers.tiktok.com/apps) → `railway variable set --service youlikeit-web ...`. Luego conectar la cuenta en `/studio` del sitio. Ver [TIKTOK_APP_REVIEW.md](docs/operations/TIKTOK_APP_REVIEW.md). |
| Google API key (`YOUTUBE_API_KEY` = `GEMINI_API_KEY`, misma key) | **INVÁLIDA** (`API_KEY_INVALID`). **No hace falta para subir videos** (eso usa OAuth) | Crear nueva en [Cloud Console → Credenciales](https://console.cloud.google.com/apis/credentials) (YouTube Data API v3) y otra en [AI Studio](https://aistudio.google.com/apikey) para Gemini (opcional: Groq ya cubre el LLM). |
| YouTube para el estudio (`client_secrets.json` + `TOKEN_ENC_KEY` local) | **Conectado** (2026-11-05): canal *Nico Flor*, cliente de escritorio del proyecto `dynamic-cove-436900-i9` (My First Project), app OAuth **En producción** | Sin auditoría de YouTube API Services las subidas quedan privadas. Si algo falla, `ylk doctor` → "YouTube del estudio". |
| Tokens OAuth legacy por persona (ex34) | MUERTOS (`invalid_grant`) | Solo para el producto anterior. |
| `TMDB_API_KEY` | OK, pero **filtrada en el historial de git** | Rotar en [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api). |
| OpenSubtitles / OMDb / Hugging Face (`HF_TOKEN`) | OK | Opcionales. |
| `TRAKT_CLIENT_ID` | INVÁLIDA (403) | Opcional; no la usan las lecciones. |
| GitHub Actions secrets | Ninguno configurado | Los tests de CI no necesitan keys. |
| Ollama | Instalado, sin modelos | `ollama pull qwen3:8b` solo si quieres LLM local (pide permiso de GPU; si no, `LLM_PROVIDER=groq`). |

---

## 1. Estudio local (obligatorio para producir)

Variables del `.env` raíz. Generar los tokens así (no compartirlos):

```powershell
python -c "import secrets;print(secrets.token_urlsafe(32))"                                  # STUDIO_TOKEN y STUDIO_API_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"     # TOKEN_ENC_KEY
```

| Variable | Para qué |
|---|---|
| `STUDIO_TOKEN` | Token de la API del estudio. Sin él `ylk studio` no arranca. |
| `WEB_BASE_URL` | `https://youlikeit-web-production.up.railway.app` (puente de TikTok). |
| `STUDIO_API_KEY` | Secreto compartido con Railway (mínimo 32 caracteres, mismo valor en ambos lados). |
| `TOKEN_ENC_KEY` | Cifra el token de YouTube en `tokens/youtube_studio.json.enc`. |

## 2. IA (recomendada)

- **Groq** ([console.groq.com/keys](https://console.groq.com/keys)) → `GROQ_API_KEY`. Habilita ASR por API
  (Whisper large-v3-turbo) y el LLM por API (`openai/gpt-oss-120b`). Plan gratis con límites por minuto;
  el código espera y reintenta los `429`.
- Alternativas: Gemini (`GEMINI_API_KEY`) u Ollama local. ASR local con `faster-whisper` necesita
  `requirements-gpu.txt` y la GPU.

## 3. TikTok (las keys viven en Railway)

- App en [developers.tiktok.com/apps](https://developers.tiktok.com/apps) con **Login Kit** y
  **Content Posting API**; scopes `user.info.basic` y `video.upload`.
- Redirect URI: `https://youlikeit-web-production.up.railway.app/auth/tiktok/callback`.
- `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` se cargan en Railway, no en el `.env`
  (la copia local solo sirve para que `ylk doctor` los revise).
- Sin auditoría: subida como **borrador** al inbox (la canción se elige en la app).
- Paso a paso de la revisión: [docs/operations/TIKTOK_APP_REVIEW.md](docs/operations/TIKTOK_APP_REVIEW.md).

## 4. YouTube (Google Cloud)

- **Ir a:** https://console.cloud.google.com/ → crear proyecto → habilitar **YouTube Data API v3**.
- **Credenciales:** OAuth 2.0 Client ID de tipo **Aplicación de escritorio** → descargar
  `client_secrets.json` a la raíz (o apuntar `GOOGLE_CLIENT_SECRETS`).
- **Pantalla de consentimiento:** "External" y luego **Publicar app (En producción)**. En "Testing" los
  refresh tokens vencen a los 7 días. Sin verificar, Google muestra una advertencia al autorizar; basta
  con continuar (uso propio).
- **Conectar:** estudio → Revisión → **Conectar YouTube** (redirect loopback a `127.0.0.1:8001`).
- **Límite:** `videos.insert` tiene cuota propia (~100 subidas/día por defecto).
- Publicar en **público** vía API requiere la auditoría de YouTube API Services; sin ella quedan privados.

## 5. Opcionales (producto anterior o enriquecimiento)

Las lecciones **no** necesitan subtítulos descargados: la transcripción sale del ASR (Groq o local).

| Servicio | Variable | Registro | Uso |
|---|---|---|---|
| OpenSubtitles | `OPENSUBTITLES_API_KEY`, `_USERNAME`, `_PASSWORD` | [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers) | Subtítulos .srt (20/día). Opcional |
| TMDB | `TMDB_API_KEY` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) | Metadatos de obras |
| SubDL | `SUBDL_API_KEY` | [subdl.com/panel/api](https://subdl.com/panel/api) | Alternativa de subtítulos |
| OMDb | `OMDB_API_KEY` | [omdbapi.com](https://www.omdbapi.com/apikey.aspx) | Ratings |
| Trakt | `TRAKT_CLIENT_ID` | [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications) | Trending |

---

## Después de crear las cuentas

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # y llenar las keys
python -m pip install -e .           # instala `ylk`
ylk doctor                           # estado de cada credencial, sin mostrar valores
.\scripts\ops\studio.ps1 -Check      # requisitos del estudio
.\scripts\ops\studio.ps1             # API + front en 127.0.0.1:5180
```

Por CLI, sin UI:

```powershell
ylk media ingest "Horror Express" --year 1972 --asr-backend groq   # buscar + registrar + indexar
ylk moments run 1 --provider groq                                    # detectar + etiquetar el asset 1
ylk moments find emotion:fear --min-works 3                          # momentos equivalentes entre obras
```

Runbook completo: [docs/operations/INDEX_A_FILM.md](docs/operations/INDEX_A_FILM.md).

### Producto anterior (legacy)

Los ejercicios `ex04`–`ex09` y los flujos programados del producto anterior se corren con
`python scripts/legacy/main.py exNN` y los `.ps1` de `scripts/ops/`
(`run-content-flow.ps1`, `schedule-flow-every-3-days.ps1`, `unschedule-flow.ps1`). No los usa el estudio.
