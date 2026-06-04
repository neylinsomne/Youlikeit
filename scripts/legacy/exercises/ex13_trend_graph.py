"""
ex13 - Grafo heterogeneo de tendencias: canciones, hashtags, temas, emociones, frases.

Construye un grafo con NetworkX donde los nodos son de tipos distintos y las aristas
representan relaciones con pesos + metadata extensible.

Tipos de nodos:
  - song:     Cancion trending (de TikTok Creative Center)
  - hashtag:  Hashtag trending (TikTok + YouTube suggest)
  - theme:    Tema de busqueda del usuario
  - emotion:  Emocion detectada (anger, joy, sadness...)
  - category: Categoria de frase (villain, romance, motivational...)
  - quote:    Frase con timestamp
  - movie:    Pelicula

Tipos de aristas (relaciones):
  - co_occurs:       Cancion <-> Hashtag (aparecen juntos en tendencias)
  - co_tagged:       Hashtag <-> Hashtag (se usan juntos frecuentemente)
  - fits_theme:      Cancion/Quote -> Theme (similitud semantica)
  - evokes:          Theme/Quote -> Emotion (clasificacion)
  - belongs_to:      Quote -> Category, Quote -> Movie
  - similar_meaning: Cualquier nodo texto <-> otro (embedding cosine)

Pesos de aristas:
  Cada arista tiene un dict de metadata extensible:
  {
    "weight": float,           # Peso base (0-1)
    "source": str,             # De donde viene (scraping, llm, embedding, manual)
    "confidence": float,       # Confianza en la relacion (0-1)
    "context": dict,           # EXTENSIBLE: jergas, slang, cultura, sinonimos
    "updated_at": str,         # Timestamp
  }

  El campo "context" es un dict abierto para agregar en el futuro:
  {
    "slang_mappings": {"no cap": "de verdad", "slay": "dominar"},
    "region": "CO",
    "synonyms": ["villain", "antagonist", "bad guy"],
    "cultural_weight": 0.8,    # Relevancia cultural para la region
    "generation": "gen_z",     # Segmento demografico
  }

Uso:
  python src/main.py ex13 --query "villain monologue"
  python src/main.py ex13 --query "motivacion gym" --export-gexf
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger


# ── Edge metadata schema ─────────────────────────────────────────────


def _make_edge_meta(
    weight: float,
    source: str,
    confidence: float = 1.0,
    context: dict | None = None,
) -> dict:
    """
    Create standardized edge metadata.

    The 'context' field is intentionally open/extensible for future use:
    slang mappings, regional weights, synonyms, demographic segments, etc.
    """
    return {
        "weight": round(weight, 4),
        "source": source,  # scraping, embedding, llm, heuristic, manual
        "confidence": round(confidence, 3),
        "context": context or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Graph building ───────────────────────────────────────────────────


def _build_graph(
    songs: list[dict],
    hashtags: list[str],
    quotes: list[dict],
    movies: list[dict],
    query: str,
    data_dir: Path,
    log,
):
    """
    Build the heterogeneous trend graph.

    Returns a NetworkX DiGraph with typed nodes and weighted edges.
    """
    try:
        import networkx as nx
    except ImportError:
        log.error("networkx not installed. Run: pip install networkx")
        return None

    G = nx.DiGraph()

    # ── 1. Theme node (from user query) ──────────────────────────
    theme_id = f"theme:{query}"
    G.add_node(theme_id, type="theme", label=query)
    log.info(f"Theme node: {query}")

    # ── 2. Song nodes ────────────────────────────────────────────
    for i, song in enumerate(songs):
        title = song.get("title", f"song_{i}")
        song_id = f"song:{_safe_id(title)}"
        G.add_node(song_id, type="song", label=title, **{
            k: v for k, v in song.items() if k != "title" and isinstance(v, (str, int, float))
        })

    log.info(f"Song nodes: {len(songs)}")

    # ── 3. Hashtag nodes ─────────────────────────────────────────
    for tag in hashtags:
        tag_id = f"hashtag:{tag.lower()}"
        G.add_node(tag_id, type="hashtag", label=f"#{tag}")

    log.info(f"Hashtag nodes: {len(hashtags)}")

    # ── 4. Quote + Movie + Category + Emotion nodes ──────────────
    categories_seen = set()
    emotions_seen = set()

    for q in quotes:
        # Quote node
        q_id = f"quote:{q['id']}"
        G.add_node(q_id, type="quote", label=q["text"][:60],
                   movie_id=q.get("movie_id", 0),
                   viral_score=q.get("viral_score", 0),
                   start_ms=q.get("start_ms", 0),
                   end_ms=q.get("end_ms", 0))

        # Category node
        cat = q.get("category", "")
        if cat:
            cat_id = f"category:{cat}"
            if cat not in categories_seen:
                G.add_node(cat_id, type="category", label=cat)
                categories_seen.add(cat)
            # Edge: quote -> category
            G.add_edge(q_id, cat_id, relation="belongs_to",
                       **_make_edge_meta(1.0, "llm", confidence=0.9))

        # Emotion node
        emo = q.get("emotion", "")
        if emo:
            emo_id = f"emotion:{emo}"
            if emo not in emotions_seen:
                G.add_node(emo_id, type="emotion", label=emo)
                emotions_seen.add(emo)
            # Edge: quote -> emotion
            G.add_edge(q_id, emo_id, relation="evokes",
                       **_make_edge_meta(0.8, "llm", confidence=0.85))

    log.info(f"Quote nodes: {len(quotes)}, Categories: {len(categories_seen)}, Emotions: {len(emotions_seen)}")

    # ── 5. Movie nodes ───────────────────────────────────────────
    for m in movies:
        m_id = f"movie:{m['id']}"
        G.add_node(m_id, type="movie", label=m.get("title", ""),
                   year=m.get("year", 0), genre=m.get("genre", ""),
                   popularity=m.get("popularity", 0))

    # Edges: quote -> movie
    for q in quotes:
        q_id = f"quote:{q['id']}"
        m_id = f"movie:{q.get('movie_id', 0)}"
        if G.has_node(m_id):
            G.add_edge(q_id, m_id, relation="belongs_to",
                       **_make_edge_meta(1.0, "database", confidence=1.0))

    log.info(f"Movie nodes: {len(movies)}")

    # ── 6. Song <-> Hashtag edges (co-occurrence) ────────────────
    _add_cooccurrence_edges(G, songs, hashtags, log)

    # ── 7. Hashtag <-> Hashtag edges (co-tagging) ────────────────
    _add_cotag_edges(G, hashtags, log)

    # ── 8. Song/Quote -> Theme edges (semantic similarity) ───────
    _add_semantic_edges(G, theme_id, query, songs, quotes, data_dir, log)

    # ── 9. Theme -> Category/Emotion edges ───────────────────────
    _add_theme_classification_edges(G, theme_id, quotes, log)

    return G


def _safe_id(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text.lower())[:50]


# ── Edge builders ────────────────────────────────────────────────────


def _add_cooccurrence_edges(G, songs, hashtags, log):
    """Song <-> Hashtag: keyword overlap as proxy for co-occurrence."""
    from collections import Counter

    hashtag_tokens = {}
    for tag in hashtags:
        tokens = set(re.findall(r"[a-z]{3,}", tag.lower()))
        hashtag_tokens[tag] = tokens

    edges_added = 0
    for song in songs:
        title = song.get("title", "")
        song_id = f"song:{_safe_id(title)}"
        song_tokens = set(re.findall(r"[a-z]{3,}", title.lower()))

        if not song_tokens:
            continue

        for tag, tag_toks in hashtag_tokens.items():
            overlap = song_tokens & tag_toks
            if overlap:
                tag_id = f"hashtag:{tag.lower()}"
                weight = len(overlap) / max(len(song_tokens), len(tag_toks))
                G.add_edge(song_id, tag_id, relation="co_occurs",
                           **_make_edge_meta(
                               weight, "scraping",
                               confidence=min(1.0, weight + 0.3),
                               context={
                                   "shared_tokens": list(overlap),
                                   # EXTENSIBLE: future slang/synonym resolution goes here
                                   # "slang_resolved": {"lit": "amazing", ...},
                                   # "region_boost": {"CO": 1.2, "MX": 0.9},
                               },
                           ))
                edges_added += 1

    log.info(f"Co-occurrence edges (song-hashtag): {edges_added}")


def _add_cotag_edges(G, hashtags, log):
    """Hashtag <-> Hashtag: connect hashtags with shared tokens."""
    edges_added = 0
    tag_list = list(hashtags)

    for i in range(len(tag_list)):
        tokens_i = set(re.findall(r"[a-z]{3,}", tag_list[i].lower()))
        if not tokens_i:
            continue

        for j in range(i + 1, min(i + 30, len(tag_list))):  # Limit comparisons
            tokens_j = set(re.findall(r"[a-z]{3,}", tag_list[j].lower()))
            overlap = tokens_i & tokens_j
            if overlap:
                id_i = f"hashtag:{tag_list[i].lower()}"
                id_j = f"hashtag:{tag_list[j].lower()}"
                weight = len(overlap) / max(len(tokens_i), len(tokens_j))
                G.add_edge(id_i, id_j, relation="co_tagged",
                           **_make_edge_meta(
                               weight, "scraping",
                               context={
                                   "shared_tokens": list(overlap),
                                   # EXTENSIBLE: future fields
                                   # "synonyms": [...],
                                   # "semantic_group": "motivation",
                               },
                           ))
                edges_added += 1

    log.info(f"Co-tag edges (hashtag-hashtag): {edges_added}")


def _add_semantic_edges(G, theme_id, query, songs, quotes, data_dir, log):
    """
    Song/Quote -> Theme edges using ChromaDB embeddings (cosine similarity).

    Uses the existing all-MiniLM-L6-v2 model from ChromaDB (free, local, CPU).
    Falls back to token overlap if ChromaDB is not available.
    """
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(data_dir / "chromadb"))
        # Use a temporary collection for similarity computation
        temp = client.get_or_create_collection("_trend_graph_temp")

        # Embed the theme query
        theme_docs = [query]
        theme_ids = ["theme_query"]

        # Embed song titles
        song_docs = [s.get("title", "") for s in songs if s.get("title")]
        song_ids = [f"song_{_safe_id(s.get('title', ''))}" for s in songs if s.get("title")]

        all_docs = theme_docs + song_docs
        all_ids = theme_ids + song_ids

        if len(all_docs) > 1:
            temp.upsert(documents=all_docs, ids=all_ids)
            # Query theme against songs
            results = temp.query(query_texts=[query], n_results=min(20, len(song_docs)))

            if results and results["distances"]:
                for idx, (doc_id, distance) in enumerate(
                    zip(results["ids"][0], results["distances"][0])
                ):
                    if doc_id == "theme_query":
                        continue
                    similarity = max(0, 1 - distance)
                    if similarity > 0.3:
                        # Find corresponding song node
                        original_title = results["documents"][0][idx] if results["documents"] else ""
                        song_node_id = f"song:{_safe_id(original_title)}"
                        if G.has_node(song_node_id):
                            G.add_edge(song_node_id, theme_id, relation="fits_theme",
                                       **_make_edge_meta(
                                           similarity, "embedding",
                                           confidence=similarity,
                                           context={
                                               "model": "all-MiniLM-L6-v2",
                                               "method": "cosine_similarity",
                                               # EXTENSIBLE: future contextual adjustments
                                               # "cultural_boost": 0.0,
                                               # "slang_adjusted": False,
                                               # "synonym_expanded_query": "...",
                                           },
                                       ))

        # Clean up temp collection
        try:
            client.delete_collection("_trend_graph_temp")
        except Exception:
            pass

        log.info("Semantic edges: computed via ChromaDB embeddings")
        return

    except (ImportError, Exception) as e:
        log.info(f"ChromaDB not available ({e}), using token overlap for semantic edges")

    # Fallback: token overlap
    query_tokens = set(re.findall(r"[a-z]{3,}", query.lower()))
    if not query_tokens:
        return

    for song in songs:
        title = song.get("title", "")
        song_tokens = set(re.findall(r"[a-z]{3,}", title.lower()))
        overlap = query_tokens & song_tokens
        if overlap:
            song_id = f"song:{_safe_id(title)}"
            weight = len(overlap) / max(len(query_tokens), len(song_tokens))
            G.add_edge(song_id, theme_id, relation="fits_theme",
                       **_make_edge_meta(weight, "heuristic",
                                         context={"shared_tokens": list(overlap)}))


def _add_theme_classification_edges(G, theme_id, quotes, log):
    """Theme -> Category/Emotion: aggregate from classified quotes."""
    from collections import Counter

    cat_counts = Counter()
    emo_counts = Counter()

    for q in quotes:
        cat = q.get("category", "")
        emo = q.get("emotion", "")
        if cat:
            cat_counts[cat] += 1
        if emo:
            emo_counts[emo] += 1

    total_cats = sum(cat_counts.values()) or 1
    for cat, count in cat_counts.most_common(5):
        cat_id = f"category:{cat}"
        if G.has_node(cat_id):
            weight = count / total_cats
            G.add_edge(theme_id, cat_id, relation="evokes",
                       **_make_edge_meta(
                           weight, "aggregation",
                           confidence=min(1.0, count / 3),
                           context={
                               "quote_count": count,
                               "total": total_cats,
                               # EXTENSIBLE:
                               # "regional_preference": {"CO": 0.9, "ES": 0.7},
                           },
                       ))

    total_emos = sum(emo_counts.values()) or 1
    for emo, count in emo_counts.most_common(5):
        emo_id = f"emotion:{emo}"
        if G.has_node(emo_id):
            weight = count / total_emos
            G.add_edge(theme_id, emo_id, relation="evokes",
                       **_make_edge_meta(weight, "aggregation",
                                         context={"quote_count": count}))

    log.info(f"Theme classification edges: {len(cat_counts)} categories, {len(emo_counts)} emotions")


# ── Graph analysis ───────────────────────────────────────────────────


def _analyze_graph(G, query: str, log) -> dict:
    """
    Analyze the graph to extract actionable insights.

    Returns recommendations for the best song+hashtag combos.
    """
    import networkx as nx

    analysis = {
        "node_counts": {},
        "edge_counts": {},
        "top_songs_by_centrality": [],
        "top_hashtags_by_centrality": [],
        "best_combos": [],
        "theme_connections": [],
    }

    # Node type counts
    type_counts = {}
    for _, data in G.nodes(data=True):
        t = data.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    analysis["node_counts"] = type_counts

    # Edge relation counts
    rel_counts = {}
    for _, _, data in G.edges(data=True):
        r = data.get("relation", "unknown")
        rel_counts[r] = rel_counts.get(r, 0) + 1
    analysis["edge_counts"] = rel_counts

    # Degree centrality (most connected nodes)
    if G.number_of_nodes() > 1:
        centrality = nx.degree_centrality(G)

        song_centrality = [
            (nid, c) for nid, c in centrality.items()
            if G.nodes[nid].get("type") == "song"
        ]
        song_centrality.sort(key=lambda x: x[1], reverse=True)
        analysis["top_songs_by_centrality"] = [
            {"id": nid, "label": G.nodes[nid].get("label", ""), "centrality": round(c, 4)}
            for nid, c in song_centrality[:5]
        ]

        hashtag_centrality = [
            (nid, c) for nid, c in centrality.items()
            if G.nodes[nid].get("type") == "hashtag"
        ]
        hashtag_centrality.sort(key=lambda x: x[1], reverse=True)
        analysis["top_hashtags_by_centrality"] = [
            {"id": nid, "label": G.nodes[nid].get("label", ""), "centrality": round(c, 4)}
            for nid, c in hashtag_centrality[:10]
        ]

    # Best combos: songs connected to theme with highest-weighted paths
    theme_id = f"theme:{query}"
    if G.has_node(theme_id):
        for nid, data in G.nodes(data=True):
            if data.get("type") != "song":
                continue
            # Check if song connects to theme
            if G.has_edge(nid, theme_id):
                edge_data = G.edges[nid, theme_id]
                # Find hashtags connected to this song
                connected_hashtags = [
                    G.nodes[neighbor].get("label", "")
                    for neighbor in G.neighbors(nid)
                    if G.nodes[neighbor].get("type") == "hashtag"
                ]
                analysis["best_combos"].append({
                    "song": data.get("label", ""),
                    "theme_fit": edge_data.get("weight", 0),
                    "source": edge_data.get("source", ""),
                    "hashtags": connected_hashtags[:5],
                    "context": edge_data.get("context", {}),
                })

        analysis["best_combos"].sort(key=lambda x: x["theme_fit"], reverse=True)

        # Direct theme connections
        for neighbor in G.neighbors(theme_id):
            ndata = G.nodes[neighbor]
            edata = G.edges[theme_id, neighbor]
            analysis["theme_connections"].append({
                "node": ndata.get("label", ""),
                "type": ndata.get("type", ""),
                "relation": edata.get("relation", ""),
                "weight": edata.get("weight", 0),
            })

    return analysis


# ── Export ────────────────────────────────────────────────────────────


def _export_graph(G, output_dir: Path, safe_theme: str, export_gexf: bool, log) -> dict:
    """Export graph in multiple formats."""
    import networkx as nx

    paths = {}

    # JSON export (always)
    json_data = {
        "nodes": [],
        "edges": [],
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
            "edge_context_schema": {
                "weight": "float 0-1, relationship strength",
                "source": "how the edge was computed (scraping/embedding/llm/heuristic/manual)",
                "confidence": "float 0-1, certainty of the relationship",
                "context": {
                    "_description": "EXTENSIBLE dict for future metadata",
                    "shared_tokens": "list of overlapping keywords",
                    "slang_mappings": "(future) slang/jargon translations",
                    "region_boost": "(future) regional relevance multipliers",
                    "synonyms": "(future) synonym groups for this edge",
                    "cultural_weight": "(future) cultural relevance score",
                    "generation": "(future) demographic segment (gen_z, millennial...)",
                },
            },
        },
    }

    for nid, data in G.nodes(data=True):
        node_entry = {"id": nid, **{k: v for k, v in data.items() if isinstance(v, (str, int, float))}}
        json_data["nodes"].append(node_entry)

    for src, dst, data in G.edges(data=True):
        edge_entry = {"source": src, "target": dst}
        for k, v in data.items():
            if isinstance(v, (str, int, float, dict, list)):
                edge_entry[k] = v
        json_data["edges"].append(edge_entry)

    json_path = output_dir / f"ex13_trend_graph_{safe_theme}.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["json"] = json_path
    log.info(f"JSON export: {json_path}")

    # GEXF export (for Gephi visualization)
    if export_gexf:
        gexf_path = output_dir / f"ex13_trend_graph_{safe_theme}.gexf"
        try:
            nx.write_gexf(G, str(gexf_path))
            paths["gexf"] = gexf_path
            log.info(f"GEXF export: {gexf_path} (open with Gephi)")
        except Exception as e:
            log.warning(f"GEXF export failed: {e}")

    return paths


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    query: str = "epic movie moment",
    export_gexf: bool = False,
) -> Path:
    log = build_logger("ex13", settings.output_dir / "logs" / "ex13.log")
    conn = get_db(settings.data_dir)

    try:
        import networkx  # noqa: F401
    except ImportError:
        msg = "networkx not installed. Run: pip install networkx"
        log.error(msg)
        rp = settings.output_dir / "logs" / "ex13_graph_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(f"ex13 - ERROR: {msg}\n", encoding="utf-8")
        conn.close()
        return rp

    # ── Gather data from all sources ─────────────────────────────

    # Songs from latest growth pack (ex08)
    songs = []
    meta_dir = settings.output_dir / "metadata"
    if meta_dir.exists():
        packs = sorted(meta_dir.glob("ex08_growth_pack_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for pack_file in packs[:1]:
            try:
                pack = json.loads(pack_file.read_text(encoding="utf-8"))
                songs = pack.get("tiktok", {}).get("song_candidates", [])
                log.info(f"Loaded {len(songs)} songs from {pack_file.name}")
            except Exception:
                pass

    # Hashtags from growth pack
    hashtags = []
    if meta_dir.exists():
        for pack_file in sorted(meta_dir.glob("ex08_growth_pack_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:1]:
            try:
                pack = json.loads(pack_file.read_text(encoding="utf-8"))
                yt_tags = pack.get("youtube", {}).get("hashtags", [])
                tt_tags = pack.get("tiktok", {}).get("hashtags", [])
                # Strip # prefix
                hashtags = list(set(
                    t.lstrip("#") for t in yt_tags + tt_tags if t.startswith("#")
                ))
                log.info(f"Loaded {len(hashtags)} hashtags")
            except Exception:
                pass

    # Classified quotes (from ex10)
    cur = conn.execute(
        """SELECT q.*, m.title as movie_title
           FROM quotes q JOIN movies m ON q.movie_id = m.id
           WHERE q.start_ms IS NOT NULL AND q.category IS NOT NULL
           ORDER BY q.viral_score DESC NULLS LAST
           LIMIT 100"""
    )
    quotes = [dict(r) for r in cur.fetchall()]
    log.info(f"Loaded {len(quotes)} classified quotes")

    # Movies
    cur = conn.execute("SELECT * FROM movies ORDER BY popularity DESC LIMIT 50")
    movies = [dict(r) for r in cur.fetchall()]
    log.info(f"Loaded {len(movies)} movies")

    if not songs and not quotes:
        msg = "No data to build graph. Run ex04->ex05->ex06->ex10 and ex08 first."
        log.warning(msg)
        rp = settings.output_dir / "logs" / "ex13_graph_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(f"ex13 - {msg}\n", encoding="utf-8")
        conn.close()
        return rp

    # ── Build graph ──────────────────────────────────────────────

    G = _build_graph(songs, hashtags, quotes, movies, query, settings.data_dir, log)
    if G is None:
        conn.close()
        rp = settings.output_dir / "logs" / "ex13_graph_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text("ex13 - ERROR: Failed to build graph.\n", encoding="utf-8")
        return rp

    log.info(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # ── Analyze ──────────────────────────────────────────────────

    analysis = _analyze_graph(G, query, log)

    # ── Export ────────────────────────────────────────────────────

    graph_dir = settings.output_dir / "graphs"
    graph_dir.mkdir(parents=True, exist_ok=True)
    safe_theme = re.sub(r"[^a-zA-Z0-9_-]+", "_", query)[:40]

    export_paths = _export_graph(G, graph_dir, safe_theme, export_gexf, log)

    # ── Report ───────────────────────────────────────────────────

    report_lines = [
        "ex13 - Trend Graph Report",
        "=" * 50,
        f"Query: {query}",
        f"Nodes: {G.number_of_nodes()}",
        f"Edges: {G.number_of_edges()}",
        "",
        "Node types:",
    ]
    for ntype, count in sorted(analysis["node_counts"].items()):
        report_lines.append(f"  {ntype}: {count}")

    report_lines.append("")
    report_lines.append("Edge types:")
    for rel, count in sorted(analysis["edge_counts"].items()):
        report_lines.append(f"  {rel}: {count}")

    report_lines.append("")
    report_lines.append("Top songs by centrality (most connected):")
    for s in analysis["top_songs_by_centrality"][:5]:
        report_lines.append(f"  {s['label']} (centrality: {s['centrality']})")

    report_lines.append("")
    report_lines.append("Top hashtags by centrality:")
    for h in analysis["top_hashtags_by_centrality"][:8]:
        report_lines.append(f"  {h['label']} (centrality: {h['centrality']})")

    if analysis["best_combos"]:
        report_lines.append("")
        report_lines.append("Best song + hashtag combos for this theme:")
        report_lines.append("-" * 50)
        for combo in analysis["best_combos"][:5]:
            report_lines.append(f"  Song: {combo['song']} (fit: {combo['theme_fit']:.3f}, via {combo['source']})")
            if combo["hashtags"]:
                report_lines.append(f"    Use with: {' '.join(combo['hashtags'][:5])}")
            ctx = combo.get("context", {})
            if ctx:
                report_lines.append(f"    Context: {json.dumps(ctx, ensure_ascii=False)}")
            report_lines.append("")

    if analysis["theme_connections"]:
        report_lines.append("")
        report_lines.append("Theme connections:")
        for tc in sorted(analysis["theme_connections"], key=lambda x: x["weight"], reverse=True)[:10]:
            report_lines.append(
                f"  [{tc['type']}] {tc['node']} "
                f"({tc['relation']}, weight: {tc['weight']:.3f})"
            )

    report_lines.append("")
    report_lines.append("Edge context schema (extensible for future use):")
    report_lines.append("  weight:          relationship strength (0-1)")
    report_lines.append("  source:          how computed (scraping/embedding/llm/heuristic)")
    report_lines.append("  confidence:      certainty (0-1)")
    report_lines.append("  context.shared_tokens:    keyword overlap")
    report_lines.append("  context.slang_mappings:   (future) jargon translations")
    report_lines.append("  context.region_boost:     (future) regional relevance")
    report_lines.append("  context.synonyms:         (future) synonym groups")
    report_lines.append("  context.cultural_weight:  (future) cultural score")
    report_lines.append("  context.generation:       (future) demographic segment")

    report_lines.append("")
    for fmt, path in export_paths.items():
        report_lines.append(f"Export ({fmt}): {path}")

    report_path = settings.output_dir / "logs" / "ex13_graph_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report: {report_path}")

    conn.close()
    return report_path
