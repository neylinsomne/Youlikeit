"""Upload all videos from outputs/produce/{slug}/ to YouTube as unlisted Shorts."""
import sys, os, json, argparse
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials


def upload_one(yt, path, title, description, tags):
    size_mb = Path(path).stat().st_size / 1024 / 1024
    print(f"\n▶ {title}")
    print(f"  File: {path} ({size_mb:.1f} MB)")
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
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
    last = -1
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct != last:
                print(f"  ... {pct}%")
                last = pct
    vid = resp["id"]
    url = f"https://youtu.be/{vid}"
    print(f"  ✓ {url}")
    return {"id": vid, "url": url, "title": title}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--persona", default="deep_mind")
    ap.add_argument("--series-name", default="")
    args = ap.parse_args()

    slug = args.slug
    series_name = args.series_name or slug.replace("_", " ").title()
    persona = args.persona

    token_path = Path(f"tokens/youtube_{persona}.json")
    if not token_path.exists():
        print(f"ERROR: {token_path} not found")
        sys.exit(1)

    token_data = json.loads(token_path.read_text())
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
    )
    yt = build("youtube", "v3", credentials=creds)

    ch = yt.channels().list(part="snippet", mine=True).execute()
    ch_title = ch.get("items", [{}])[0].get("snippet", {}).get("title", "?")
    print(f"Channel: {ch_title}")

    results = []
    titles = {
        "narration": f"{series_name}: The Story That Changed Everything #Shorts",
        "personality": f"Why {series_name} Is Deeper Than You Think #Shorts",
        "test": f"This {series_name} Moment Broke Me #Shorts",
    }

    for vtype in ("narration", "personality", "test"):
        path = Path(f"outputs/produce/{slug}/{vtype}/FINAL_{vtype.upper()}.mp4")
        if not path.exists():
            print(f"[SKIP] {path} not found")
            continue

        title = titles.get(vtype, f"{series_name} #Shorts")
        desc = (
            f"A {vtype} piece about {series_name}.\n"
            f"Part of the Deep Mind analysis series.\n\n"
            f"#{slug.replace('_', '')} #anime #manga #shorts #deepmind"
        )
        tags = [slug.replace("_", ""), "anime", "manga", "shorts", persona, vtype]
        try:
            r = upload_one(yt, str(path), title, desc, tags)
            results.append(r)
        except Exception as e:
            print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print(f"UPLOADED TO {ch_title}:")
    for r in results:
        print(f"  {r['url']}  —  {r['title']}")


if __name__ == "__main__":
    main()
