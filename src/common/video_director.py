"""
Video Director: connects narration segments to visual content.
Ensures what the voice says matches what appears on screen.

Flow:
1. Narration segments (text + emotion + duration)
2. Available pages/panels with OCR text and metadata
3. Director matches each segment to the best visual
4. Generates a timeline: [{visual, audio, transition, duration}]
5. FFmpeg renders the final video from the timeline
"""
import json
import os
import re
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ── Transition types ──────────────────────────────────────────
TRANSITIONS = {
    "fade": {"filter": "xfade=transition=fade:duration={dur}:offset={offset}"},
    "dissolve": {"filter": "xfade=transition=dissolve:duration={dur}:offset={offset}"},
    "wipeleft": {"filter": "xfade=transition=wipeleft:duration={dur}:offset={offset}"},
    "wiperight": {"filter": "xfade=transition=wiperight:duration={dur}:offset={offset}"},
    "slideup": {"filter": "xfade=transition=slideup:duration={dur}:offset={offset}"},
    "circleopen": {"filter": "xfade=transition=circleopen:duration={dur}:offset={offset}"},
    "none": None,
}

# Emotion → transition mapping
EMOTION_TRANSITIONS = {
    "dark": "dissolve",
    "epic": "wipeleft",
    "tragic": "fade",
    "hopeful": "circleopen",
    "default": "fade",
}

# Emotion → color grade
EMOTION_GRADES = {
    "dark": "eq=brightness=-0.05:saturation=0.7",
    "epic": "eq=brightness=0.02:saturation=1.2:contrast=1.1",
    "tragic": "eq=brightness=-0.08:saturation=0.5",
    "hopeful": "eq=brightness=0.05:saturation=1.1",
    "default": "null",
}


