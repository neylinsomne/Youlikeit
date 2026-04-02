"""
ex06 - Matching de frases contra subtitulos para obtener timestamps.

Flujo:
  1. Lee frases sin timestamp de la BD
  2. Carga el .srt correspondiente con pysubs2
  3. Usa rapidfuzz para buscar la mejor coincidencia
  4. Guarda start_ms y end_ms en la BD
  5. Opcionalmente indexa en ChromaDB para busqueda semantica

Uso:
  python main.py ex06
  python main.py ex06 --threshold 75
  python main.py ex06 --with-chroma
"""

import re
from pathlib import Path

import pysubs2
from rapidfuzz import fuzz, process

from common.config import Settings
from common.db import get_db, get_quotes_without_timestamps, get_quotes_with_timestamps
from common.logger import build_logger


# ── SRT Loading ──────────────────────────────────────────────────────


def load_srt_events(srt_path: str) -> list[dict]:
    """Load an SRT file and return list of {start_ms, end_ms, text} dicts."""
    try:
        subs = pysubs2.load(srt_path)
    except Exception:
        # Fallback: manual regex parsing for malformed SRT files
        return _parse_srt_regex(srt_path)

    events = []
    for event in subs:
        if event.type == "Dialogue" or not hasattr(event, "type"):
            text = event.plaintext if hasattr(event, "plaintext") else event.text
            # Clean HTML tags and formatting
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\{[^}]+\}", "", text)
            text = text.strip()
            if text:
                events.append(
                    {
                        "start_ms": event.start,
                        "end_ms": event.end,
                        "text": text,
                    }
                )
    return events


def _parse_srt_regex(srt_path: str) -> list[dict]:
    """Fallback SRT parser using regex."""
    content = Path(srt_path).read_text(encoding="utf-8", errors="replace")

    pattern = re.compile(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
    )

    events = []
    blocks = content.strip().split("\n\n")

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        timestamp_match = None
        text_lines = []
        for line in lines:
            m = pattern.search(line)
            if m:
                timestamp_match = m
            elif timestamp_match and line.strip() and not line.strip().isdigit():
                text_lines.append(line.strip())

        if timestamp_match and text_lines:
            h1, m1, s1, ms1 = int(timestamp_match.group(1)), int(timestamp_match.group(2)), int(timestamp_match.group(3)), int(timestamp_match.group(4))
            h2, m2, s2, ms2 = int(timestamp_match.group(5)), int(timestamp_match.group(6)), int(timestamp_match.group(7)), int(timestamp_match.group(8))

            start_ms = h1 * 3600000 + m1 * 60000 + s1 * 1000 + ms1
            end_ms = h2 * 3600000 + m2 * 60000 + s2 * 1000 + ms2

            text = " ".join(text_lines)
            text = re.sub(r"<[^>]+>", "", text)
            text = text.strip()

            if text:
                events.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})

    return events


# ── Fuzzy Matching ───────────────────────────────────────────────────


def find_best_match(
    quote_text: str,
    srt_events: list[dict],
    threshold: int = 70,
) -> dict | None:
    """
    Find the SRT event that best matches the quote using fuzzy matching.

    Strategy:
      1. Try exact substring match first (fastest)
      2. Try sliding window of concatenated subtitle lines
      3. Fall back to individual line matching with rapidfuzz
    """
    quote_clean = _normalize(quote_text)

    if len(quote_clean) < 5:
        return None

    # Strategy 1: exact substring in individual lines
    for event in srt_events:
        if quote_clean.lower() in _normalize(event["text"]).lower():
            return {
                "start_ms": event["start_ms"],
                "end_ms": event["end_ms"],
                "confidence": 100.0,
                "matched_text": event["text"],
            }

    # Strategy 2: sliding window over consecutive lines
    # Quotes often span 2-4 subtitle blocks
    window_sizes = [2, 3, 4]
    best_window_match = None
    best_window_score = 0

    for window in window_sizes:
        for i in range(len(srt_events) - window + 1):
            chunk = srt_events[i : i + window]
            combined_text = " ".join(e["text"] for e in chunk)
            combined_clean = _normalize(combined_text)

            score = fuzz.partial_ratio(quote_clean.lower(), combined_clean.lower())

            if score > best_window_score and score >= threshold:
                best_window_score = score
                best_window_match = {
                    "start_ms": chunk[0]["start_ms"],
                    "end_ms": chunk[-1]["end_ms"],
                    "confidence": score,
                    "matched_text": combined_text[:200],
                }

    if best_window_match and best_window_score >= threshold:
        return best_window_match

    # Strategy 3: rapidfuzz process.extractOne against all lines
    choices = [_normalize(e["text"]) for e in srt_events]
    if not choices:
        return None

    result = process.extractOne(
        quote_clean,
        choices,
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold,
    )

    if result:
        matched_text, score, idx = result
        event = srt_events[idx]

        # Add 1 second padding on each side
        padded_start = max(0, event["start_ms"] - 1000)
        padded_end = event["end_ms"] + 1000

        return {
            "start_ms": padded_start,
            "end_ms": padded_end,
            "confidence": score,
            "matched_text": event["text"],
        }

    return None


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{[^}]+\}", "", text)
    text = re.sub(r"[♪♫♬]", "", text)
    text = re.sub(r"\([^)]*\)", "", text)  # Remove (parenthetical descriptions)
    text = re.sub(r"\[[^\]]*\]", "", text)  # Remove [bracketed descriptions]
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ── ChromaDB indexing (optional) ─────────────────────────────────────


