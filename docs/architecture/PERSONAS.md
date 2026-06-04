# YouLikeIt — Arquitectura Multi-Persona

> **Nota (2026-06-02):** movido desde el root del repo. El flujo end-to-end
> canónico vive en [MLOPS_FLOW.md](MLOPS_FLOW.md); la fuente de verdad de los
> datos de persona es `src/apps/content/personas.py` + `tokens/personas.json`. Aquí
> queda el **diseño narrativo** (knowledge graph, rationale multi-persona).

> Sistema de producción de contenido con múltiples personalidades,
> knowledge graph local, y pipelines desacoplados.

---

## 1. Visión

No somos un bot que resume películas. Somos un sistema de **análisis cultural**
que cruza referencias entre cine, manga, comics, filosofía y cultura pop.

Cada **persona** es una voz con una perspectiva única sobre el mismo contenido.
El contenido base (knowledge graph) es compartido; el filtro y estilo son únicos por persona.

---

## 2. Personas Definidas

```
┌─────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE GRAPH (compartido)              │
│  Movies · Comics · Series · Filosofía · Cultura Pop · News  │
└──────────┬──────────────┬──────────────┬────────────────────┘
           │              │              │
     ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
     │ PERSONA 1  │ │ PERSONA 2  │ │ PERSONA 3  │
     │ Deep Mind  │ │ Cinephile  │ │ Pop Oracle │
     │            │ │            │ │            │
     │ Voz: grave │ │ Voz: ener- │ │ Voz: feme- │
     │ reflexiva  │ │ gética     │ │ nina dinámi│
     │            │ │            │ │ ca         │
     │ Cruza con: │ │ Cruza con: │ │ Cruza con: │
     │ filosofía, │ │ directores,│ │ farandula, │
     │ películas  │ │ filmografía│ │ noticias,  │
     │ profundas  │ │ comparativa│ │ famosos    │
     └─────┬──────┘ └─────┬──────┘ └──────┬─────┘
           │              │               │
     ┌─────▼──────────────▼───────────────▼─────┐
     │           RENDER PIPELINE                 │
     │  Fish Speech (endpoint por persona)       │
     │  FFmpeg + Subtítulos + Metadata           │
     │  Upload (YouTube/TikTok/Instagram)        │
     └───────────────────────────────────────────┘
```

### Persona 1: "Deep Mind" (Masculina profunda)
- **Fish Speech seed/ref**: voice_deep_reflective.wav (P1_seg0)
- **Prompt template**: Conecta con filosofía (Nietzsche, Camus), películas de Tarkovsky, Kubrick, Villeneuve
- **Estilo edición**: Pausado, zoom lentos, colores desaturados
- **Subtítulos**: Blancos, fuente serif, aparición suave
- **Ejemplo**: "La traición de Griffith no es solo narrativa. Es el eterno retorno de Nietzsche materializado en tinta..."

### Persona 2: "Cinephile" (Masculina energética)
- **Fish Speech seed/ref**: voice_dramatic_epic.wav (P2_seg3)
- **Prompt template**: Conecta directores (Miyazaki↔Miura, Nolan↔Urasawa), compara mundos creativos
- **Estilo edición**: Dinámico, cortes rápidos, colores vivos
- **Subtítulos**: Amarillos, fuente bold, pop-in
- **Ejemplo**: "Miura hizo con Berserk lo que Kubrick hizo con 2001 — redefinió las reglas de su medio..."

### Persona 3: "Pop Oracle" (Femenina dinámica)
- **Fish Speech ref**: TBD (voz femenina, pendiente de selección)
- **Prompt template**: Conecta con celebridades, trends, memes, noticias
- **Estilo edición**: Rápido, emojis sutiles, colores neón
- **Subtítulos**: Rosa/cyan, fuente moderna, word-by-word
- **Ejemplo**: "Si Griffith fuera famoso hoy, Twitter lo cancelaría en 3 minutos..."

---

## 3. Knowledge Graph (PostgreSQL + pgvector)

