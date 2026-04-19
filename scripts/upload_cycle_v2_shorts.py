"""
Upload the 3 cycle v2 videos to YouTube as unlisted Shorts.
Deep Mind channel (Nico Flor).
"""
import sys, os, json
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

VIDEOS = [
    {
        "path": "outputs/content_cycle_v2/narration/FINAL_NARRATION.mp4",
        "title": "Berserk: The Night Everything Changed #Shorts",
        "description": (
            "The Eclipse. The most devastating moment in manga history.\n"
            "Griffith, broken and desperate, holds the Behelit — and chose power over family.\n"
            "Guts lost his arm, his eye, and everyone he loved.\n\n"
            "#berserk #manga #anime #eclipse #griffith #guts #shorts"
        ),
        "tags": ["berserk", "manga", "anime", "eclipse", "griffith", "guts", "shorts", "deepmind"],
    },
    {
        "path": "outputs/content_cycle_v2/personality/FINAL_PERSONALITY.mp4",
        "title": "Griffith Was RIGHT and You Know It #Shorts",
        "description": (
            "A deep dive into moral ambiguity.\n"
            "Griffith, Walter White, Light Yagami, Michael Corleone — same path.\n"
            "The only difference? Griffith was honest about the cost.\n\n"
            "What would you sacrifice for your dream?\n\n"
            "#berserk #breakingbad #deathnote #antihero #manga #anime #shorts"
        ),
        "tags": ["berserk", "breaking bad", "death note", "antihero", "manga", "anime", "shorts"],
    },
    {
        "path": "outputs/content_cycle_v2/test/FINAL_TEST.mp4",
        "title": "I Cannot Watch This Scene Without Crying #Shorts",
        "description": (
            "Some scenes break you every single time.\n"
            "Casca. Guts. The Band of the Hawk — a family destroyed.\n"
            "If you have ever been betrayed by someone you loved, you understand.\n\n"
            "#berserk #manga #anime #eclipse #emotional #shorts"
        ),
        "tags": ["berserk", "manga", "anime", "eclipse", "emotional", "shorts"],
    },
]


def upload(video, youtube):
    path = video["path"]
    if not Path(path).exists():
        print(f"  [SKIP] {path} — file not found")
        return None

    size_mb = Path(path).stat().st_size / 1024 / 1024
    print(f"\n▶ {video['title']}")
    print(f"  File: {path} ({size_mb:.1f} MB)")

    body = {
        "snippet": {
            "title": video["title"],
            "description": video["description"],
            "tags": video["tags"],
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    last_pct = -1
    while response is None:
        status, response = req.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct != last_pct:
                print(f"  ... {pct}%")
                last_pct = pct

    vid_id = response["id"]
    url = f"https://youtu.be/{vid_id}"
    print(f"  ✓ {url}")
    return {"id": vid_id, "url": url, "title": video["title"]}


def main():
    # Load token
    token_path = Path("tokens/youtube_deep_mind.json")
    if not token_path.exists():
        print("ERROR: tokens/youtube_deep_mind.json not found")
        sys.exit(1)

    token_data = json.loads(token_path.read_text())
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
    )

    youtube = build("youtube", "v3", credentials=creds)

    # Verify channel
    ch_resp = youtube.channels().list(part="snippet", mine=True).execute()
    chan = ch_resp.get("items", [{}])[0]
    print(f"Channel: {chan.get('snippet', {}).get('title')} ({chan.get('id')})")

    results = []
    for v in VIDEOS:
        try:
            r = upload(v, youtube)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print("UPLOADED:")
    for r in results:
        print(f"  {r['url']}  —  {r['title']}")


if __name__ == "__main__":
    main()
