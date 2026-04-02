# YouLikeIt — Roadmap de Tareas

> Pipeline automatizado de contenido educativo para YouTube Shorts.
> Misión: extraer lecciones de vida del cine, manga, anime, novelas y libros.
> Temas centrales: nihilismo → adicción → levantarse → intentarlo de nuevo.

---

## Estado Actual (Marzo 2026)

### ✅ Completado
- [x] Pipeline base: descubrimiento → quotes → clasificación → video → upload
- [x] Manga vertical: MangaDex API + Fandom Wiki + OCR + camera scroll
- [x] Frontend React: editor de Shorts, Review queue, clip library, metadata
- [x] YouTube upload con OAuth (insomnesoul@gmail.com)
- [x] GitHub Action (cron diario, excluye días 15-18)
- [x] Subtítulos animados estilo Shorts (módulo animated_subs.py)
- [x] Google Trends integrado para relevancia temporal
- [x] Gemini Flash para narración dramática
- [x] edge-tts como TTS temporal (Andrew EN / Gonzalo ES)
- [x] Docker multi-container (ytlab, api, frontend, fish-speech)

### 🔧 En Progreso
- [ ] **Fish Speech TTS** — imagen v1.4.1 + PyTorch nightly cu128 (Blackwell RTX 5060)
  - Modelo openaudio-s1-mini descargado
  - Pendiente: resolver tokenizer error y probar generación de voz
- [ ] **Git push** de todos los cambios recientes

---

## Fase 5: Voz y Personalidad

### 5.1 Fish Speech Operativo
- [ ] Resolver compatibilidad Fish Speech + PyTorch Blackwell
- [ ] Probar generación de voz con texto de Berserk
- [ ] Seleccionar 2 voces predeterminadas (una épica, una reflexiva)
- [ ] Integrar Fish Speech al pipeline (reemplazar edge-tts)
- [ ] Voice cloning: grabar 30s de tu voz y usarla como referencia

### 5.2 Subtítulos Animados
- [ ] Quemar subtítulos ASS en los videos (animated_subs.py ya existe)
- [ ] Sincronizar con la narración de Fish Speech
- [ ] Palabras clave resaltadas en color según emoción
- [ ] Probar estilos: shorts (2-3 palabras), karaoke, simple

### 5.3 Música Trending (con cache)
- [ ] ytmusicapi integrado — charts de YouTube Music
- [ ] **Cache local en SQLite** — guardar charts 1x/día, no pedir a cada request
  - Tabla `trending_songs`: title, artist, youtube_url, chart_rank, genre, fetched_at
  - TTL de 24h: si el último fetch fue hace <24h, usar cache
  - El pipeline y el frontend leen del cache, no de la API directamente
- [ ] Sección en frontend para ver/seleccionar canciones trending
- [ ] Metadata de canción sugerida por tag/emoción del Short
- [ ] Link a YouTube para escuchar antes de elegir

---

## Fase 6: Aprendizaje Automático (Feedback Loop)

### 6.1 Medición Profunda
- [ ] Retención segundo a segundo por Short (ex19/ex24 ya existe)
- [ ] Watch time promedio vs duración total
- [ ] CTR de thumbnails
- [ ] Demographics detallados (edad, género, país)
- [ ] Engagement: likes/comments/shares ratio
- [ ] Hora y día de publicación vs performance
- [ ] **Punto de abandono**: detectar en qué segundo la gente se va
  - IQR (rango intercuartílico) para identificar outliers de abandono
  - Cruzar segundo de abandono con edad, género, país
  - Separar población: "los que se quedan" vs "los que se van"
  - Análisis por tipo de escena en ese segundo (¿qué estaba pasando?)

### 6.2 Correlación (Random Forest mejorado)
- [ ] Features: serie, emoción, tipo de escena, voz, duración, hora
- [ ] Target: retención promedio, engagement
- [ ] Entrenar con 50-100 videos publicados
- [ ] Identificar: "¿qué retiene más? acción vs reflexión vs tragedia"
- [ ] Detectar qué emociones en la voz generan más watch time

### 6.3 A/B Testing Automatizado
- [ ] Variantes por Short: mismo contenido, diferentes tratamientos
  - Variante A: narración dramática vs Variante B: narración reflexiva
  - Variante A: voz grave vs Variante B: voz aguda
  - Variante A: subtítulos blancos vs Variante B: subtítulos con color
  - Variante A: intro con pregunta vs Variante B: intro con dato
- [ ] Publicar ambas variantes (una como unlisted, link en comunidad)
- [ ] Comparar retención, engagement, CTR después de 48h
- [ ] Random Forest aprende de los resultados del A/B
- [ ] Automatizar: el pipeline genera 2 versiones, sube ambas, mide, elige