### Por qué PostgreSQL + pgvector
- SQLite funciona para un canal. Para 3+ personas produciendo en paralelo, necesitas concurrencia real
- pgvector permite búsqueda semántica sin ChromaDB separado
- PostGIS (mismo PostgreSQL) si en el futuro quieres geo-analytics
- Gratis, self-hosted en Docker

### Schema

```sql
-- === CONTENIDO BASE ===

CREATE TABLE works (
    id SERIAL PRIMARY KEY,
    type VARCHAR(20) NOT NULL,  -- 'movie', 'manga', 'comic', 'series', 'book'
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    creator TEXT,               -- director, mangaka, author
    genre TEXT[],
    themes TEXT[],               -- ['betrayal', 'redemption', 'power']
    external_ids JSONB,          -- {tmdb: 123, imdb: 'tt123', mal: 456, mangadex: 'uuid'}
    popularity REAL DEFAULT 0,
    overview TEXT,
    embedding VECTOR(384),       -- semantic embedding del overview
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE quotes (
    id SERIAL PRIMARY KEY,
    work_id INTEGER REFERENCES works(id),
    text TEXT NOT NULL,
    character_name TEXT,
    chapter_episode TEXT,        -- 'Ch.83', 'S02E05'
    timestamp_ms INTEGER,
    category TEXT,               -- villain, motivational, philosophical
    emotion TEXT,                -- dark, epic, tragic, hopeful
    viral_score INTEGER,
    embedding VECTOR(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- === CROSS-REFERENCES (el diferenciador) ===

CREATE TABLE cross_references (
    id SERIAL PRIMARY KEY,
    source_work_id INTEGER REFERENCES works(id),
    target_work_id INTEGER REFERENCES works(id),
    reference_type TEXT NOT NULL, -- 'thematic', 'director', 'actor', 'cultural', 'philosophical'
    description TEXT,             -- "Both explore the corruption of power"
    strength REAL DEFAULT 0.5,    -- 0-1 relevance score
    persona_affinity TEXT[],      -- ['deep_mind', 'cinephile'] — qué personas usarían esta ref
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE cultural_events (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT,                    -- 'news', 'celebrity', 'trend', 'meme', 'award'
    description TEXT,
    date DATE,
    related_work_ids INTEGER[],   -- works mencionados
    related_people TEXT[],        -- actores, directores, celebridades
    source_url TEXT,
    embedding VECTOR(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- === PERSONAS ===

CREATE TABLE personas (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,     -- 'deep_mind', 'cinephile', 'pop_oracle'
    display_name TEXT,
    voice_ref_path TEXT,           -- path al .wav de referencia
    fish_speech_params JSONB,      -- {temperature, top_p, seed, ...}
    subtitle_style JSONB,          -- {font, color, animation}
    edit_style JSONB,              -- {pace, color_grade, transitions}
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prompts versionados por persona (evolucionan con el aprendizaje)
CREATE TABLE persona_prompts (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER REFERENCES personas(id),
    prompt_type TEXT NOT NULL,     -- 'system', 'narration', 'cross_ref', 'intro', 'outro', 'analysis'
    version INTEGER DEFAULT 1,
    content TEXT NOT NULL,         -- el prompt completo
    variables TEXT[],              -- ['{{work_title}}', '{{themes}}', '{{cross_refs}}']
    active BOOLEAN DEFAULT true,   -- solo 1 activo por (persona_id, prompt_type)
    performance_score REAL,        -- avg retention de Shorts que usaron este prompt
    a_b_test_id INTEGER,           -- si está en A/B test
    notes TEXT,                    -- por qué se cambió
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Feed de información nueva por persona (contexto que se acumula)
CREATE TABLE persona_knowledge (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER REFERENCES personas(id),
    knowledge_type TEXT NOT NULL,  -- 'reference', 'insight', 'style_note', 'audience_signal', 'trend'
    content TEXT NOT NULL,         -- el conocimiento en sí
    source TEXT,                   -- 'analytics', 'manual', 'gemini', 'trend_api', 'a_b_test'
    relevance_score REAL DEFAULT 1.0,  -- decae con el tiempo si no se valida
    expires_at TIMESTAMPTZ,        -- NULL = permanente, fecha = temporal (trends)
    used_count INTEGER DEFAULT 0,  -- cuántas veces se usó en producción
    embedding VECTOR(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reglas de comportamiento por persona (lo que puede/no puede hacer)
CREATE TABLE persona_rules (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER REFERENCES personas(id),
    rule_type TEXT NOT NULL,       -- 'must', 'never', 'prefer', 'avoid'
    rule TEXT NOT NULL,            -- "Siempre citar al director cuando menciones una película"
    priority INTEGER DEFAULT 5,    -- 1-10, 10 = inquebrantable
    source TEXT,                   -- 'manual', 'a_b_test', 'audience_feedback'
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Historial de interacciones del pipeline con cada persona
CREATE TABLE persona_runs (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER REFERENCES personas(id),
    short_id INTEGER REFERENCES shorts(id),
    prompt_id INTEGER REFERENCES persona_prompts(id),
    knowledge_ids INTEGER[],       -- qué knowledge se inyectó
    llm_input TEXT,                -- prompt completo enviado a Gemini
    llm_output TEXT,               -- respuesta completa de Gemini
    tokens_used INTEGER,
    duration_ms INTEGER,
    quality_score REAL,            -- auto-eval o manual
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- === PRODUCCIÓN ===

CREATE TABLE shorts (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER REFERENCES personas(id),
    title TEXT,
    work_ids INTEGER[],           -- works usados en este Short
    cross_ref_ids INTEGER[],      -- cross-references usados
    narration_script JSONB,       -- {intro, segments[], outro}
    voice TEXT,                   -- 'fish_speech', 'edge_tts'
    output_file TEXT,
    subtitles_file TEXT,
    status TEXT DEFAULT 'draft',  -- draft, rendered, pending_review, approved, uploaded, rejected
    youtube_id TEXT,
    tiktok_id TEXT,
    instagram_id TEXT,
    metadata JSONB,               -- {hashtags, song, description, category}
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE analytics (
    id SERIAL PRIMARY KEY,
    short_id INTEGER REFERENCES shorts(id),
    platform TEXT,                -- 'youtube', 'tiktok', 'instagram'
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    avg_watch_time_s REAL,
    retention_curve JSONB,        -- [{second: 1, pct: 100}, {second: 5, pct: 80}, ...]
    demographics JSONB,           -- {age_groups: {...}, countries: {...}}
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

-- === APRENDIZAJE ===

CREATE TABLE ab_tests (
    id SERIAL PRIMARY KEY,
    short_a_id INTEGER REFERENCES shorts(id),
    short_b_id INTEGER REFERENCES shorts(id),
    variable TEXT,                -- 'voice', 'subtitle_style', 'intro_type', 'emotion'
    started_at TIMESTAMPTZ DEFAULT NOW(),
    concluded_at TIMESTAMPTZ,
    winner TEXT,                  -- 'a', 'b', 'inconclusive'
    metrics JSONB                 -- {retention_a, retention_b, engagement_a, engagement_b}
);

-- === CACHE ===

CREATE TABLE trending_songs (
    id SERIAL PRIMARY KEY,
    title TEXT, artist TEXT, youtube_url TEXT,
    views TEXT, thumbnail TEXT, duration TEXT,
    region TEXT DEFAULT 'US',
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

-- === INDEXES ===

CREATE INDEX idx_works_embedding ON works USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_quotes_embedding ON quotes USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_cultural_embedding ON cultural_events USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_cross_refs_source ON cross_references(source_work_id);
CREATE INDEX idx_cross_refs_target ON cross_references(target_work_id);
CREATE INDEX idx_shorts_persona ON shorts(persona_id);
CREATE INDEX idx_analytics_short ON analytics(short_id);
```

