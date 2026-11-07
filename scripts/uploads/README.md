# scripts/uploads · Subida a plataformas

> **Owner**: pendiente — diferido hasta que TikTok app review pase.

## Archivos

| Script | Propósito |
|---|---|
| `upload_cycle_v2_shorts.py` | Subida YouTube Shorts |
| `upload_series_from_produce.py` | Subida desde `outputs/produce/` directo |

## Estado actual

- 🔴 **DESHABILITADO por owner** hasta validar calidad del hook scorer.
- TikTok pendiente de aprobación del flujo OAuth.
- YouTube channels: Deep Mind ok, Voz Latina ok, Pop Oracle pendiente.

## Cuando se reactive

1. Validar que `hook_scores.passed = 1` en los videos a subir
2. Modo `--dry-run` antes de cualquier upload real
3. Marcar `youtube_id` / `tiktok_id` en `content_produced`