def index_in_chromadb(quotes: list[dict], data_dir: Path, log) -> None:
    """Index quotes with timestamps in ChromaDB for semantic search."""
    try:
        import chromadb
    except ImportError:
        log.warning("chromadb not installed. Run: pip install chromadb")
        log.warning("Skipping vector indexing.")
        return

    client = chromadb.PersistentClient(path=str(data_dir / "chromadb"))
    collection = client.get_or_create_collection(
        name="movie_quotes",
        metadata={"hnsw:space": "cosine"},
    )

    documents = []
    metadatas = []
    ids = []

    for q in quotes:
        doc_id = f"quote_{q['id']}"

        # Skip if already indexed
        try:
            existing = collection.get(ids=[doc_id])
            if existing and existing["ids"]:
                continue
        except Exception:
            pass

        documents.append(q["text"])
        metadatas.append(
            {
                "movie_title": q["movie_title"],
                "movie_id": q["movie_id"],
                "start_ms": q["start_ms"],
                "end_ms": q["end_ms"],
                "character": q["character_name"] or "",
                "confidence": q["confidence"],
            }
        )
        ids.append(doc_id)

    if documents:
        # ChromaDB batches max 5461 by default
        batch_size = 100
        for i in range(0, len(documents), batch_size):
            collection.add(
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
                ids=ids[i : i + batch_size],
            )
        log.info(f"Indexed {len(documents)} quotes in ChromaDB")
    else:
        log.info("No new quotes to index in ChromaDB")


# ── Entry point ───────────────────────────────────────────────────────


def run(settings: Settings, threshold: int = 70, with_chroma: bool = False) -> Path:
    log = build_logger("ex06", settings.output_dir / "logs" / "ex06.log")
    conn = get_db(settings.data_dir)

    report_lines = ["ex06 - Match Quotes to Timestamps", "=" * 40, ""]

    # Get quotes that need timestamps
    quotes = get_quotes_without_timestamps(conn)
    log.info(f"Found {len(quotes)} quotes without timestamps")

    if not quotes:
        report_lines.append("All quotes already have timestamps.")
        report_path = settings.output_dir / "logs" / "ex06_matching_report.txt"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        conn.close()
        return report_path

    # Group quotes by movie
    by_movie = {}
    for q in quotes:
        mid = q["movie_id"]
        if mid not in by_movie:
            by_movie[mid] = []
        by_movie[mid].append(q)

    matched = 0
    unmatched = 0

    for movie_id, movie_quotes in by_movie.items():
        movie_title = movie_quotes[0]["movie_title"]

        # Find the SRT file for this movie
        cur = conn.execute(
            "SELECT srt_path FROM subtitles WHERE movie_id = ? LIMIT 1",
            (movie_id,),
        )
        sub_row = cur.fetchone()
        if not sub_row:
            log.warning(f"No subtitles for: {movie_title} (run ex05 first)")
            for q in movie_quotes:
                unmatched += 1
            continue

        srt_path = sub_row["srt_path"]
        if not Path(srt_path).exists():
            log.warning(f"SRT file missing: {srt_path}")
            continue

        # Load SRT
        log.info(f"Loading SRT for: {movie_title}")
        srt_events = load_srt_events(srt_path)
        if not srt_events:
            log.warning(f"  No valid subtitle events in {srt_path}")
            continue

        log.info(f"  {len(srt_events)} subtitle events loaded")

        # Match each quote
        for q in movie_quotes:
            quote_text = q["text"]
            result = find_best_match(quote_text, srt_events, threshold=threshold)

            if result:
                conn.execute(
                    """UPDATE quotes SET start_ms = ?, end_ms = ?, confidence = ?
                       WHERE id = ?""",
                    (result["start_ms"], result["end_ms"], result["confidence"], q["id"]),
                )
                conn.commit()
                matched += 1

                # Format timestamp for readability
                start_fmt = _ms_to_timestamp(result["start_ms"])
                end_fmt = _ms_to_timestamp(result["end_ms"])
                log.info(
                    f"  MATCH [{result['confidence']:.0f}%]: "
                    f"\"{quote_text[:50]}...\" -> {start_fmt} - {end_fmt}"
                )
                report_lines.append(
                    f"  [{result['confidence']:.0f}%] {movie_title}: "
                    f"\"{quote_text[:60]}\" @ {start_fmt}-{end_fmt}"
                )
            else:
                unmatched += 1
                log.info(f"  NO MATCH: \"{quote_text[:50]}...\"")

    report_lines.insert(2, f"Matched: {matched} | Unmatched: {unmatched}")

    # ChromaDB indexing
    if with_chroma:
        log.info("Indexing matched quotes in ChromaDB...")
        all_matched = get_quotes_with_timestamps(conn)
        # Convert sqlite3.Row to dict
        quotes_dicts = [dict(q) for q in all_matched]
        index_in_chromadb(quotes_dicts, settings.data_dir, log)
        report_lines.append(f"\nChromaDB: indexed {len(quotes_dicts)} quotes")

    report_lines.append("")
    cur = conn.execute("SELECT COUNT(*) as cnt FROM quotes WHERE start_ms IS NOT NULL")
    report_lines.append(f"Total quotes with timestamps: {cur.fetchone()['cnt']}")

    report_path = settings.output_dir / "logs" / "ex06_matching_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report saved to {report_path}")

    conn.close()
    return report_path


def _ms_to_timestamp(ms: int) -> str:
    """Convert milliseconds to HH:MM:SS format."""
    s = ms // 1000
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