---

## 4. Pipelines Desacoplados

Cada pipeline es independiente. Se comunican via la BD, no entre sí.
Pueden correr en paralelo sin conflictos.

```
PIPELINE 1: DISCOVERY (corre 1x/día)
  ├── Buscar trending en AniList, TMDB, Trakt, Google Trends
  ├── Insertar/actualizar works en la BD
  ├── Generar embeddings con sentence-transformers (local, gratis)
  ├── Detectar cross-references automáticamente:
  │   "¿Qué works comparten temas similares?" (cosine similarity)
  └── Output: works y cross_references actualizados

PIPELINE 2: CONTENT PLANNING (corre 1x/día, después de Discovery)
  ├── Para cada persona activa:
  │   ├── Consultar works trending + cross-refs relevantes a su perfil
  │   ├── Score = f(trending, cross_refs, diversidad, misión)
  │   ├── Seleccionar top 3 contenidos para producir
  │   └── Generar narration_script con Gemini (usando prompt_template de la persona)
  └── Output: shorts en status='draft' con script listo

PIPELINE 3: PRODUCTION (corre bajo demanda o después de Planning)
  ├── Para cada short en status='draft':
  │   ├── Descargar assets (páginas manga, clips)
  │   ├── Generar audio con Fish Speech (endpoint dedicado por persona)
  │   ├── Generar video (camera scroll, Ken Burns)
  │   ├── Generar + quemar subtítulos (estilo por persona)
  │   ├── Validar Fair Use
  │   └── Mover a status='pending_review'
  └── Output: videos renderizados en el frontend Review

PIPELINE 4: UPLOAD (manual o automático después de Review)
  ├── Para cada short en status='approved':
  │   ├── Subir a YouTube (con metadata de la persona)
  │   ├── Subir a TikTok (adaptado)
  │   ├── Subir a Instagram Reels (adaptado)
  │   └── Mover a status='uploaded'
  └── Output: IDs de cada plataforma guardados

PIPELINE 5: ANALYTICS (corre 1x/día)
  ├── Para cada short en status='uploaded':
  │   ├── YouTube Analytics API → retención, demographics
  │   ├── TikTok Analytics (si disponible)
  │   ├── Detectar punto de abandono (IQR)
  │   ├── Cruzar abandono con demographics
  │   └── Alimentar modelo de aprendizaje
  └── Output: analytics actualizados, modelo re-entrenado

PIPELINE 6: LEARNING (corre 1x/semana)
  ├── Random Forest: features → retención predicha
  ├── A/B test results → ajustar parámetros de personas
  ├── Identificar: qué persona performa mejor, qué cross-refs funcionan
  ├── Ajustar prompt_templates, edit_styles, subtitle_styles
  └── Output: personas evolucionadas
```

