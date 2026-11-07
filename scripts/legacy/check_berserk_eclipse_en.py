"""Check if Berserk Eclipse chapters are available in English."""
import sys
sys.path.insert(0, "src")
from integrations.mangadex import search_manga, get_chapters

m = search_manga("Berserk")
if m:
    # Get chapters around the Eclipse (73-90)
    for offset in [0, 50, 70, 80]:
        chs = get_chapters(m["id"], lang="en", limit=20, offset=offset)
        if chs:
            print(f"\nOffset {offset}:")
            for ch in chs:
                num = ch.get("chapter", "?")
                title = ch.get("title", "untitled")
                print(f"  Ch {num}: {title}")
        else:
            print(f"\nOffset {offset}: no chapters")
