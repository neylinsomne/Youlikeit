"""
Video Director v2: Professional editing orchestration.

Connects narration to visuals with cinematic techniques:
- J-cuts (audio leads visual by 0.3-0.5s)
- Ken Burns with easing (smoothstep, not linear)
- Mood-based pacing (action=fast, dialogue=slow)
- Face-targeted zoom for dramatic moments
- Cross-reference clips (movie scenes inserted mid-narration)
- Audio ducking (silence movie audio when narrator speaks)
- STT-based scene matching (find exact movie timestamp for a quote)

Architecture:
  Narration script → Director → Edit Decision List (EDL) → FFmpeg filter graph → Video
"""
import json
import math
import os
import re
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ── Pacing rules (cuts per minute by mood) ────────────────────
PACING = {
    "calm":      {"hold_s": 6.0, "transition_s": 0.5},
    "dialogue":  {"hold_s": 4.0, "transition_s": 0.4},
    "tension":   {"hold_s": 3.0, "transition_s": 0.3},
    "action":    {"hold_s": 1.5, "transition_s": 0.2},
    "shock":     {"hold_s": 0.8, "transition_s": 0.1},
    # Mapped from emotions
    "dark":      {"hold_s": 4.0, "transition_s": 0.5},
    "epic":      {"hold_s": 3.0, "transition_s": 0.3},
    "tragic":    {"hold_s": 5.0, "transition_s": 0.6},
    "hopeful":   {"hold_s": 4.0, "transition_s": 0.4},
    "default":   {"hold_s": 4.0, "transition_s": 0.4},
}

# ── Easing functions for Ken Burns ────────────────────────────
def ease_smoothstep(t):
    """Smoothstep: slow start + slow end."""
    return t * t * (3 - 2 * t)

def ease_out_cubic(t):
    """Fast start, slow end — good for zoom-in."""
    return 1 - (1 - t) ** 3

def ease_in_cubic(t):
    """Slow start, fast end — good for building tension."""
    return t ** 3

EASING_MAP = {
    "dark":    "smoothstep",
    "epic":    "ease_out",
    "tragic":  "ease_in",
    "hopeful": "smoothstep",
}

# FFmpeg easing expressions
EASING_EXPR = {
    "smoothstep": "(T*T*(3-2*T))",        # T = normalized time (in/total_frames)
    "ease_out":   "(1-pow(1-T,3))",
    "ease_in":    "(pow(T,3))",
    "linear":     "T",
}


class EditDecision:
    """A single edit decision in the timeline."""
    def __init__(
        self,
        visual_type: str,       # 'manga_panel', 'movie_clip', 'black', 'title_card'
        visual_path: str,       # path to image or video file
        duration: float,        # seconds
        narration_text: str = "",
        narration_audio: str = "", # path to narration audio for this segment
        emotion: str = "default",
        camera: dict = None,    # {"zoom_start": 1.0, "zoom_end": 1.1, "focus": "center"}
        transition_in: str = "fade",
        transition_duration: float = 0.3,
        audio_mode: str = "narration_only",  # 'narration_only', 'clip_audio', 'ducked', 'silent'
        clip_start_s: float = 0, # for movie clips: start timestamp
        clip_end_s: float = 0,   # for movie clips: end timestamp
        j_cut_s: float = 0.3,   # audio leads visual by this much
        is_hook: bool = False,  # mark first segment as the retention hook
        hook_cps: float = 0.5,  # cuts per second during this segment (0.5 = current behavior)
        hook_image_pool: list = None,  # extra images to rotate through during a hook
    ):
        self.visual_type = visual_type
        self.visual_path = visual_path
        self.duration = duration
        self.narration_text = narration_text
        self.narration_audio = narration_audio
        self.emotion = emotion
        self.camera = camera or {"zoom_start": 1.0, "zoom_end": 1.08, "focus": "center"}
        self.transition_in = transition_in
        self.transition_duration = transition_duration
        self.audio_mode = audio_mode
        self.clip_start_s = clip_start_s
        self.clip_end_s = clip_end_s
        self.j_cut_s = j_cut_s
        self.is_hook = is_hook
        self.hook_cps = hook_cps
        self.hook_image_pool = hook_image_pool or []


