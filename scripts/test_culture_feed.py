"""Test the culture feed pipeline."""
import sys
import logging
sys.path.insert(0, "src")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

from common.culture_feed import fetch_rss_headlines, fetch_trending_people, fetch_wikipedia_context

# 1. RSS
headlines = fetch_rss_headlines(max_per_feed=3)
print(f"\nRSS HEADLINES ({len(headlines)}):")
for h in headlines[:8]:
    src = h["source"]
    title = h["title"][:70]
    print(f"  [{src:15s}] {title}")

# 2. Trending people
people = fetch_trending_people()
print(f"\nTRENDING PEOPLE ({len(people)}):")
for p in people[:5]:
    print(f"  {p['name']}")

# 3. Wiki context for first person
if people:
    wiki = fetch_wikipedia_context(people[0]["name"])
    if wiki:
        print(f"\nWIKI: {wiki['name']}: {wiki['description']}")
        print(f"  {wiki['summary'][:150]}...")