### 6.4 Selección Inteligente de Contenido
- [ ] Multi-armed bandit: 80% explotar lo que funciona, 20% explorar nuevo
- [ ] Score de prioridad = f(retención, engagement, trending, misión)
- [ ] Auto-seleccionar siguiente serie/manga/libro a usar
- [ ] Filtrar trends por relevancia a la misión del canal:
  - Gemini: "De estos 20 trends, ¿cuáles conectan con superación personal?"
- [ ] Ajustar estilo de narración según lo que el público responde

### 6.5 Evolución de Audiencia
- [ ] Fase 1 (mes 1-3): Exploración — publicar diverso, medir todo
- [ ] Fase 2 (mes 3-6): Convergencia — el modelo detecta patrones
- [ ] Fase 3 (mes 6+): Personalidad definida — voz clonada, estilo propio

---

## Fase 7: Verticales de Contenido

### 7.1 Manga/Anime (operativo)
- [x] Descubrimiento trending (AniList, Jikan, MangaDex)
- [x] Wiki scraper para resúmenes reales
- [x] Descarga de páginas por capítulo
- [x] Camera scroll + panel detection
- [ ] Mejorar match narración↔panel (OCR + Gemini page hints)
- [ ] Series completas particionadas por arcos

### 7.2 Películas/Series (pausado — necesita Real-Debrid o Fonti)
- [ ] Reactivar cuando el canal genere ~$4/mes para Real-Debrid
- [ ] O configurar Tailscale + qBittorrent en Fonti
- [ ] ex11 corta clips exactos con timestamps de OpenSubtitles
- [ ] Novelas colombianas viejas (Betty la fea, Pasión de gavilanes, etc.)

### 7.3 Comics Occidentales
- [ ] Marvel/DC via MangaDex o scraper dedicado
- [ ] Webcomics (Webtoon)
- [ ] Panel detection adaptado a formato comic (colores, layouts diferentes)

### 7.4 Libros
- [ ] Conectar con Project Gutenberg (libros de dominio público)
- [ ] Extraer quotes icónicas de libros de filosofía, autoayuda, literatura
- [ ] Generar Shorts con texto + imágenes generativas o stock
- [ ] Nihilismo: Nietzsche, Camus, Dostoevsky
- [ ] Adicción/recuperación: libros de psicología
- [ ] Resiliencia: Viktor Frankl, Jordan Peterson, etc.

### 7.5 Lyrics/Música
- [ ] Extraer letras de canciones con significado profundo
- [ ] Shorts con lyrics + visualización + narración reflexiva

---

## Fase 8: Frontend y UX

### 8.1 Editor de Shorts
- [ ] Preview en tiempo real con clips del timeline
- [ ] Drag & drop clips de la clip library
- [ ] Configurar movimiento de cámara por clip
- [ ] Selección de canción trending

### 8.2 Review Queue
- [x] Lista de Shorts pendientes con preview
- [ ] Reproducción de video funcional en el browser
- [ ] Issues con timestamp relativo a la duración del video
- [ ] Approve → auto-upload a YouTube

### 8.3 Dashboard/Analytics
- [ ] Métricas en tiempo real via WebSocket
- [ ] Revenue tracking (cuando haya monetización)
- [ ] Comparación de performance por vertical
- [ ] Calendario de publicaciones (Planner)

### 8.4 Knowledge Base
- [ ] Banco de contenido extraído (manga, libros, movies)
- [ ] Búsqueda semántica (ChromaDB)
- [ ] Reutilización de clips entre Shorts

---

## Fase 9: Infraestructura

### 9.1 Almacenamiento
- [ ] Videos en E:\youlikeit-outputs (USB)
- [ ] Sync automático al final de cada pipeline run
- [ ] Limpieza de archivos temporales

### 9.2 Descarga de Contenido
- [ ] Windscribe VPN para torrents (cuando se active)
- [ ] O Real-Debrid ($3-4/mes) para descarga instantánea
- [ ] O Tailscale + Fonti como nodo de descarga
- [ ] qBittorrent API integrada al pipeline

### 9.3 CI/CD
- [x] GitHub Action con cron (excluye días 15-18)
- [ ] Secrets configurados en GitHub (API keys, OAuth token)
- [ ] Pipeline manga-short completo en Action
- [ ] Notificaciones de éxito/error

---

## Principios

1. **Zero-cost** — todo gratis o mínimo costo
2. **Interpretable** — Random Forest, ANOVA, no cajas negras
3. **ETL pattern** — Extract → Transform → Load en todo
4. **Auto-mejora** — el pipeline aprende de sus resultados
5. **Misión clara** — nihilismo → redención → crecimiento
6. **Audiencia primero** — el contenido se adapta a quién lo ve
