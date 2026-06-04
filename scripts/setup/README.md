# scripts/setup · Setup de assets y OAuth

> **Owner**: pendiente (provisional: QA Agent).

## Archivos

| Script | Propósito |
|---|---|
| `setup_voices.py` | Descarga voces edge-tts + Fish Speech params |
| `seed_cross_refs.py` | Pobla `cross_ref_images` con personajes cinema canónicos |
| `download_movies.py` | Descarga películas para pipeline de quotes |
| `remote-download.py` | qBittorrent remoto + curl helpers |

## Comandos

```powershell
# Setup inicial (una sola vez)
python scripts/setup/setup_voices.py
python scripts/setup/seed_cross_refs.py
```
