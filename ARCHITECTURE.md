# YouLikeIt — Arquitectura del Pipeline

## Vision

Canal educativo de YouTube Shorts que usa escenas de peliculas, anime y manga
para ensenar lecciones de vida. Pipeline 100% automatizado: descubre contenido,
genera Shorts con narracion reflexiva, sube, analiza metricas, y mejora solo.

---

## Stack Tecnologico

| Capa | Tecnologia | Proposito |
|------|-----------|-----------|
| Runtime | Docker + NVIDIA GPU (RTX 5060) | Contenedores con aceleracion GPU |
| Lenguaje | Python 3.11 | Todo el pipeline |
| Base de datos | SQLite + ChromaDB | Estructurada + busqueda semantica |
| LLM | Gemini Flash (gratis) | Clasificacion, guiones, reflexiones |
| TTS | Fish Speech S1-Mini (local) | Narracion con voice cloning |
| Video | FFmpeg + NVENC | Edicion y codificacion GPU |
| OCR | EasyOCR + OpenCV | Lectura de paneles de manga |
| Frontend | FastAPI + htmx | Dashboard y gestion |
| CI/CD | GitHub Actions | Automatizacion diaria |
| Analytics | scipy + sklearn | ANOVA, Random Forest, DBSCAN |
| Trends | PyTrends + TikTok scraper | Tendencias en tiempo real |

---

## Verticales de Contenido

### 1. Peliculas (ex04-ex12)
```
TMDB + Wikiquote + OMDb + Trakt
    |
    v
Descubrir peliculas trending + frases iconicas
    |
    v
OpenSubtitles/Whisper -> timestamps exactos
    |
    v
ChromaDB -> busqueda semantica por tema
    |
    v
FFmpeg (GPU) -> cortar clip 9:16 + subtitulos
    |
    v
Gemini -> guion de narracion reflexiva
    |
    v
Fish Speech -> TTS con voice cloning
    |
    v
YouTube Data API -> subir Short
```
**Estado**: Pausado hasta tener fuente de video (Real-Debrid ~$3/mes)

### 2. Manga / Anime / Comics (ex36-ex39)
```
Jikan + AniList + Animechan (sin API key)
    |
    v
Descubrir trending manga/anime + quotes
    |
    v
Fandom Wiki -> scrape capitulos + panels iconicos
    |
    v
OpenCV -> detectar paneles individuales
    |
    v
EasyOCR -> leer texto de globos de dialogo
    |
    v
rapidfuzz -> match OCR con quotes de la BD
    |
    v
FFmpeg -> Ken Burns (zoom/pan panel a panel)
    |   Pausa + narracion en panels con match
    v
Short de 30-60s listo para subir
```
**Estado**: Operativo. Pipeline completo funciona.

### 3. Series (futuro)
Mismo flujo que peliculas, iterado por episodios.

---

## Ejercicios por Fase

### Fase 0: Infraestructura (ex00, ex34)
| Ejercicio | Funcion |
|-----------|---------|
| ex00 | Verificacion de conexiones y API keys |
| ex34 | OAuth manager (YouTube upload + analytics scopes) |

### Fase 1: Descubrimiento + Preparacion (ex04-ex06, ex10)
| Ejercicio | Funcion |
|-----------|---------|
| ex04 | Descubrir peliculas (TMDB + Wikiquote + OMDb + Trakt) |
| ex05 | Descargar subtitulos (OpenSubtitles -> SubDL -> Whisper) |
| ex06 | Matching frases <-> timestamps (rapidfuzz + ChromaDB) |
| ex10 | Clasificar frases con LLM (categoria, emocion, viral score) |

### Fase 2: Produccion de Shorts (ex07-ex09, ex11, ex16-ex18)
| Ejercicio | Funcion |
|-----------|---------|
| ex07 | Buscar escenas por tema (ChromaDB semantico) |
| ex08 | Growth pack (hashtags + canciones trending + checklist) |
| ex09 | Curar y agrupar clips (ranking + pre-edicion) |
| ex11 | Cortar video con FFmpeg (GPU NVENC + subtitulos) |
| ex16 | Edicion Shotcut (MLT XML alternativo) |
| ex17 | Estrategia de publicacion (PyTrends + horario optimo) |
| ex18 | Narracion reflexiva (Gemini guion + Fish Speech TTS) |

