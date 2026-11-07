"""
Batch orchestrator: runs the full content cycle every 3 days.

Flow:
  1. ContentRotator picks 1 series per persona (9 videos total: 3 personas x 3 types)
  2. For each selection, run produce_for_series.py to generate videos
  3. Log every produced video to content_produced table (for next rotation)
  4. Optional: upload to YouTube as unlisted

Usage:
  python scripts/production/run_rotation_batch.py                  # Full batch
  python scripts/production/run_rotation_batch.py --dry-run        # Scripts only
  python scripts/production/run_rotation_batch.py --upload-youtube # Also upload
  python scripts/production/run_rotation_batch.py --personas deep_mind pop_oracle
  # o vía CLI: ylk rotate --personas deep_mind pop_oracle

Use --skip-render on GitHub Actions CI where no GPU is available.
"""
import sys, os, json, logging, argparse, subprocess, sqlite3
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("orchestrator")


def run_produce(series_slug, series_title, tmdb_id, persona, dry_run=False):
    """Invoke produce_for_series.py as subprocess."""
    cmd = [
        sys.executable,
        "scripts/production/produce_for_series.py",
        "--series", series_title,
        "--tmdb-id", str(tmdb_id),
        "--slug", series_slug,
        "--persona", persona,
    ]
    if dry_run:
        cmd.append("--dry-run")

    log.info(f"  ▶ Running: {' '.join(cmd[2:])}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    return result.returncode == 0, result.stdout, result.stderr


def log_to_db(
    persona: str, slug: str, title: str, video_type: str,
    output_path: str = "", script: dict | None = None,
):
    """Record production in content_produced table."""
    from apps.production.content_rotator import log_produced
    conn = sqlite3.connect("data/shorts_pipeline.db")
    log_produced(
        conn, persona=persona, series_slug=slug, series_title=title,
        video_type=video_type, output_path=output_path, script=script,
    )
    conn.close()


def upload_batch_to_youtube(batch_results):
    """Optional: upload all produced videos to YouTube as unlisted."""
    import json as _json
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials

    log.info("\n" + "=" * 60)
    log.info("UPLOADING TO YOUTUBE")
    log.info("=" * 60)

    uploaded = []
    for item in batch_results:
        persona = item["persona"]
        token_path = Path(f"tokens/youtube_{persona}.json")

        if not token_path.exists():
            log.warning(f"  [{persona}] token missing — skip")
            continue

        token_data = _json.loads(token_path.read_text())
        creds = Credentials(
            token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
        )
        yt = build("youtube", "v3", credentials=creds)

        for vtype, video_info in item.get("videos", {}).items():
            path = video_info.get("path")
            if not path or not Path(path).exists():
                continue

            title = video_info.get("title", f"{item['title']} #Shorts")
            if "#Shorts" not in title:
                title += " #Shorts"

            log.info(f"  Uploading {persona}/{vtype}: {title[:60]}")
            body = {
                "snippet": {
                    "title": title[:100],
                    "description": video_info.get("description", f"{item['title']}\n\n#shorts"),
                    "tags": video_info.get("tags", ["shorts"]),
                    "categoryId": "24",
                },
                "status": {
                    "privacyStatus": "unlisted",
                    "selfDeclaredMadeForKids": False,
                },
            }
            media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
            req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

            resp = None
            while resp is None:
                status, resp = req.next_chunk()
            vid_id = resp["id"]
            url = f"https://youtu.be/{vid_id}"
            log.info(f"    ✓ {url}")
            uploaded.append({"persona": persona, "type": vtype, "url": url, "id": vid_id})

    return uploaded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Only generate scripts, no audio/video rendering")
    ap.add_argument("--skip-render", action="store_true",
                    help="Skip rendering (for CI without GPU — still generates scripts)")
    ap.add_argument("--upload-youtube", action="store_true",
                    help="Upload produced videos to YouTube as unlisted")
    ap.add_argument("--personas", nargs="+",
                    default=["deep_mind", "pop_oracle", "latam"],
                    help="Which personas to produce for")
    ap.add_argument("--cooldown-days", type=int, default=14,
                    help="Min days between same series production")
    args = ap.parse_args()

    log.info("=" * 60)
    log.info(f"CONTENT ROTATION BATCH — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 60)

    # Step 1: Plan rotation
    log.info("\nSTEP 1 — Planning rotation...")
    from apps.production.content_rotator import ContentRotator

    rotator = ContentRotator()
    batch = rotator.plan_batch(
        personas=args.personas,
        min_days_cooldown=args.cooldown_days,
    )
    rotator.close()

    if not batch:
        log.error("No candidates available in rotation. Check CATALOG and cooldowns.")
        return 1

    print("\n── ROTATION PLAN ──")
    for item in batch:
        print(f"  {item['persona']:12s} -> {item['slug']:30s} "
              f"score={item['score']:.2f} "
              f"classified={item['classified']}")

    # Save the plan
    plan_path = Path(f"outputs/rotation_plans/{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(batch, indent=2), encoding="utf-8")
    log.info(f"\nPlan saved: {plan_path}")

    if args.dry_run and not args.skip_render:
        log.info("\n--dry-run specified — running produce in dry-run mode")

    # Step 2: Produce each
    log.info("\nSTEP 2 — Producing content...")
    results = []

    for i, item in enumerate(batch, 1):
        log.info(f"\n[{i}/{len(batch)}] {item['persona']} → {item['title']}")

        if args.skip_render:
            # CI mode: only run script generation (dry-run)
            ok, stdout, stderr = run_produce(
                item["slug"], item["title"], item["tmdb_id"],
                item["persona"], dry_run=True,
            )
        else:
            ok, stdout, stderr = run_produce(
                item["slug"], item["title"], item["tmdb_id"],
                item["persona"], dry_run=args.dry_run,
            )

        if not ok:
            log.error(f"  FAILED: {stderr[-500:]}")
            continue

        # Load generated scripts
        scripts_path = Path(f"outputs/produce/{item['slug']}/scripts.json")
        scripts = {}
        if scripts_path.exists():
            scripts = json.loads(scripts_path.read_text(encoding="utf-8"))

        # Collect output video paths
        videos = {}
        for vtype in ("narration", "personality", "test"):
            vpath = Path(f"outputs/produce/{item['slug']}/{vtype}/FINAL_{vtype.upper()}.mp4")
            if vpath.exists():
                videos[vtype] = {
                    "path": str(vpath),
                    "title": f"{item['title']} — {vtype.capitalize()}",
                    "script": scripts.get(vtype, []),
                }

        # Log to DB (one entry per video_type)
        for vtype, vinfo in videos.items():
            log_to_db(
                persona=item["persona"],
                slug=item["slug"],
                title=item["title"],
                video_type=vtype,
                output_path=vinfo["path"],
                script={"segments": vinfo.get("script", [])},
            )

        # If no videos were rendered (dry-run/skip-render), still log scripts as dry
        if not videos and scripts:
            for vtype in scripts:
                log_to_db(
                    persona=item["persona"],
                    slug=item["slug"],
                    title=item["title"],
                    video_type=f"{vtype}_dry",
                    script={"segments": scripts.get(vtype, [])},
                )

        results.append({**item, "videos": videos, "scripts": scripts})

    # Step 3: Upload if requested
    if args.upload_youtube and not args.dry_run and not args.skip_render:
        upload_batch_to_youtube(results)

    # Summary
    log.info("\n" + "=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    for r in results:
        rendered = len(r.get("videos", {}))
        scripts_n = len(r.get("scripts", {}))
        log.info(f"  {r['persona']:12s} {r['slug']:30s} "
                 f"scripts={scripts_n}/3  rendered={rendered}/3")

    total_scripts = sum(len(r.get("scripts", {})) for r in results)
    total_videos = sum(len(r.get("videos", {})) for r in results)
    log.info(f"\nTotal: {total_scripts} scripts, {total_videos} videos rendered")

    # Save final report
    report_path = Path(f"outputs/rotation_plans/report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json")
    report_path.write_text(
        json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "batch": results,
            "total_scripts": total_scripts,
            "total_videos": total_videos,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(f"Report: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
