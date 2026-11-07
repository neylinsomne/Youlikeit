"""Exporta el catálogo público del sitio (web/app/data/catalog.json) desde la DB.

Runner delgado: lee apps.moments.vocab (nombres/descripciones de tropos) y la DB
(obras, momentos, emociones con confianza ≥ 0.5) y escribe el JSON que sirve
el sitio. Por defecto publica solo obras de dominio público o licencia abierta.

    python scripts/web/export_catalog.py               # DATA_DIR del .env
    python scripts/web/export_catalog.py --include-owned
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from apps.moments.vocab import load_vocab
from core.config import load_settings
from core.db import get_db

OUT = Path(__file__).resolve().parents[2] / "web" / "app" / "data" / "catalog.json"
RIGHTS_LABEL = {"public_domain": "Public domain", "open_license": "Open license", "owned": "Licensed copy"}


def build(conn: sqlite3.Connection, *, include_owned: bool = False, min_conf: float = 0.5) -> dict:
    rights = ["public_domain", "open_license"] + (["owned"] if include_owned else [])
    q = ",".join("?" * len(rights))
    rows = conn.execute(f"""
        SELECT w.id, w.title, w.year, a.provider, a.external_id, a.rights,
               (SELECT COUNT(*) FROM moments m WHERE m.asset_id = a.id) AS moments
        FROM works w JOIN media_assets a ON a.work_id = w.id
        WHERE a.rights IN ({q}) ORDER BY w.year, w.title""", rights).fetchall()
    films, seen = [], set()
    for wid, title, year, provider, ext_id, right, n_moments in rows:
        if wid in seen:
            continue
        seen.add(wid)
        emotions = [r[0] for r in conn.execute("""
            SELECT l.value FROM moment_labels l JOIN moments m ON m.id = l.moment_id
            JOIN media_assets a ON a.id = m.asset_id
            WHERE a.work_id = ? AND l.dimension = 'emotion' AND l.confidence >= ?
            GROUP BY l.value ORDER BY COUNT(*) DESC""", (wid, min_conf))]
        films.append({
            "title": title, "year": year, "rights": right, "rights_label": RIGHTS_LABEL[right],
            "moments": n_moments, "emotions": emotions,
            "source_url": f"https://archive.org/details/{ext_id}" if provider == "archive_org" else None,
        })
    tropes = {t["id"]: {"en": t["en"], "es": t["es"], "desc_en": t["desc_en"], "desc_es": t["desc_es"]}
              for t in load_vocab()["trope"]}
    return {"tropes": tropes, "films": films}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--include-owned", action="store_true", help="Incluir copias propias (derechos 'owned')")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    conn = get_db(load_settings().data_dir)
    catalog = build(conn, include_owned=args.include_owned)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"catalog: {len(catalog['films'])} films, {len(catalog['tropes'])} tropes -> {args.out}")


if __name__ == "__main__":
    main()
