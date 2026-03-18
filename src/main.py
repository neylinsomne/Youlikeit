import argparse

from common.config import load_settings
from exercises import (
    ex00_check_connections,
    ex01_search_and_open,
    ex02_video_metadata,
    ex03_channel_rss_monitor,
    ex04_discover_movies,
    ex05_download_subtitles,
    ex06_match_quotes,
    ex07_search_scenes,
    ex08_growth_pack,
    ex09_curate_groups,
    ex10_classify_quotes,
    ex11_cut_video,
    ex12_upload,
    ex13_trend_graph,
    ex14_davinci_edit,
)


EXERCISES = {
    "ex00": "Verificacion de conexiones/keys (.env)",
    "ex01": "Busqueda y captura en YouTube (Playwright)",
    "ex02": "Extraccion de metadata de video (yt-dlp)",
    "ex03": "Monitoreo RSS de canal (feedparser)",
    "ex04": "Descubrir peliculas y frases (TMDB + Wikiquote)",
    "ex05": "Descargar subtitulos .srt (OpenSubtitles/SubDL)",
    "ex06": "Matching frases <-> timestamps (rapidfuzz + pysubs2)",
    "ex07": "Buscar escenas por tema (ChromaDB / SQLite)",
    "ex08": "Generar pack de crecimiento (hashtags + songs + checklist)",
    "ex09": "Curar y agrupar clips (ranking + pre-edicion)",
    "ex10": "Clasificar frases con LLM (categoria, emocion, viral score)",
    "ex11": "Cortar video con FFmpeg (descarga + corte + concat)",
    "ex12": "Subir Short a YouTube (Data API v3)",
    "ex13": "Grafo de tendencias (canciones + hashtags + temas + emociones)",
    "ex14": "Edicion DaVinci Resolve (templates + spec + MCP)",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ejercicios de automatizacion de YouTube")
    parser.add_argument("exercise", nargs="?", choices=list(EXERCISES.keys()), help="Ejercicio a ejecutar")
    parser.add_argument("--list", action="store_true", help="Lista ejercicios disponibles")

    # ex01
    parser.add_argument("--query", default="python automation", help="Busqueda para ex01 / tema para ex07")
    # ex02
    parser.add_argument("--url", default="https://www.youtube.com/watch?v=dQw4w9WgXcQ", help="URL de video para ex02")
    # ex03
    parser.add_argument("--channel-id", default="UC_x5XG1OV2P6uZZ5FSM9Ttw", help="Canal para ex03")
    # ex04
    parser.add_argument("--max-movies", type=int, default=10, help="Max peliculas a descubrir (ex04)")
    parser.add_argument("--mode", default="trending", help="Modo: trending, genre, year, now_playing, search, all (ex04)")
    parser.add_argument("--genre", default="", help="Genero: action, drama, thriller, horror, scifi, comedy, crime (ex04)")
    parser.add_argument("--year", type=int, default=0, help="Año especifico (ex04 --mode year)")
    # ex05
    parser.add_argument("--max-downloads", type=int, default=10, help="Max subtitulos a descargar (ex05)")
    # ex06
    parser.add_argument("--threshold", type=int, default=70, help="Umbral de fuzzy matching 0-100 (ex06)")
    parser.add_argument("--with-chroma", action="store_true", help="Indexar en ChromaDB (ex06)")
    # ex07
    parser.add_argument("--max-results", type=int, default=5, help="Max resultados (ex07)")
    parser.add_argument("--unique-movies", action="store_true", default=True, help="Un clip por pelicula (ex07)")
    # ex08
    parser.add_argument("--country-code", default="CO", help="Codigo de pais para tendencia TikTok (ex08)")
    parser.add_argument("--period-days", type=int, default=7, help="Ventana de tendencia: 7/30/120 (ex08)")
    # ex09
    parser.add_argument("--group-size", type=int, default=3, help="Clips por grupo propuesto (ex09)")
    # ex10
    parser.add_argument("--provider", default="auto", help="LLM provider: auto, groq, gemini, ollama, heuristic (ex10)")
    parser.add_argument("--ollama-model", default="mistral", help="Modelo Ollama (ex10)")
    parser.add_argument("--batch-size", type=int, default=50, help="Frases a clasificar por ejecucion (ex10)")
    # ex11
    parser.add_argument("--manifest", default="", help="Ruta al manifest JSON (ex11)")
    parser.add_argument("--burn-subs", action="store_true", help="Quemar subtitulos en el video (ex11)")
    parser.add_argument("--no-vertical", action="store_true", help="No convertir a 9:16 (ex11)")
    # ex12
    parser.add_argument("--video", default="", help="Ruta al video para subir (ex12)")
    parser.add_argument("--title", default="", help="Titulo del video (ex12)")
    parser.add_argument("--privacy", default="private", help="Privacidad: private, unlisted, public (ex12)")
    # ex13
    parser.add_argument("--export-gexf", action="store_true", help="Exportar grafo en GEXF para Gephi (ex13)")
    # ex14
    parser.add_argument("--template", default="auto", help="Template: auto, villain, romance, motivational, comedy, action, dramatic, horror (ex14)")
    parser.add_argument("--render", action="store_true", help="Lanzar render en DaVinci automaticamente (ex14)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        print("\nEjercicios disponibles:")
        print("=" * 60)
        for key, desc in EXERCISES.items():
            print(f"  {key}: {desc}")
        print("\nFlujo recomendado: ex04 -> ex05 -> ex06 -> ex10 -> ex07 -> ex09 -> ex11 -> ex08 -> ex12")
        print("  ex04: Descubre peliculas + extrae frases de Wikiquote")
        print("  ex05: Descarga subtitulos .srt para obtener timestamps")
        print("  ex06: Cruza frases con subtitulos (fuzzy matching)")
        print("  ex10: Clasifica frases (categoria, emocion, viral score)")
        print("  ex07: Busca escenas por tema para armar Shorts")
        print("  ex09: Rankea matches, muestra top y sugiere grupos antes de editar")
        print("  ex11: Corta y ensambla el video con FFmpeg")
        print("  ex08: Propone hashtags + canciones + checklist de subida")
        print("  ex13: Grafo de tendencias (relaciones cancion-hashtag-tema-emocion)")
        print("  ex12: Sube el Short a YouTube")
        return

    if not args.exercise:
        parser.print_help()
        return

    settings = load_settings()

    if args.exercise == "ex00":
        out = ex00_check_connections.run(settings)
    elif args.exercise == "ex01":
        out = ex01_search_and_open.run(args.query, settings)
    elif args.exercise == "ex02":
        out = ex02_video_metadata.run(args.url, settings)
    elif args.exercise == "ex03":
        out = ex03_channel_rss_monitor.run(args.channel_id, settings)
    elif args.exercise == "ex04":
        out = ex04_discover_movies.run(
            settings, max_movies=args.max_movies, mode=args.mode,
            genre=args.genre, year=args.year, query=args.query,
        )
    elif args.exercise == "ex05":
        out = ex05_download_subtitles.run(settings, max_downloads=args.max_downloads)
    elif args.exercise == "ex06":
        out = ex06_match_quotes.run(settings, threshold=args.threshold, with_chroma=args.with_chroma)
    elif args.exercise == "ex07":
        out = ex07_search_scenes.run(
            settings, query=args.query, max_results=args.max_results, unique_movies=args.unique_movies
        )
    elif args.exercise == "ex08":
        out = ex08_growth_pack.run(
            settings,
            query=args.query,
            country_code=args.country_code,
            period_days=args.period_days,
        )
    elif args.exercise == "ex09":
        out = ex09_curate_groups.run(
            settings,
            query=args.query,
            max_results=args.max_results,
            group_size=args.group_size,
        )
    elif args.exercise == "ex10":
        out = ex10_classify_quotes.run(
            settings,
            provider=args.provider,
            ollama_model=args.ollama_model,
            batch_size=args.batch_size,
        )
    elif args.exercise == "ex11":
        out = ex11_cut_video.run(
            settings,
            query=args.query,
            manifest_path=args.manifest,
            burn_subs=args.burn_subs,
            vertical=not args.no_vertical,
        )
    elif args.exercise == "ex12":
        out = ex12_upload.run(
            settings,
            video_path=args.video,
            title=args.title,
            privacy=args.privacy,
            query=args.query,
        )
    elif args.exercise == "ex13":
        out = ex13_trend_graph.run(
            settings,
            query=args.query,
            export_gexf=args.export_gexf,
        )
    elif args.exercise == "ex14":
        out = ex14_davinci_edit.run(
            settings,
            query=args.query,
            template=args.template,
            do_render=args.render,
        )
    else:
        raise ValueError("Ejercicio no soportado")

    print(f"Terminado. Resultado: {out}")


if __name__ == "__main__":
    main()
