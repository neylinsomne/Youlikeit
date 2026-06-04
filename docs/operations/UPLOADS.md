# Uploads · APIs y costos: YouTube + TikTok

> **Nota (2026-06-02):** movido desde `GUIA_APIS_YOUTUBE_TIKTOK.md` (root) a
> `docs/operations/`. Doc load-bearing del dominio **uploads** (handler diferido;
> publicación en pausa hasta que la calidad esté OK y TikTok OAuth pase review).

Este documento resume como trabajar tendencias, hashtags y musica para Shorts/Reels/TikTok sin pagar al inicio.

## 1. YouTube: que es gratis y cuando cuesta

### Gratis para este proyecto

- YouTube Data API v3 con cuota diaria gratuita.
- Uso tipico de este repo (descubrimiento/metadata) suele caber dentro de la cuota.

### Cuando podria tener costo

- Si tu volumen crece y excedes la cuota de forma recurrente.
- Si pides ampliaciones para operacion a escala.
- Si integras otros servicios cloud de pago.

## 2. TikTok Business: que significa

- Cambiar cuenta personal a Business: gratis.
- Tener cuenta Business no implica pagar automaticamente.
- Lo que si cuesta: pauta publicitaria.

## 3. Tendencias de TikTok: de donde salen

Ruta recomendada:

- TikTok Creative Center (hashtags, songs, creators, videos trending).
- Filtro por pais e intervalo (7/30/120 dias) para evitar sesgo.

Nota:

- Para uso comercial, valida dentro de TikTok que el audio este habilitado para negocio.

## 4. APIs vs scraping

## APIs oficiales (preferido)

- Mas estables, menos riesgo de bloqueo.
- Mejor para produccion.

## Web publica (solo lectura)

- Puede servir para investigacion y prototipos.
- Respeta ToS, limites de frecuencia y robots.
- Evita scraping agresivo o bypass de autenticacion.

## 5. Flujo recomendado en este proyecto

1. Ejecutar pipeline de escenas:
   - ex04 -> ex05 -> ex06 -> ex07
2. Generar pack de publicacion:
   - ex08 (hashtags + songs + checklist)
3. Publicar test A/B y medir:
   - retencion 3s, retencion media, porcentaje completado, CTR

## 6. Checklist minimo antes de publicar

- Hook fuerte en primeros 2 segundos.
- Texto legible y subtitulos claros.
- 8-12 hashtags maximo, relevantes al tema.
- 3-5 audios candidatos y seleccion final por contexto/pais.
- Verificar licencia/uso comercial del audio en TikTok.

## 7. Variables sugeridas en .env

- YOUTUBE_API_KEY
- TMDB_API_KEY
- OPENSUBTITLES_API_KEY
- OPENSUBTITLES_USERNAME
- OPENSUBTITLES_PASSWORD
- SUBDL_API_KEY

## 8. Seguridad

Si accidentalmente publicaste claves en chat o repositorio:

1. Rotar API keys de inmediato.
2. Cambiar credenciales de usuario expuestas.
3. Revisar historial de git y logs exportados.