class VideoDirector:
    """Orchestrates the connection between narration and visuals."""

    def __init__(
        self,
        target_size: tuple = (1080, 1920),
        fps: int = 30,
        use_gpu: bool = True,
    ):
        self.target_size = target_size
        self.fps = fps
        self.encoder = "h264_nvenc" if use_gpu else "libx264"
        self.w, self.h = target_size

    def create_timeline(
        self,
        narration_segments: list,
        available_pages: list,
        page_ocr_texts: dict = None,
    ) -> list:
        """Match each narration segment to the best visual page/panel.

        narration_segments: [{"text": "...", "start_s": 0, "duration_s": 5, "emotion": "dark", "visual_hint": "..."}]
        available_pages: ["/path/to/page1.jpg", "/path/to/page2.jpg", ...]
        page_ocr_texts: {"/path/to/page1.jpg": "OCR text from this page", ...}

        Returns timeline: [{"visual": path, "audio_start": 0, "duration": 5, "emotion": "dark", "transition": "fade", "camera": {...}}]
        """
        if not available_pages:
            return []

        timeline = []
        used_pages = set()
        pages_per_segment = max(1, len(available_pages) // max(len(narration_segments), 1))

        for i, seg in enumerate(narration_segments):
            text = seg.get("text", "")
            emotion = seg.get("emotion", "default")
            visual_hint = seg.get("visual_hint", "")
            duration = seg.get("duration_s", 5.0)
            start = seg.get("start_s", 0)

            # Find best matching page
            best_page = self._find_best_page(
                text, visual_hint, available_pages, page_ocr_texts, used_pages
            )

            if not best_page:
                # Fallback: use pages in order
                page_idx = min(i * pages_per_segment, len(available_pages) - 1)
                best_page = available_pages[page_idx]

            used_pages.add(best_page)

            # Determine transition based on emotion change
            prev_emotion = narration_segments[i - 1].get("emotion", "default") if i > 0 else None
            transition = self._select_transition(emotion, prev_emotion, i == 0)

            # Camera movement based on emotion
            camera = self._select_camera(emotion, duration)

            timeline.append({
                "visual": best_page,
                "audio_start": start,
                "duration": duration,
                "emotion": emotion,
                "transition": transition,
                "camera": camera,
                "narration_text": text,
                "segment_index": i,
            })

        log.info(f"Timeline: {len(timeline)} segments, {sum(s['duration'] for s in timeline):.1f}s total")
        return timeline

    def _find_best_page(
        self, narration_text: str, visual_hint: str, pages: list,
        ocr_texts: dict, used: set
    ) -> Optional[str]:
        """Find the page that best matches the narration content."""
        if not ocr_texts:
            return None

        query = (narration_text + " " + visual_hint).lower()
        keywords = set(re.findall(r'\b[a-z]{4,}\b', query))

        # Remove common words
        stopwords = {"this", "that", "with", "from", "have", "been", "their", "would",
                      "could", "about", "which", "where", "when", "what", "your", "into",
                      "them", "than", "then", "some", "more", "very", "just", "like"}
        keywords -= stopwords

        best_score = -1
        best_page = None

        for page in pages:
            if page in used and len(pages) > len(used) + 1:
                continue  # Skip already used, unless running out

            page_text = (ocr_texts.get(page, "") or "").lower()
            if not page_text:
                continue

            # Score: count matching keywords
            page_words = set(re.findall(r'\b[a-z]{4,}\b', page_text))
            matches = keywords & page_words
            score = len(matches)

            # Bonus for character names
            for name in ["guts", "griffith", "casca", "band", "hawk", "eclipse",
                         "skull", "knight", "zodd", "femto", "godhand"]:
                if name in query and name in page_text:
                    score += 3

            if score > best_score:
                best_score = score
                best_page = page

        return best_page if best_score > 0 else None

    def _select_transition(self, emotion: str, prev_emotion: str, is_first: bool) -> str:
        """Select transition based on emotional shift."""
        if is_first:
            return "fade"  # Always fade in

        # Big emotional shifts get dramatic transitions
        if prev_emotion != emotion:
            if emotion == "dark":
                return "dissolve"
            elif emotion == "epic":
                return "wipeleft"
            elif emotion == "tragic":
                return "fade"
            elif emotion == "hopeful":
                return "circleopen"

        return EMOTION_TRANSITIONS.get(emotion, "fade")

    def _select_camera(self, emotion: str, duration: float) -> dict:
        """Select camera movement based on emotion."""
        if emotion == "dark":
            return {"type": "slow_zoom_in", "speed": 0.002, "start_scale": 1.0, "end_scale": 1.08}
        elif emotion == "epic":
            return {"type": "pan_and_zoom", "speed": 0.004, "start_scale": 1.05, "end_scale": 1.15}
        elif emotion == "tragic":
            return {"type": "slow_zoom_out", "speed": 0.001, "start_scale": 1.1, "end_scale": 1.0}
        elif emotion == "hopeful":
            return {"type": "gentle_pan", "speed": 0.003, "start_scale": 1.0, "end_scale": 1.05}
        return {"type": "static", "speed": 0, "start_scale": 1.0, "end_scale": 1.0}

    def render_from_timeline(
        self,
        timeline: list,
        audio_path: str,
        output_path: str,
        subtitle_path: str = None,
    ) -> str:
        """Render final video from a director timeline.

        Each segment gets its own clip with camera movement + color grade,
        then all clips are concatenated with transitions, and audio is merged.
        """
        if not timeline:
            raise ValueError("Empty timeline")

        tmpdir = tempfile.mkdtemp(prefix="director_")
        clip_paths = []

        try:
            for i, seg in enumerate(timeline):
                clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
                self._render_segment(seg, clip_path)
                if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
                    clip_paths.append(clip_path)
                else:
                    log.warning(f"Segment {i} failed to render")

            if not clip_paths:
                raise RuntimeError("No segments rendered")

            # Concatenate with transitions
            video_only = os.path.join(tmpdir, "video_only.mp4")
            self._concatenate_with_transitions(clip_paths, timeline, video_only)

            # Merge audio
            if audio_path and Path(audio_path).exists():
                self._merge_audio(video_only, audio_path, output_path, subtitle_path)
            else:
                import shutil
                shutil.copy(video_only, output_path)

        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

        if Path(output_path).exists():
            size_kb = Path(output_path).stat().st_size // 1024
            log.info(f"Director output: {output_path} ({size_kb}KB)")

        return output_path

    def _render_segment(self, seg: dict, output: str):
        """Render a single segment: image → video with camera movement + color grade."""
        visual = seg["visual"]
        duration = seg["duration"]
        emotion = seg["emotion"]
        camera = seg["camera"]

        frames = int(duration * self.fps)
        start_scale = camera["start_scale"]
        end_scale = camera["end_scale"]

        # Color grade
        grade = EMOTION_GRADES.get(emotion, "null")

        # Build zoompan filter for camera movement
        # zoompan: zoom from start_scale to end_scale over duration
        zoom_expr = f"'{start_scale}+({end_scale}-{start_scale})*on/{frames}'"
        # Center the zoom
        x_expr = f"'(iw-iw/zoom)/2'"
        y_expr = f"'(ih-ih/zoom)/2'"

        vf = (
            f"scale={self.w * 2}:{self.h * 2}:flags=lanczos,"
            f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
            f":d={frames}:s={self.w}x{self.h}:fps={self.fps},"
            f"{grade}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", visual,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", self.encoder,
            "-b:v", "5M",
            "-pix_fmt", "yuv420p",
            "-an",
            output,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            # Fallback: simple scale without zoompan
            cmd_simple = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", visual,
                "-vf", f"scale={self.w}:{self.h}:force_original_aspect_ratio=decrease,"
                       f"pad={self.w}:{self.h}:(ow-iw)/2:(oh-ih)/2:black,{grade}",
                "-t", str(duration),
                "-c:v", self.encoder, "-b:v", "5M",
                "-pix_fmt", "yuv420p", "-an",
                output,
            ]
            subprocess.run(cmd_simple, capture_output=True, timeout=60)

    def _concatenate_with_transitions(self, clips: list, timeline: list, output: str):
        """Concatenate clips with xfade transitions between them."""
        if len(clips) == 1:
            import shutil
            shutil.copy(clips[0], output)
            return

        # For xfade, we need to chain filters
        # Simple approach: concat without transitions if xfade is complex
        # Use xfade for pairs
        if len(clips) <= 6:
            self._xfade_chain(clips, timeline, output)
        else:
            # Too many clips for xfade chain, use simple concat
            self._simple_concat(clips, output)

    def _xfade_chain(self, clips: list, timeline: list, output: str):
        """Chain xfade transitions between clips."""
        transition_dur = 0.3  # 300ms transitions

        inputs = []
        for c in clips:
            inputs.extend(["-i", c])

        # Build filter chain
        n = len(clips)
        filter_parts = []
        offset = 0

        for i in range(n - 1):
            seg_dur = timeline[i]["duration"] if i < len(timeline) else 5.0
            offset += seg_dur - transition_dur

            transition_type = timeline[i + 1]["transition"] if i + 1 < len(timeline) else "fade"
            if transition_type not in ["fade", "dissolve", "wipeleft", "wiperight", "slideup", "circleopen"]:
                transition_type = "fade"

            if i == 0:
                src_a = "[0:v]"
            else:
                src_a = f"[v{i}]"

            src_b = f"[{i + 1}:v]"
            out_label = f"[v{i + 1}]" if i < n - 2 else "[vout]"

            filter_parts.append(
                f"{src_a}{src_b}xfade=transition={transition_type}:duration={transition_dur}:offset={offset:.2f}{out_label}"
            )

        filter_str = ";".join(filter_parts)

        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", filter_str,
            "-map", "[vout]",
            "-c:v", self.encoder, "-b:v", "5M",
            "-pix_fmt", "yuv420p",
            output,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.warning(f"xfade failed, falling back to simple concat: {result.stderr[:200]}")
            self._simple_concat(clips, output)

    def _simple_concat(self, clips: list, output: str):
        """Simple concatenation without transitions."""
        tmpdir = Path(clips[0]).parent
        concat_file = str(tmpdir / "concat.txt")
        with open(concat_file, "w") as f:
            for c in clips:
                f.write(f"file '{c}'\n")

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_file, "-c", "copy", output,
        ], capture_output=True, timeout=60)

    def _merge_audio(self, video: str, audio: str, output: str, subtitle: str = None):
        """Merge audio track with video, optionally burn subtitles."""
        vf_filters = []

        if subtitle and Path(subtitle).exists():
            sub_escaped = subtitle.replace(":", "\\:")
            vf_filters.append(f"ass='{sub_escaped}'")

        cmd = ["ffmpeg", "-y", "-i", video, "-i", audio]

        if vf_filters:
            cmd.extend(["-vf", ",".join(vf_filters), "-c:v", self.encoder, "-b:v", "5M"])
        else:
            cmd.extend(["-c:v", "copy"])

        cmd.extend([
            "-map", "0:v", "-map", "1:a",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            output,
        ])

        subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def direct_short(
    narration_segments: list,
    available_pages: list,
    audio_path: str,
    output_path: str,
    page_ocr_texts: dict = None,
    subtitle_path: str = None,
    use_gpu: bool = True,
) -> str:
    """High-level function: direct a complete Short.

    Connects narration to visuals, selects transitions and camera,
    renders the final video.
    """
    director = VideoDirector(use_gpu=use_gpu)
    timeline = director.create_timeline(narration_segments, available_pages, page_ocr_texts)

    if not timeline:
        raise RuntimeError("Director could not create timeline")

    log.info(f"Directing Short: {len(timeline)} segments")
    for i, seg in enumerate(timeline):
        log.info(f"  [{i}] {seg['emotion']:8s} | {seg['duration']:.1f}s | "
                 f"{seg['transition']:10s} | {Path(seg['visual']).name} | "
                 f"{seg['narration_text'][:50]}...")

    return director.render_from_timeline(timeline, audio_path, output_path, subtitle_path)