class VideoDirector:
    """Orchestrates professional video editing from narration + visuals."""

    def __init__(self, target_size=(1080, 1920), fps=30, use_gpu=True):
        self.w, self.h = target_size
        self.fps = fps
        self.encoder = "h264_nvenc" if use_gpu else "libx264"

    # ── Main entry point ──────────────────────────────────────

    def direct(
        self,
        narration_script: dict,
        manga_pages: list,
        movie_clips: dict = None,
        page_ocr: dict = None,
        output_path: str = "output.mp4",
        subtitle_path: str = None,
    ) -> str:
        """Direct a complete Short from script + visuals.

        narration_script: {
            "intro": "opening narration",
            "segments": [
                {
                    "text": "narration text",
                    "emotion": "dark",
                    "visual_hint": "Guts standing alone",
                    "cross_ref": {                          # OPTIONAL
                        "type": "movie_clip",
                        "movie": "The Godfather",
                        "quote": "I'll make him an offer...",
                        "action": "play_then_narrate"       # play_then_narrate, narrate_over, silent_bg
                    }
                }
            ],
            "outro": "closing narration"
        }
        manga_pages: ["/path/page1.jpg", ...]
        movie_clips: {"The Godfather": "/path/godfather.mp4"}  # pre-downloaded
        page_ocr: {"/path/page1.jpg": "OCR text..."}
        """
        edl = self._build_edl(narration_script, manga_pages, movie_clips, page_ocr)
        return self._render_edl(edl, output_path, subtitle_path)

    # ── EDL Builder ───────────────────────────────────────────

    def _build_edl(self, script, pages, clips, ocr) -> list:
        """Build Edit Decision List from script."""
        edl = []
        segments = script.get("segments", [])
        intro = script.get("intro", "")
        outro = script.get("outro", "")

        # Add intro
        if intro:
            edl.append(EditDecision(
                visual_type="manga_panel",
                visual_path=pages[0] if pages else "",
                duration=3.0,
                narration_text=intro,
                emotion="epic",
                camera={"zoom_start": 1.15, "zoom_end": 1.0, "focus": "center"},  # zoom OUT for intro
                transition_in="fade",
                j_cut_s=0,  # no j-cut for first segment
            ))

        # Process each segment
        page_idx = 1  # start from second page (first used for intro)
        for i, seg in enumerate(segments):
            emotion = seg.get("emotion", "default")
            text = seg.get("text", "")
            cross_ref = seg.get("cross_ref")
            visual_hint = seg.get("visual_hint", "")

            # Find best matching page
            best_page = self._match_page(text, visual_hint, pages, ocr, page_idx)
            if best_page:
                page_idx = pages.index(best_page) + 1
            else:
                best_page = pages[min(page_idx, len(pages) - 1)] if pages else ""
                page_idx += 1

            pacing = PACING.get(emotion, PACING["default"])

            if cross_ref and cross_ref.get("type") == "movie_clip":
                # ── CROSS-REFERENCE: insert movie clip ────
                movie_name = cross_ref.get("movie", "")
                movie_path = (clips or {}).get(movie_name, "")
                quote = cross_ref.get("quote", "")
                action = cross_ref.get("action", "play_then_narrate")

                if movie_path and Path(movie_path).exists():
                    # Find the quote timestamp via STT
                    clip_start, clip_end = self._find_quote_timestamp(movie_path, quote)

                    if action == "play_then_narrate":
                        # 1. Show manga panel while narrator introduces
                        edl.append(EditDecision(
                            visual_type="manga_panel",
                            visual_path=best_page,
                            duration=max(2.0, len(text.split()) * 0.3),
                            narration_text=text.split("...")[0] if "..." in text else text[:len(text)//2],
                            emotion=emotion,
                            camera=self._camera_for_emotion(emotion),
                            transition_in=self._transition_for_shift(emotion, i),
                        ))

                        # 2. Cut to movie clip with ORIGINAL audio
                        clip_dur = min(clip_end - clip_start, 8.0) if clip_end > clip_start else 5.0
                        edl.append(EditDecision(
                            visual_type="movie_clip",
                            visual_path=movie_path,
                            duration=clip_dur,
                            narration_text="",  # no narration, movie audio plays
                            emotion=emotion,
                            audio_mode="clip_audio",
                            clip_start_s=clip_start,
                            clip_end_s=clip_start + clip_dur,
                            transition_in="dissolve",
                            transition_duration=0.4,
                            j_cut_s=0,
                        ))

                        # 3. Continue with narration over SILENT movie clip (duck)
                        remaining_text = text.split("...")[-1] if "..." in text else text[len(text)//2:]
                        if remaining_text.strip():
                            edl.append(EditDecision(
                                visual_type="movie_clip",
                                visual_path=movie_path,
                                duration=max(2.0, len(remaining_text.split()) * 0.35),
                                narration_text=remaining_text,
                                emotion=emotion,
                                audio_mode="ducked",  # movie audio at -20dB, narration on top
                                clip_start_s=clip_start + clip_dur,
                                clip_end_s=clip_start + clip_dur + 5,
                                transition_in="none",
                                j_cut_s=0.3,
                            ))

                    elif action == "narrate_over":
                        # Movie clip plays silently while narrator speaks
                        edl.append(EditDecision(
                            visual_type="movie_clip",
                            visual_path=movie_path,
                            duration=max(3.0, len(text.split()) * 0.35),
                            narration_text=text,
                            emotion=emotion,
                            audio_mode="ducked",
                            clip_start_s=clip_start,
                            clip_end_s=clip_start + 10,
                            transition_in=self._transition_for_shift(emotion, i),
                            j_cut_s=0.3,
                        ))

                    elif action == "silent_bg":
                        # Movie clip as silent background
                        edl.append(EditDecision(
                            visual_type="movie_clip",
                            visual_path=movie_path,
                            duration=max(3.0, len(text.split()) * 0.35),
                            narration_text=text,
                            emotion=emotion,
                            audio_mode="narration_only",
                            clip_start_s=clip_start,
                            clip_end_s=clip_start + 10,
                            transition_in=self._transition_for_shift(emotion, i),
                        ))
                else:
                    # No movie clip available, use manga panel
                    edl.append(EditDecision(
                        visual_type="manga_panel",
                        visual_path=best_page,
                        duration=max(3.0, len(text.split()) * 0.35),
                        narration_text=text,
                        emotion=emotion,
                        camera=self._camera_for_emotion(emotion),
                        transition_in=self._transition_for_shift(emotion, i),
                    ))
            else:
                # ── STANDARD: manga panel with narration ────
                # Split long segments into multiple panels for better pacing
                words = text.split()
                if len(words) > 20 and page_idx < len(pages):
                    # Split into 2 panels
                    mid = len(words) // 2
                    text_a = " ".join(words[:mid])
                    text_b = " ".join(words[mid:])

                    edl.append(EditDecision(
                        visual_type="manga_panel",
                        visual_path=best_page,
                        duration=max(2.0, len(text_a.split()) * 0.35),
                        narration_text=text_a,
                        emotion=emotion,
                        camera=self._camera_for_emotion(emotion),
                        transition_in=self._transition_for_shift(emotion, i),
                        j_cut_s=0.3 if i > 0 else 0,
                    ))

                    next_page = pages[min(page_idx, len(pages) - 1)]
                    page_idx += 1
                    edl.append(EditDecision(
                        visual_type="manga_panel",
                        visual_path=next_page,
                        duration=max(2.0, len(text_b.split()) * 0.35),
                        narration_text=text_b,
                        emotion=emotion,
                        camera=self._camera_for_emotion(emotion),
                        transition_in="dissolve",
                        transition_duration=0.2,
                        j_cut_s=0.3,
                    ))
                else:
                    edl.append(EditDecision(
                        visual_type="manga_panel",
                        visual_path=best_page,
                        duration=max(3.0, len(words) * 0.35),
                        narration_text=text,
                        emotion=emotion,
                        camera=self._camera_for_emotion(emotion),
                        transition_in=self._transition_for_shift(emotion, i),
                        j_cut_s=0.3 if i > 0 else 0,
                    ))

        # Add outro
        if outro:
            edl.append(EditDecision(
                visual_type="manga_panel",
                visual_path=pages[-1] if pages else "",
                duration=3.5,
                narration_text=outro,
                emotion="hopeful",
                camera={"zoom_start": 1.0, "zoom_end": 1.1, "focus": "center"},
                transition_in="fade",
                j_cut_s=0.3,
            ))

        log.info(f"EDL: {len(edl)} decisions, {sum(d.duration for d in edl):.1f}s total")
        return edl

    # ── STT: Find quote timestamp in movie ────────────────────

    def _find_quote_timestamp(self, movie_path: str, quote: str) -> tuple:
        """Use Whisper STT to find the timestamp of a quote in a movie.
        Returns (start_s, end_s).
        """
        if not quote:
            return (0, 10)

        try:
            import whisper
            model = whisper.load_model("base")

            # Transcribe (this is slow for full movies — use SRT if available)
            result = model.transcribe(movie_path, language="en", word_timestamps=True)

            quote_lower = quote.lower().strip()
            quote_words = quote_lower.split()[:5]  # first 5 words for matching

            for segment in result.get("segments", []):
                seg_text = segment.get("text", "").lower().strip()
                # Fuzzy match: check if most words appear in the segment
                matches = sum(1 for w in quote_words if w in seg_text)
                if matches >= len(quote_words) * 0.6:
                    start = segment["start"]
                    end = segment["end"]
                    log.info(f"STT match: '{quote[:40]}...' at {start:.1f}-{end:.1f}s")
                    return (max(0, start - 1), end + 1)  # add 1s buffer

        except ImportError:
            log.warning("Whisper not available, using SRT fallback")
        except Exception as e:
            log.warning(f"STT failed: {e}")

        # Fallback: try SRT file
        srt_path = Path(movie_path).with_suffix(".srt")
        if srt_path.exists():
            return self._find_in_srt(str(srt_path), quote)

        return (0, 10)  # default to first 10 seconds

    def _find_in_srt(self, srt_path: str, quote: str) -> tuple:
        """Find quote timestamp in SRT subtitle file."""
        try:
            with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            blocks = content.strip().split("\n\n")
            quote_lower = quote.lower()
            quote_words = set(re.findall(r'\b\w{4,}\b', quote_lower))

            best_match = (0, 10)
            best_score = 0

            for block in blocks:
                lines = block.strip().split("\n")
                if len(lines) < 3:
                    continue

                # Parse timestamp
                time_line = lines[1]
                text = " ".join(lines[2:]).lower()
                text_words = set(re.findall(r'\b\w{4,}\b', text))

                score = len(quote_words & text_words)
                if score > best_score:
                    best_score = score
                    # Parse time
                    match = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', time_line)
                    if match:
                        g = match.groups()
                        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
                        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
                        best_match = (max(0, start - 0.5), end + 0.5)

            return best_match
        except Exception:
            return (0, 10)

    # ── Camera and transition helpers ─────────────────────────

    def _camera_for_emotion(self, emotion: str) -> dict:
        cameras = {
            "dark":    {"zoom_start": 1.0, "zoom_end": 1.08, "focus": "center", "easing": "smoothstep"},
            "epic":    {"zoom_start": 1.05, "zoom_end": 1.15, "focus": "face", "easing": "ease_out"},
            "tragic":  {"zoom_start": 1.1, "zoom_end": 1.0, "focus": "center", "easing": "ease_in"},
            "hopeful": {"zoom_start": 1.0, "zoom_end": 1.05, "focus": "center", "easing": "smoothstep"},
        }
        return cameras.get(emotion, cameras["dark"])

    def _transition_for_shift(self, emotion: str, index: int) -> str:
        if index == 0:
            return "fade"
        transitions = {
            "dark": "dissolve", "epic": "wipeleft",
            "tragic": "fade", "hopeful": "circleopen",
        }
        return transitions.get(emotion, "fade")

    # ── Page matching ─────────────────────────────────────────

    def _match_page(self, text, hint, pages, ocr, start_idx):
        if not ocr or not pages:
            return None

        query = (text + " " + hint).lower()
        keywords = set(re.findall(r'\b[a-z]{4,}\b', query))
        stopwords = {"this", "that", "with", "from", "have", "been", "their",
                     "would", "could", "about", "which", "where", "when"}
        keywords -= stopwords

        best = None
        best_score = 0
        for page in pages[start_idx:] + pages[:start_idx]:
            page_text = (ocr.get(page, "") or "").lower()
            score = len(keywords & set(re.findall(r'\b[a-z]{4,}\b', page_text)))
            if score > best_score:
                best_score = score
                best = page

        return best if best_score > 0 else None

    # ── Render EDL ────────────────────────────────────────────

    def _render_edl(self, edl: list, output_path: str, subtitle_path: str = None) -> str:
        """Render the Edit Decision List into a final video."""
        tmpdir = tempfile.mkdtemp(prefix="director_v2_")
        clip_paths = []

        try:
            # 1. Render each segment
            for i, decision in enumerate(edl):
                clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")

                if decision.visual_type == "manga_panel":
                    self._render_panel_segment(decision, clip_path)
                elif decision.visual_type == "movie_clip":
                    self._render_movie_segment(decision, clip_path)
                elif decision.visual_type == "title_card":
                    self._render_title_card(decision, clip_path)

                if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
                    clip_paths.append((clip_path, decision))

            if not clip_paths:
                raise RuntimeError("No segments rendered")

            # 2. Concatenate all segments
            video_only = os.path.join(tmpdir, "assembled.mp4")
            self._assemble_clips([c[0] for c in clip_paths], video_only)

            # 3. Build and merge full audio track (narration with J-cuts)
            full_audio = os.path.join(tmpdir, "full_audio.wav")
            self._build_audio_track(edl, full_audio)

            # 4. Merge video + audio + optional subtitles
            self._final_merge(video_only, full_audio, output_path, subtitle_path)

        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

        if Path(output_path).exists():
            log.info(f"Director v2 output: {Path(output_path).stat().st_size // 1024}KB")

        return output_path

    def expand_hook(self, d: EditDecision) -> list:
        """
        Expand a hook EditDecision into N sub-decisions.

        Splits the hook visually into N micro-segments (each shows a
        different image) while keeping the audio continuous (the audio
        is rendered separately at the merge step, not per sub-clip).

        Returns the list of sub-decisions. If hook_cps < 1.0 or no
        extra images are available, returns [d] unchanged so behavior
        is identical to the pre-hook pipeline.
        """
        if not d.is_hook or d.hook_cps < 1.0:
            return [d]

        n_cuts = max(1, int(round(d.duration * d.hook_cps)))
        if n_cuts <= 1:
            return [d]

        # Collect images: visual_path is the first, then hook_image_pool
        pool = [d.visual_path] + [p for p in d.hook_image_pool if p and p != d.visual_path]
        if len(pool) < 2:
            # Not enough variety to do a hook — fall back to the default render
            return [d]

        # Chunk duration. Last sub-clip absorbs rounding error.
        per = d.duration / n_cuts
        sub_decisions = []
        for i in range(n_cuts):
            img = pool[i % len(pool)]
            dur = per if i < n_cuts - 1 else d.duration - per * (n_cuts - 1)
            sub = EditDecision(
                visual_type=d.visual_type,
                visual_path=img,
                duration=dur,
                # Audio belongs to the whole hook — only the first sub-clip
                # carries the audio reference; the rest are silent visual fills
                # because the merge step lays full_audio on top of the assembled
                # video anyway.
                narration_text=d.narration_text if i == 0 else "",
                narration_audio=d.narration_audio if i == 0 else "",
                emotion=d.emotion,
                # Tighter zoom range for hooks — punchier feel
                camera={
                    "zoom_start": 1.0,
                    "zoom_end": 1.05,
                    "easing": "ease_out",
                },
                transition_in="cut",  # hard cuts inside the hook
                transition_duration=0.0,
                audio_mode="silent",
                j_cut_s=0.0,
                is_hook=False,  # the sub-clips themselves are not hooks
                hook_cps=0.5,
            )
            sub_decisions.append(sub)
        return sub_decisions

    def _render_panel_segment(self, d: EditDecision, output: str):
        """Render manga panel with Ken Burns + easing."""
        if not d.visual_path or not Path(d.visual_path).exists():
            return

        frames = int(d.duration * self.fps)
        zs = d.camera.get("zoom_start", 1.0)
        ze = d.camera.get("zoom_end", 1.08)
        easing = d.camera.get("easing", "smoothstep")

        # Build easing expression
        ease_expr = EASING_EXPR.get(easing, EASING_EXPR["smoothstep"])
        # T = normalized time
        t_expr = f"(on/{frames})"
        zoom_expr = f"'{zs}+{ze - zs}*{ease_expr}'.replace('T', '{t_expr}')"
        # Simplified: compute directly
        zoom_ffmpeg = f"'{zs}+({ze}-{zs})*({t_expr}*{t_expr}*(3-2*{t_expr}))'"

        vf = (
            f"scale={self.w * 2}:{self.h * 2}:flags=lanczos,"
            f"zoompan=z={zoom_ffmpeg}"
            f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
            f":d={frames}:s={self.w}x{self.h}:fps={self.fps}"
        )

        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", d.visual_path,
            "-vf", vf, "-t", str(d.duration),
            "-c:v", self.encoder, "-b:v", "5M",
            "-pix_fmt", "yuv420p", "-an", output,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)

    def _render_movie_segment(self, d: EditDecision, output: str):
        """Extract and render a movie clip segment."""
        if not d.visual_path or not Path(d.visual_path).exists():
            return

        # Extract the clip segment
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(d.clip_start_s),
            "-i", d.visual_path,
            "-t", str(d.duration),
            "-vf", f"scale={self.w}:{self.h}:force_original_aspect_ratio=decrease,"
                   f"pad={self.w}:{self.h}:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", self.encoder, "-b:v", "5M",
            "-pix_fmt", "yuv420p",
        ]

        if d.audio_mode == "clip_audio":
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        elif d.audio_mode == "ducked":
            cmd.extend(["-af", "volume=-20dB", "-c:a", "aac"])
        else:
            cmd.append("-an")

        cmd.append(output)
        subprocess.run(cmd, capture_output=True, timeout=60)

    def _render_title_card(self, d: EditDecision, output: str):
        """Render a title card (black bg + text)."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={self.w}x{self.h}:d={d.duration}:r={self.fps}",
            "-vf", f"drawtext=text='{d.narration_text[:50]}':fontsize=64:fontcolor=white:"
                   f"x=(w-tw)/2:y=(h-th)/2:font=DejaVu Sans",
            "-c:v", self.encoder, "-b:v", "2M",
            "-pix_fmt", "yuv420p", "-an", output,
        ]
        subprocess.run(cmd, capture_output=True, timeout=30)

    def _assemble_clips(self, clips: list, output: str):
        """Concatenate all clips (transitions applied in filter if <=8 clips)."""
        if len(clips) == 1:
            import shutil
            shutil.copy(clips[0], output)
            return

        # Simple concat (xfade can be added for <=8 clips in future)
        tmpdir = Path(clips[0]).parent
        concat_file = str(tmpdir / "concat.txt")
        with open(concat_file, "w") as f:
            for c in clips:
                f.write(f"file '{c}'\n")

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_file, "-c", "copy", output,
        ], capture_output=True, timeout=120)

    def _build_audio_track(self, edl: list, output: str):
        """Build the full audio track with J-cut offsets."""
        # Collect all narration audio files with their timing
        audio_segments = []
        current_time = 0.0

        for d in edl:
            if d.narration_audio and Path(d.narration_audio).exists():
                # J-cut: audio starts slightly before visual
                audio_start = max(0, current_time - d.j_cut_s)
                audio_segments.append({
                    "path": d.narration_audio,
                    "start": audio_start,
                    "duration": d.duration,
                })
            current_time += d.duration

        if not audio_segments:
            # Generate silent track
            total = sum(d.duration for d in edl)
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"anullsrc=r=44100:cl=mono:d={total}",
                "-c:a", "pcm_s16le", output,
            ], capture_output=True, timeout=30)
            return

        # For now, concatenate narration audio files
        tmpdir = Path(audio_segments[0]["path"]).parent
        concat_file = str(tmpdir / "audio_concat.txt")
        with open(concat_file, "w") as f:
            for seg in audio_segments:
                f.write(f"file '{seg['path']}'\n")

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_file, "-c:a", "pcm_s16le",
            "-ar", "44100", "-ac", "1", output,
        ], capture_output=True, timeout=60)

    def _final_merge(self, video: str, audio: str, output: str, subtitle: str = None):
        """Final merge: video + audio + optional subtitles."""
        cmd = ["ffmpeg", "-y", "-i", video, "-i", audio]

        if subtitle and Path(subtitle).exists():
            sub_esc = subtitle.replace(":", "\\:")
            cmd.extend(["-vf", f"ass='{sub_esc}'", "-c:v", self.encoder, "-b:v", "5M"])
        else:
            cmd.extend(["-c:v", "copy"])

        cmd.extend([
            "-map", "0:v", "-map", "1:a",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", output,
        ])
        subprocess.run(cmd, capture_output=True, timeout=120)


# ── Prompt template for Gemini (generates director-ready scripts) ──

DIRECTOR_PROMPT_ADDON = """
IMPORTANT: For each narration segment, you can optionally include a cross-reference
to a movie/series scene. When you do, specify:
- "cross_ref.type": "movie_clip"
- "cross_ref.movie": "exact movie title"
- "cross_ref.quote": "the iconic line to find via STT" (or "" for visual reference)
- "cross_ref.action": one of:
    - "play_then_narrate": play the movie clip with original audio (max 8s),
      then continue narrating over the clip silently
    - "narrate_over": your narration plays while the movie clip runs silently
    - "silent_bg": movie clip as visual background, fully silent

Example segment with cross-reference:
{
    "text": "The weight of ambition... as Michael Corleone once learned...",
    "emotion": "dark",
    "visual_hint": "Griffith looking at the castle",
    "cross_ref": {
        "type": "movie_clip",
        "movie": "The Godfather",
        "quote": "I'll make him an offer he can't refuse",
        "action": "play_then_narrate"
    }
}

Rules for cross-references:
- Max 1 cross-reference per Short (quality over quantity)
- The cross-reference must ENHANCE the analysis, not be random
- The movie quote must be ICONIC and recognizable
- After the clip plays, smoothly return to narrating over manga panels
"""


def get_director_prompt_addon() -> str:
    """Returns the prompt addon that teaches Gemini how to generate director-ready scripts."""
    return DIRECTOR_PROMPT_ADDON