---

## 5. Fish Speech — Endpoints por Persona

Para que las voces no se crucen durante generación paralela,
cada persona tiene su propio endpoint o queue.

### Opción A: Un solo container, cola por persona (simple)
```python
# API wrapper que enqueue requests por persona
POST /api/tts/deep_mind     → cola persona_1 → Fish Speech
POST /api/tts/cinephile     → cola persona_2 → Fish Speech
POST /api/tts/pop_oracle    → cola persona_3 → Fish Speech

# Cada cola procesa secuencialmente pero las colas son independientes
# Fish Speech procesa 1 request a la vez (GPU bound)
# Las colas se procesan round-robin o por prioridad
```

### Opción B: Múltiples containers (escalable, más VRAM)
```yaml
# docker-compose.yml
fish-speech-1:
  image: youlikeit-fish:latest
  container_name: yt-fish-deep-mind
  ports: ["7861:7860"]
  # Usa voice_deep_reflective.wav como referencia default

fish-speech-2:
  image: youlikeit-fish:latest
  container_name: yt-fish-cinephile
  ports: ["7862:7860"]
  # Usa voice_dramatic_epic.wav como referencia default
```

### Recomendación: Opción A por ahora
- Tu RTX 5060 tiene 16GB VRAM, Fish Speech usa ~1.5GB
- Un container alcanza para producción secuencial
- La cola por persona evita que se mezclen voces
- Cuando escales a 3 personas produciendo diario, cambia a Opción B

---

## 6. Docker Compose Target

