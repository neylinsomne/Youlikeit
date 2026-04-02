"""Check English manga availability on MangaDex."""
import sys
sys.path.insert(0, "src")
from common.mangadex import search_manga, get_chapters

titles = ["Berserk", "One Piece", "Death Note", "Attack on Titan", "Chainsaw Man", "Vinland Saga", "Naruto"]

for title in titles:
    m = search_manga(title)
    if m:
        chs = get_chapters(m["id"], lang="en", limit=50)
        print(f"{title:20s} | {len(chs):3d} EN chapters")
        if chs:
            ch = chs[0]
            print(f"  First: Ch {ch.get('chapter', '?')} - {ch.get('title', 'untitled')}")
    else:
        print(f"{title:20s} | NOT FOUND")