### Fase 3: Analytics + Aprendizaje (ex19-ex27, ex31-ex33)
| Ejercicio | Funcion |
|-----------|---------|
| ex19 | Analytics de videos propios |
| ex24 | Retencion segundo a segundo (cliffs, hooks, plateaus) |
| ex25 | Random Forest: que senales importan |
| ex26 | Demographics + segmentacion DBSCAN |
| ex27 | Optimizacion geografica (ANOVA por pais) |
| ex31 | Taxonomia pedagogica (tipo de aprendizaje) |
| ex32 | Rendimiento por tipo pedagogico (scipy ANOVA + Cohen's d) |
| ex33 | Planificador de curriculum (diversidad + trends) |
| ex21 | Auto-ajuste de pesos (ciclo de aprendizaje) |
| ex22 | A/B testing automatizado |
| ex23 | Analisis estadistico + metas |

### Fase 4: Plataforma (ex28-ex30, ex35)
| Ejercicio | Funcion |
|-----------|---------|
| ex28 | Dashboard analitico (htmx + Canvas JS) |
| ex29 | API REST unificada (FastAPI + auth + WebSocket) |
| ex30 | Frontend de gestion multi-pagina |
| ex35 | Exportar BD a CSV/JSON + backup |

### Fase 5: Manga/Anime (ex36-ex39)
| Ejercicio | Funcion |
|-----------|---------|
| ex36 | Descubrir manga/anime trending (Jikan + AniList + Animechan) |
| ex37 | Clasificar quotes manga (Gemini + heuristico) |
| ex38 | Panel detection + OCR + Ken Burns video |
| ex39 | Scraper Fandom Wiki para panels iconicos |

### Auxiliares
| Ejercicio | Funcion |
|-----------|---------|
| ex01 | Busqueda y captura en YouTube (Playwright) |
| ex02 | Extraccion de metadata (yt-dlp) |
| ex03 | Monitoreo RSS de canal |
| ex12 | Subir Short a YouTube |
| ex13 | Grafo de tendencias |
| ex14 | Edicion DaVinci Resolve |
| ex15 | Dashboard de revision |
| ex20 | Analisis de competencia |

---

## Base de Datos

### SQLite: `data/shorts_pipeline.db`
```
movies          -> peliculas descubiertas (TMDB)
quotes          -> frases con timestamps + clasificacion
subtitles       -> archivos .srt descargados
shorts          -> Shorts generados
analytics       -> metricas de YouTube
manga_series    -> anime/manga trending
manga_quotes    -> frases de anime/manga
clip_library    -> biblioteca reutilizable de clips
short_clips     -> que clips uso cada Short
pipeline_runs   -> historial de ejecuciones
retention_curves -> retencion segundo a segundo
audience_demographics -> segmentos de audiencia
curriculum_plan -> plan de contenido diversificado
knowledge_base  -> insights aprendidos
ab_tests        -> tests A/B activos
goals           -> metas del canal
audit_log       -> auditoria completa
```

### ChromaDB: `data/chroma/`
Embeddings semanticos para busqueda por similitud:
- Coleccion `quotes`: frases de peliculas
- Coleccion `clip_library`: clips reutilizables
- Permite: "busca escenas de villanos oscuros" -> match semantico

---

## Reutilizacion de Clips

```
clip_library (SQLite)              ChromaDB (embeddings)
+-- clip_id, source_type           +-- vector de significado
+-- tags, category, themes         +-- busqueda semantica
+-- times_used
+-- chroma_id ─────────────────────> vinculo

short_clips (junction)
+-- short_id: "Villanos" ──> clip: Griffith, clip: Doflamingo
+-- short_id: "Historia Oscura" ──> clip: Griffith (REUSADO)
                                     clip: Guts (nuevo)
```

El sistema rastrea que clips se usaron en que Shorts.
Cuando creas un nuevo Short sobre "historia oscura",
ChromaDB busca clips semanticamente similares y encuentra
el de Griffith que ya usaste en "Villanos".

---

## Docker Services

```
docker-compose.yml
+-- ytlab          (pipeline principal, GPU)      localhost:----
+-- dashboard      (ex28: analytics htmx)         localhost:8080
+-- api            (ex29: REST API + WebSocket)    localhost:8001
+-- frontend       (ex30: gestion multi-pagina)    localhost:8002/app
+-- qbittorrent    (descarga peliculas)            localhost:8090
+-- fish-speech    (TTS, descomentado cuando listo) localhost:8080
```

Todos los servicios comparten `env_file: .env` para las API keys.

---

## API REST (ex29)

### Endpoints principales
```
POST /api/auth/token        -> obtener token
GET  /api/movies            -> listar peliculas
GET  /api/quotes            -> listar frases (filtros: category, emotion)
GET  /api/shorts            -> listar Shorts
GET  /api/analytics         -> metricas
GET  /api/manga/series      -> series manga/anime
GET  /api/manga/quotes      -> quotes manga (filtros: category)
GET  /api/clips             -> biblioteca de clips
GET  /api/clips/search?q=   -> busqueda semantica ChromaDB
GET  /api/clips/{id}/usage  -> en que Shorts se uso
POST /api/pipeline/run      -> disparar pipeline desde frontend
GET  /api/pipeline/runs     -> historial de ejecuciones
GET  /api/status            -> estado general de la BD
GET  /api/curriculum        -> plan de contenido
GET  /api/goals             -> metas del canal
GET  /api/ab-tests          -> tests A/B activos
WS   /ws                    -> progreso ETL en tiempo real
```

---

## Automatizacion

### GitHub Action (`.github/workflows/pipeline.yml`)
- Corre diario a las 1am Colombia (6am UTC)
- Salta los dias 15-18 automaticamente
- Lun-Vie: pipeline manga | Sab-Dom: ciclo de aprendizaje
- Disparo manual desde GitHub con parametros

### Scripts locales
```powershell
.\run.ps1 manga                              # pipeline completo
.\run.ps1 manga -SeriesTitle "Berserk"       # con wiki scrape
.\run.ps1 manga -SeriesTitle "One Piece" -Source "page.jpg"  # con OCR
.\run.ps1 movies -Query "villain monologue"  # pipeline peliculas
.\run.ps1 learn                              # ciclo de aprendizaje
.\run.ps1 status                             # estado de la BD
.\run.ps1 dashboard                          # levantar todos los servicios
.\run.ps1 upload -Video "short.mp4" -Title "Griffith's Truth"
```

---

## Flujo de Musica

El video se sube SIN musica mezclada. La cancion se selecciona
EN LA PLATAFORMA (YouTube/TikTok) al momento de publicar.

Beneficios:
1. El Short aparece cuando buscan esa cancion
2. Se muestra como recuadro clickeable en la descripcion
3. ex08 sugiere canciones trending que matchean con los hashtags
4. Volumen recomendado: voz al 80-100%, musica al 15-25%

```
ex08 Growth Pack
+-- TikTok Creative Center -> canciones trending
+-- Keywords del contenido -> ranking por relevancia
+-- Song-hashtag graph -> que cancion cruza con que hashtags
+-- Resultado: "usar esta cancion en la plataforma"
```

---

## LLM Provider Cascade

```
1. Gemini Flash (gratis, 1M tokens contexto)
   +-- Ideal: system prompt completo con todo el contexto
   +-- 10 req/min, 250 req/dia
   |
   v (si falla)
2. Groq (gratis, 128K tokens)
   +-- Rapido, buen JSON
   +-- 30 req/min
   |
   v (si falla)
3. Heuristico (sin internet)
   +-- Reglas basadas en keywords
   +-- Siempre disponible
```

Cada generacion lleva context del proyecto:
- Manifiesto del canal (vision, audiencia, tono)
- Insights aprendidos de analytics
- Metricas actuales vs metas
- Curriculum plan vigente

---

## Ciclo de Mejora Continua

```
Publicar Short
    |
    v
YouTube Analytics API (ex19, ex24)
    |
    v
Retencion segundo a segundo -> donde pierdes audiencia?
    |
    v
Random Forest (ex25) -> que senales importan?
    |
    v
DBSCAN (ex26) -> que segmentos de audiencia tienes?
    |
    v
ANOVA por tipo pedagogico (ex32) -> que lecciones funcionan?
    |
    v
Curriculum Planner (ex33) -> que publicar proximo?
    |
    v
Auto-ajuste (ex21) -> ajustar pesos automaticamente
    |
    v
Publicar Short mejorado
```

---

## APIs Externas (todas gratis)

| API | Limite | Uso |
|-----|--------|-----|
| TMDB | Sin limite real | Descubrir peliculas |
| Wikiquote | Sin limite | Extraer frases |
| OMDb | 1,000 req/dia | Ratings IMDb/RT |
| Trakt | 1,000 req/5min | Trending real-time |
| OpenSubtitles | 20 descargas/dia | Subtitulos .srt |
| Gemini Flash | 250 req/dia | Clasificacion, guiones |
| Jikan (MAL) | 3 req/s | Manga/anime trending |
| AniList GraphQL | Sin limite | Manga/anime datos |
| Animechan | Sin limite | Quotes anime |
| Fandom Wiki | Sin limite | Panels iconicos |
| PyTrends | ~10 req/min | Google Trends |
| TikTok Creative | scraping | Canciones trending |
| YouTube Data v3 | 10,000 units/dia | Stats, upload |
| YouTube Analytics | 200 req/dia | Retencion, demographics |

---

## Seguridad

- API keys en `.env` (nunca en git)
- `.env.example` con placeholders para referencia
- OAuth tokens en `data/youtube_oauth_token.json` (gitignored)
- API REST con auth por token (Bearer)
- Roles: admin, reviewer, agent
- Audit log completo (quien hizo que, cuando)
- Docker: env_file en todos los servicios

---

## Estado Actual (2026-03-22)

| Componente | Estado |
|-----------|--------|
| Pipeline peliculas (ex04-ex12) | Funcional, falta fuente de video |
| Pipeline manga (ex36-ex39) | Operativo |
| Analytics (ex19-ex27) | Funcional (necesita datos reales) |
| Aprendizaje (ex31-ex33) | Funcional |
| Dashboard (ex28) | Corriendo en Docker |
| API REST (ex29) | Corriendo en Docker |
| Frontend (ex30) | Corriendo en Docker |
| GitHub Action | Configurada, lista para activar |
| Fish Speech TTS | Pendiente (voice cloning) |
| qBittorrent | Pendiente (ISP bloquea, necesita VPN) |

**BD**: 5 peliculas, 130 quotes (30 con timestamps), 15 series manga, 20 quotes manga