```yaml
services:
  # PostgreSQL + pgvector (reemplaza SQLite)
  db:
    image: pgvector/pgvector:pg17
    container_name: yt-db
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: youlikeit
      POSTGRES_USER: yli
      POSTGRES_PASSWORD: ${DB_PASSWORD:-youlikeit_dev}
    volumes:
      - pgdata:/var/lib/postgresql/data

  # Pipeline worker (GPU)
  ytlab:
    build: .
    image: youlikeit:latest
    depends_on: [db]
    # ... (existing config)

  # API REST
  api:
    image: youlikeit:latest
    depends_on: [db]
    # ... (existing config, connects to PostgreSQL)

  # Fish Speech TTS (GPU)
  fish-speech:
    build: {context: ., dockerfile: Dockerfile.fish}
    # ... (existing config)

  # Frontend React
  frontend:
    # ... (existing config)

  # Redis (colas por persona, cache, WebSocket pub/sub)
  redis:
    image: redis:7-alpine
    container_name: yt-redis
    ports: ["6379:6379"]

volumes:
  pgdata:
  fish-speech-models:
```

---

## 7. Migración SQLite → PostgreSQL

### Cuándo migrar
- Cuando tengas 2+ personas produciendo contenido
- O cuando los vectores en ChromaDB superen 10K entries
- O cuando necesites concurrent writes (múltiples pipelines en paralelo)

### Cómo migrar
1. Crear schema en PostgreSQL (el SQL de arriba)
2. Script de migración: leer SQLite → insertar en PostgreSQL
3. Actualizar db.py para usar psycopg2 en vez de sqlite3
4. Generar embeddings con sentence-transformers para works/quotes existentes
5. ChromaDB se reemplaza por pgvector (misma funcionalidad, menos containers)

### Mientras tanto (SQLite funciona para 1 persona)
- No migrar hasta que sea necesario
- El schema de SQLite actual cubre Persona 1 completamente
- Agregar la tabla `personas` a SQLite es trivial

---

## 8. Buenas Prácticas

### Producción
- [ ] Nunca generar audio de 2 personas al mismo tiempo en la misma GPU
- [ ] Cola FIFO por persona: intro → seg0 → seg1 → ... → outro (secuencial)
- [ ] Validar Fair Use ANTES de mover a pending_review
- [ ] Cada Short debe tener: narración + subtítulos + ≤5 paneles + comentario original
- [ ] Guardar el seed/params de Fish Speech que generó cada audio (reproducibilidad)

### Datos
- [ ] Embeddings se generan 1 vez y se cachean (no regenerar en cada query)
- [ ] Cross-references: auto-detectar por similitud + curar manualmente las mejores
- [ ] Trending songs: cache 24h, no pedir API a cada request
- [ ] Analytics: pull 1x/día, no en tiempo real (ahorra quota de YouTube API)

### Escalabilidad
- [ ] SQLite → PostgreSQL cuando haya 2+ personas activas
- [ ] ChromaDB → pgvector (elimina un container)
- [ ] Redis para colas + WebSocket pub/sub + cache de sesión
- [ ] GitHub Action por persona (workflows separados, no se bloquean entre sí)

### Seguridad
- [ ] API keys en .env, NUNCA en el código
- [ ] OAuth tokens en data/, excluidos de git
- [ ] Rate limiting en la API REST (FastAPI middleware)
- [ ] Validación de input en todos los endpoints

---

## 9. Próximos Pasos (Prioridad)

1. **Completar Persona 1** (Deep Mind) — ya casi lista
   - Regenerar Berserk con voz consistente ✅
   - Subtítulos animados ✅
   - Upload a YouTube ✅
   - Publicar primeros 3 Shorts

2. **Knowledge Graph básico** — tabla cross_references en SQLite
   - Agregar manualmente 20-30 cross-refs para Berserk
   - Template de narración que usa los cross-refs

3. **Persona 2** (Cinephile) — cuando Persona 1 publique 10 videos
   - Seleccionar voz (P2_seg3)
   - Crear prompt template diferente
   - Probar con el mismo contenido pero perspectiva diferente

4. **Migrar a PostgreSQL** — cuando haya 2 personas activas
   - pgvector para embeddings
   - Redis para colas

5. **Persona 3** (Pop Oracle) — cuando el canal genere revenue
   - Voz femenina (TBD)
   - Requiere más fuentes de datos (celebrity news APIs)
