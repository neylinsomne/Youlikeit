"""
Panel Matcher: picks the best manga/image page for each narration segment.

Instead of assigning pages sequentially, this module:
1. Describes each available image (via Gemini Vision or filename heuristics)
2. Scores each image against each narration segment
3. Assigns the best match per segment (no repeats unless necessary)

Works with manga panels, movie stills, poster crops, or any image set.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)


# ── Image description cache ─────────────────────────────────────

_description_cache: dict[str, str] = {}


def describe_image_gemini(image_path: str) -> str:
    """Use Gemini Vision to describe a manga page / image."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return _describe_from_filename(image_path)

    cache_key = str(image_path)
    if cache_key in _description_cache:
        return _description_cache[cache_key]

    try:
        img_bytes = Path(image_path).read_bytes()
        b64 = base64.b64encode(img_bytes).decode("utf-8")

        # Detect mime type
        suffix = Path(image_path).suffix.lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(
            suffix.lstrip("."), "image/jpeg"
        )

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
            json={
                "contents": [{
                    "parts": [
                        {"text": "Describe this manga/comic page in 2-3 sentences. Focus on: characters visible, action happening, emotion conveyed, setting. Be specific about what you SEE."},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 150},
            },
            timeout=20,
        )

        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            _description_cache[cache_key] = text
            return text

    except Exception as e:
        log.warning(f"Gemini Vision failed for {Path(image_path).name}: {e}")

    return _describe_from_filename(image_path)


def _describe_from_filename(image_path: str) -> str:
    """Fallback: guess content from filename and directory name."""
    path = Path(image_path)
    dir_name = path.parent.name.lower()
    file_name = path.stem.lower()

    desc_parts = []
    if "eclipse" in dir_name:
        desc_parts.append("Eclipse scene from Berserk")
    elif "golden_age" in dir_name:
        desc_parts.append("Golden Age arc scene")
    elif "berserk" in dir_name:
        desc_parts.append("Berserk manga panel")

    # Page number hints
    num = re.search(r"(\d+)", file_name)
    if num:
        page_num = int(num.group(1))
        desc_parts.append(f"page {page_num}")

    return " — ".join(desc_parts) if desc_parts else f"manga panel from {dir_name}"


def describe_all_images(image_paths: list[str], use_gemini: bool = True) -> list[dict]:
    """Describe all images. Returns [{path, description}]."""
    results = []
    for i, path in enumerate(image_paths):
        if use_gemini and os.getenv("GEMINI_API_KEY"):
            desc = describe_image_gemini(path)
        else:
            desc = _describe_from_filename(path)
        results.append({"path": path, "description": desc, "index": i})
        log.info(f"  img[{i}]: {Path(path).name} → {desc[:60]}")
    return results


# ── Matching ────────────────────────────────────────────────────

def match_panels_to_segments(
    image_descriptions: list[dict],
    narration_segments: list[dict],
    use_llm: bool = True,
) -> list[dict]:
    """
    Match each narration segment to the best image.

    Returns list of segments with 'matched_image' added.
    """
    if not image_descriptions:
        return narration_segments

    if use_llm and os.getenv("GEMINI_API_KEY"):
        return _match_with_llm(image_descriptions, narration_segments)
    else:
        return _match_with_keywords(image_descriptions, narration_segments)


def _match_with_llm(images: list[dict], segments: list[dict]) -> list[dict]:
    """Use Gemini to match images to narration segments."""
    key = os.getenv("GEMINI_API_KEY", "")

    img_list = "\n".join(
        f"[IMG_{img['index']}] {img['description']}"
        for img in images
    )

    seg_list = "\n".join(
        f"[SEG_{i}] {seg.get('text', seg.get('narration_text', ''))}"
        for i, seg in enumerate(segments)
    )

    prompt = f"""Match each narration segment to the most fitting image.
Each image should be used AT MOST ONCE if possible (spread them out).
If there are more segments than images, you may reuse images but try to pick different ones.

IMAGES:
{img_list}

NARRATION SEGMENTS:
{seg_list}

Return JSON array (no markdown):
[
  {{"segment": 0, "image": 2, "reason": "brief reason"}},
  {{"segment": 1, "image": 0, "reason": "brief reason"}},
  ...
]"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3},
            },
            timeout=20,
        )

        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json?\s*", "", text).strip().rstrip("`")
        matches = json.loads(text)

        # Apply matches
        for match in matches:
            seg_idx = match.get("segment", 0)
            img_idx = match.get("image", 0)
            if 0 <= seg_idx < len(segments) and 0 <= img_idx < len(images):
                segments[seg_idx]["matched_image"] = images[img_idx]["path"]
                segments[seg_idx]["match_reason"] = match.get("reason", "")

        # Fill any unmatched with round-robin
        _fill_unmatched(segments, images)

        return segments

    except Exception as e:
        log.warning(f"LLM matching failed: {e}, falling back to keywords")
        return _match_with_keywords(images, segments)


def _match_with_keywords(images: list[dict], segments: list[dict]) -> list[dict]:
    """Fallback: match by keyword overlap between narration and image description.

    If keyword scoring yields 0 (descriptions are generic, no LLM was used),
    fall back to a deterministic round-robin so each segment gets a *different*
    image instead of the matcher collapsing to the first one for all.
    """
    used_paths: set[str] = set()
    for i, seg in enumerate(segments):
        text = seg.get("text", seg.get("narration_text", "")).lower()
        words = set(re.findall(r"\w{4,}", text))

        best_score = 0
        best_img = None

        for img in images:
            desc_words = set(re.findall(r"\w{4,}", img["description"].lower()))
            overlap = len(words & desc_words)

            # Bonus for emotion/scene matching
            for keyword, bonus in [
                ("fight", 3), ("battle", 3), ("sword", 3),
                ("cry", 2), ("tears", 2), ("sad", 2),
                ("sacrifice", 4), ("betray", 4), ("eclipse", 5),
                ("dark", 2), ("blood", 3), ("death", 3),
                ("dream", 2), ("hope", 2), ("light", 1),
            ]:
                if keyword in text and keyword in img["description"].lower():
                    overlap += bonus

            if overlap > best_score:
                best_score = overlap
                best_img = img

        # Only accept the keyword match if there is real overlap. Otherwise let
        # _fill_unmatched assign a unique image via round-robin.
        if best_img and best_score > 0 and best_img["path"] not in used_paths:
            seg["matched_image"] = best_img["path"]
            seg["match_reason"] = f"keyword overlap ({best_score})"
            used_paths.add(best_img["path"])

    _fill_unmatched(segments, images)
    return segments


def _fill_unmatched(segments: list[dict], images: list[dict]):
    """Fill unmatched segments with round-robin from available images."""
    used = set()
    for seg in segments:
        if seg.get("matched_image"):
            used.add(seg["matched_image"])

    available = [img for img in images if img["path"] not in used]
    if not available:
        available = list(images)  # All used, recycle

    idx = 0
    for seg in segments:
        if not seg.get("matched_image"):
            seg["matched_image"] = available[idx % len(available)]["path"]
            seg["match_reason"] = "round-robin fill"
            idx += 1


# ── Convenience function ────────────────────────────────────────

def select_panels_for_narration(
    image_dir: str | list[str],
    narration_segments: list[dict],
    use_gemini: bool = True,
) -> list[dict]:
    """
    All-in-one: load images, describe them, match to narration.

    Args:
        image_dir: directory path or list of image paths
        narration_segments: [{text, emotion, ...}]

    Returns:
        narration_segments with 'matched_image' added to each
    """
    # Collect images
    if isinstance(image_dir, list):
        image_paths = image_dir
    else:
        dir_path = Path(image_dir)
        image_paths = sorted(str(p) for p in dir_path.rglob("*.[jp][pn]g"))

    if not image_paths:
        log.warning("No images found")
        return narration_segments

    log.info(f"Describing {len(image_paths)} images...")
    descriptions = describe_all_images(image_paths, use_gemini=use_gemini)

    log.info(f"Matching {len(narration_segments)} segments to {len(descriptions)} images...")
    matched = match_panels_to_segments(descriptions, narration_segments, use_llm=use_gemini)

    for seg in matched:
        img = seg.get("matched_image", "?")
        reason = seg.get("match_reason", "")
        log.info(f"  '{seg.get('text', '')[:40]}' → {Path(img).name} ({reason})")

    return matched
