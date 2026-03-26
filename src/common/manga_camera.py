"""Manga page camera — cinematic scroll through a full manga page.

Instead of cutting individual panels, this module creates a smooth
camera movement across the entire page, following reading order,
pausing and zooming on important panels.

Flow:
  1. Establishing shot: show full page (zoom out)
  2. Scroll to first panel (reading order)
  3. For each panel:
     - Pan smoothly to panel center
     - If important: zoom in + hold (for narration)
     - If normal: pass through at steady speed
  4. End with slight zoom out

This produces a single continuous video from one page.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


def classify_page(panels: list[dict], page_size: tuple[int, int]) -> str:
    """Classify a manga page layout to decide the camera strategy.

    Returns:
        'grid'   — Regular panel grid (3+ well-defined panels). Use panel-by-panel scroll.
        'splash' — Splash page or full-bleed art (0-1 panels). Use slow vertical scroll.
        'mixed'  — Irregular layout (2 panels or big size variance). Use scroll with holds.
    """
    pw, ph = page_size
    page_area = pw * ph
    n = len(panels)

    if n == 0:
        return "splash"

    if n == 1:
        # If the single panel covers most of the page, it's a splash
        ratio = panels[0]["w"] * panels[0]["h"] / page_area
        return "splash" if ratio > 0.5 else "mixed"

    if n >= 3:
        # Check if panels are roughly similar size (grid-like)
        areas = [p["w"] * p["h"] for p in panels]
        avg_area = sum(areas) / len(areas)
        variance = sum((a - avg_area) ** 2 for a in areas) / len(areas)
        cv = (variance ** 0.5) / max(avg_area, 1)  # coefficient of variation

        # If size variance is low, it's a regular grid
        if cv < 0.8:
            return "grid"
        # High variance but many panels = irregular layout
        return "mixed"

    # 2 panels
    return "mixed"


def render_splash_scroll(
    page_image: str,
    output_path: str,
    duration: float = 5.0,
    target_size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    use_gpu: bool = False,
) -> str:
    """Render a slow vertical scroll for splash pages / full-bleed art.

    Simple top-to-bottom pan with slight zoom, no panel detection needed.
    """
    img = cv2.imread(page_image)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {page_image}")
    ph, pw = img.shape[:2]
    tw, th = target_size

    num_frames = int(duration * fps)
    tmpdir = tempfile.mkdtemp(prefix="splash_")

    try:
        # Calculate viewport: width fills target, scroll vertically
        zoom = tw / pw  # fit width
        vh = th / zoom  # viewport height in source coords

        # If page is shorter than viewport, just do slight zoom
        if vh >= ph:
            # Page fits in one frame — do subtle zoom
            for i in range(num_frames):
                t = _ease_in_out(i / max(num_frames - 1, 1))
                z = 1.0 + 0.05 * t  # 5% zoom
                crop_w = int(pw / z)
                crop_h = int(ph / z)
                x1 = (pw - crop_w) // 2
                y1 = (ph - crop_h) // 2
                crop = img[y1:y1 + crop_h, x1:x1 + crop_w]
                frame = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_LANCZOS4)
                cv2.imwrite(f"{tmpdir}/frame_{i:05d}.png", frame)
        else:
            # Scroll from top to bottom
            max_scroll = ph - vh
            for i in range(num_frames):
                t = _ease_in_out(i / max(num_frames - 1, 1))
                y_start = int(t * max_scroll)
                y_end = int(y_start + vh)
                crop = img[y_start:y_end, 0:pw]
                frame = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_LANCZOS4)
                cv2.imwrite(f"{tmpdir}/frame_{i:05d}.png", frame)

        # Encode
        encoder = "h264_nvenc" if use_gpu else "libx264"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{tmpdir}/frame_%05d.png",
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-b:v", "5M",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 and use_gpu:
            cmd[cmd.index("h264_nvenc")] = "libx264"
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    log.info(f"  Splash scroll: {Path(output_path).stat().st_size // 1024}KB")
    return output_path


def auto_render_page(
    page_image: str,
    panels: list[dict],
    output_path: str,
    important_indices: set[int] | None = None,
    target_size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    use_gpu: bool = False,
) -> str:
    """Automatically choose the best rendering strategy for a page.

    - splash → slow vertical scroll (5s)
    - grid → continuous vertical scroll (reads like manga, 4-6s)
    - mixed → panel-by-panel scroll with holds on important
    """
    img = cv2.imread(page_image)
    ph, pw = img.shape[:2]
    page_type = classify_page(panels, (pw, ph))

    log.info(f"  Page type: {page_type} ({len(panels)} panels)")

    if page_type == "splash":
        return render_splash_scroll(
            page_image, output_path,
            duration=4.0,
            target_size=target_size,
            fps=fps, use_gpu=use_gpu,
        )
    elif page_type == "grid":
        # Grid pages: smooth continuous scroll, no per-panel zoom
        return render_splash_scroll(
            page_image, output_path,
            duration=5.0,
            target_size=target_size,
            fps=fps, use_gpu=use_gpu,
        )
    else:
        # Mixed/irregular: panel-by-panel with holds
        return render_page_video(
            page_image, panels, output_path,
            important_indices=important_indices or set(),
            target_size=target_size,
            fps=fps, use_gpu=use_gpu,
        )


def _ease_in_out(t: float) -> float:
    """Smooth ease-in-out interpolation."""
    return 0.5 - 0.5 * np.cos(t * np.pi)


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation."""
    return a + (b - a) * t


def generate_camera_path(
    page_size: tuple[int, int],
    panels: list[dict],
    important_indices: set[int],
    target_size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    establish_duration: float = 0.8,
    panel_transit_duration: float = 0.6,
    normal_hold: float = 1.2,
    important_hold: float = 2.0,
    end_duration: float = 0.6,
) -> list[dict]:
    """Generate camera keyframes for a manga page.

    Returns list of {cx, cy, zoom, frame} keyframes.
    The camera viewport is always target_size at zoom=1.0.
    """
    pw, ph = page_size
    tw, th = target_size

    # Calculate zoom levels
    # Establishing: show most of the page (but never zoom out so much that bars appear)
    # Use max() to ensure the image always fills the frame width
    zoom_full = max(tw / pw, th / ph) * 0.85
    # Panel zoom: fit panel with generous context (don't crop too tight)
    def panel_zoom(panel):
        # Add 60% padding around panel so text and context are visible
        zw = tw / max(panel["w"] * 1.6, 1)
        zh = th / max(panel["h"] * 1.6, 1)
        z = min(zw, zh)
        # Clamp: never zoom more than 1.8x (keep context) or less than full page
        return max(zoom_full, min(z, 1.8))

    keyframes = []
    frame = 0

    # 1. Establishing shot — full page center, steady (no zoom animation)
    cx, cy = pw / 2, ph / 2
    establish_frames = int(establish_duration * fps)
    for i in range(establish_frames):
        keyframes.append({"cx": cx, "cy": cy, "zoom": zoom_full, "frame": frame})
        frame += 1

    # 2. Visit each panel in reading order
    for idx, panel in enumerate(panels):
        pcx = panel["x"] + panel["w"] / 2
        pcy = panel["y"] + panel["h"] / 2
        pz = panel_zoom(panel)
        is_important = idx in important_indices

        # Transit from current position to this panel
        prev = keyframes[-1] if keyframes else {"cx": cx, "cy": cy, "zoom": zoom_full}
        transit_frames = int(panel_transit_duration * fps)
        for i in range(transit_frames):
            t = _ease_in_out(i / max(transit_frames - 1, 1))
            keyframes.append({
                "cx": _lerp(prev["cx"], pcx, t),
                "cy": _lerp(prev["cy"], pcy, t),
                "zoom": _lerp(prev["zoom"], pz, t),
                "frame": frame,
            })
            frame += 1

        # Hold on panel
        hold_time = important_hold if is_important else normal_hold
        hold_frames = int(hold_time * fps)

        # Hold steady on panel (no micro-zoom — less is more)
        for i in range(hold_frames):
            keyframes.append({"cx": pcx, "cy": pcy, "zoom": pz, "frame": frame})
            frame += 1

    # 3. End: slight zoom out
    end_frames = int(end_duration * fps)
    last = keyframes[-1]
    for i in range(end_frames):
        t = _ease_in_out(i / max(end_frames - 1, 1))
        keyframes.append({
            "cx": _lerp(last["cx"], pw / 2, t),
            "cy": _lerp(last["cy"], ph / 2, t),
            "zoom": _lerp(last["zoom"], zoom_full, t),
            "frame": frame,
        })
        frame += 1

    return keyframes


def render_page_video(
    page_image: str,
    panels: list[dict],
    output_path: str,
    important_indices: set[int] | None = None,
    target_size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    use_gpu: bool = False,
    **kwargs,
) -> str:
    """Render a cinematic scroll video from a manga page.

    Args:
        page_image: Full manga page image path
        panels: Panel dicts with {x, y, w, h, index}
        output_path: Output .mp4 path
        important_indices: Set of panel indices to zoom in on
        target_size: Output resolution (width, height)
        fps: Frame rate
        use_gpu: Use GPU encoding
        **kwargs: Extra args for generate_camera_path
    """
    if important_indices is None:
        important_indices = set()

    img = cv2.imread(page_image)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {page_image}")
    ph, pw = img.shape[:2]
    tw, th = target_size

    log.info(f"  Page: {pw}x{ph}, {len(panels)} panels, {len(important_indices)} important")

    # Generate camera path
    keyframes = generate_camera_path(
        page_size=(pw, ph),
        panels=panels,
        important_indices=important_indices,
        target_size=target_size,
        fps=fps,
        **kwargs,
    )

    log.info(f"  Camera path: {len(keyframes)} frames ({len(keyframes)/fps:.1f}s)")

    # Render frames
    tmpdir = tempfile.mkdtemp(prefix="manga_cam_")
    try:
        for kf in keyframes:
            cx, cy, zoom = kf["cx"], kf["cy"], kf["zoom"]
            fidx = kf["frame"]

            # Calculate viewport in source image coordinates
            vw = tw / zoom
            vh = th / zoom

            # Check if viewport exceeds image bounds
            exceeds_w = vw > pw
            exceeds_h = vh > ph

            if exceeds_w or exceeds_h:
                # Viewport larger than image — letterbox (black padding)
                # Fit the visible portion of the image into the frame
                # Scale image to fit within target, center it
                fit_scale = min(tw / pw, th / ph) * zoom
                scaled_w = int(pw * fit_scale)
                scaled_h = int(ph * fit_scale)
                # Clamp to not exceed target
                scaled_w = min(scaled_w, tw)
                scaled_h = min(scaled_h, th)

                img_scaled = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_LANCZOS4)

                # Create black frame and paste centered
                frame = np.zeros((th, tw, 3), dtype=np.uint8)
                # Offset based on camera center
                ox = (tw - scaled_w) // 2
                oy = (th - scaled_h) // 2
                # Adjust based on where camera is looking
                cam_offset_x = int((cx / pw - 0.5) * scaled_w * 0.3)
                cam_offset_y = int((cy / ph - 0.5) * scaled_h * 0.3)
                ox = max(0, min(ox - cam_offset_x, tw - scaled_w))
                oy = max(0, min(oy - cam_offset_y, th - scaled_h))

                frame[oy:oy + scaled_h, ox:ox + scaled_w] = img_scaled
            else:
                # Normal crop — viewport fits inside image
                x1 = max(0, min(cx - vw / 2, pw - vw))
                y1 = max(0, min(cy - vh / 2, ph - vh))

                x1i = max(0, int(x1))
                y1i = max(0, int(y1))
                x2i = min(pw, int(x1 + vw))
                y2i = min(ph, int(y1 + vh))

                crop = img[y1i:y2i, x1i:x2i]
                if crop.size == 0:
                    crop = img

                frame = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_LANCZOS4)

            cv2.imwrite(f"{tmpdir}/frame_{fidx:05d}.png", frame)

        # Encode
        encoder = "h264_nvenc" if use_gpu else "libx264"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{tmpdir}/frame_%05d.png",
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-preset", "fast" if use_gpu else "medium",
            "-b:v", "5M",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0 and use_gpu:
            log.warning("GPU encode failed, fallback to libx264")
            cmd[cmd.index("h264_nvenc")] = "libx264"
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.error(f"FFmpeg failed: {result.stderr[-200:]}")

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    if Path(output_path).exists():
        log.info(f"  Video: {Path(output_path).stat().st_size // 1024}KB")
    return output_path


def detect_and_merge_spreads(
    page_images: list[str],
    reading_order: str = "rtl",
) -> list[dict]:
    """Detect single vs double-page spreads and merge when needed.

    Returns list of {'path': str, 'type': 'single'|'spread'|'wide', 'original_indices': [int]}

    Detection logic:
    - If a page is significantly wider than tall → already a spread (wide)
    - If two consecutive pages have similar height and are both narrow → merge as spread
    - Otherwise → single page
    """
    results = []
    i = 0

    while i < len(page_images):
        img = cv2.imread(page_images[i])
        if img is None:
            i += 1
            continue
        h, w = img.shape[:2]
        aspect = w / h

        # Already wide (aspect > 1.2) → it's a pre-merged spread
        if aspect > 1.2:
            results.append({
                "path": page_images[i],
                "type": "wide",
                "original_indices": [i],
            })
            log.info(f"  Page {i}: wide spread ({w}x{h}, ar={aspect:.2f})")
            i += 1
            continue

        # Check if next page could form a spread
        if i + 1 < len(page_images):
            img_next = cv2.imread(page_images[i + 1])
            if img_next is not None:
                h2, w2 = img_next.shape[:2]
                aspect2 = w2 / h2

                # Both narrow and similar height → likely a spread
                height_similar = abs(h - h2) < max(h, h2) * 0.1
                both_narrow = aspect < 0.8 and aspect2 < 0.8

                if height_similar and both_narrow:
                    # Merge: right page first for RTL manga
                    target_h = max(h, h2)
                    img_resized = cv2.resize(img, (int(w * target_h / h), target_h))
                    img_next_resized = cv2.resize(img_next, (int(w2 * target_h / h2), target_h))

                    if reading_order == "rtl":
                        merged = np.hstack([img_next_resized, img_resized])
                    else:
                        merged = np.hstack([img_resized, img_next_resized])

                    # Save merged
                    merged_path = page_images[i].replace(".png", "_spread.png").replace(".jpg", "_spread.jpg")
                    cv2.imwrite(merged_path, merged)
                    mh, mw = merged.shape[:2]
                    log.info(f"  Pages {i}+{i+1}: merged spread ({mw}x{mh})")

                    results.append({
                        "path": merged_path,
                        "type": "spread",
                        "original_indices": [i, i + 1],
                    })
                    i += 2
                    continue

        # Single page
        results.append({
            "path": page_images[i],
            "type": "single",
            "original_indices": [i],
        })
        log.info(f"  Page {i}: single ({w}x{h})")
        i += 1

    return results


def render_spread_video(
    spread_image: str,
    output_path: str,
    duration: float = 6.0,
    target_size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    use_gpu: bool = False,
) -> str:
    """Render a horizontal pan across a double-page spread.

    Pans from right to left (manga reading order) across the wide image.
    """
    img = cv2.imread(spread_image)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {spread_image}")
    ph, pw = img.shape[:2]
    tw, th = target_size

    num_frames = int(duration * fps)
    tmpdir = tempfile.mkdtemp(prefix="spread_")

    try:
        # Scale height to fill frame vertically
        scale = th / ph
        scaled_w = int(pw * scale)
        scaled_h = th
        img_scaled = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_LANCZOS4)

        # Pan range: start at right edge, end at left edge (RTL)
        max_offset = max(0, scaled_w - tw)

        for i in range(num_frames):
            t = _ease_in_out(i / max(num_frames - 1, 1))
            # RTL: start from right
            x_start = int((1.0 - t) * max_offset)

            crop = img_scaled[:, x_start:x_start + tw]
            if crop.shape[1] < tw:
                # Pad if needed
                frame = np.zeros((th, tw, 3), dtype=np.uint8)
                frame[:, :crop.shape[1]] = crop
            else:
                frame = crop

            cv2.imwrite(f"{tmpdir}/frame_{i:05d}.png", frame)

        encoder = "h264_nvenc" if use_gpu else "libx264"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{tmpdir}/frame_%05d.png",
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-b:v", "5M",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 and use_gpu:
            cmd[cmd.index("h264_nvenc")] = "libx264"
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    if Path(output_path).exists():
        log.info(f"  Spread pan: {Path(output_path).stat().st_size // 1024}KB")
    return output_path


def render_manga_short(
    page_images: list[str],
    page_panels: list[list[dict]],
    output_path: str,
    important_panels: list[set[int]] | None = None,
    target_size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    transition_duration: float = 0.5,
    use_gpu: bool = False,
) -> str:
    """Render a complete manga Short from multiple pages.

    Automatically detects single pages vs double-page spreads.
    Each page/spread gets its own camera strategy, then concatenated.
    """
    if important_panels is None:
        important_panels = [set() for _ in page_images]

    # Detect spreads
    spreads = detect_and_merge_spreads(page_images)
    n = len(spreads)
    tmpdir = tempfile.mkdtemp(prefix="manga_short_")
    clip_paths = []

    try:
        for i, spread in enumerate(spreads):
            page_img = spread["path"]
            page_type = spread["type"]
            orig_idx = spread["original_indices"][0]
            panels = page_panels[orig_idx] if orig_idx < len(page_panels) else []
            important = important_panels[orig_idx] if orig_idx < len(important_panels) else set()

            log.info(f"Page {i+1}/{n}: {Path(page_img).name} ({page_type})")
            clip_path = f"{tmpdir}/page_{i:03d}.mp4"

            if page_type in ("spread", "wide"):
                # Double page → horizontal pan
                render_spread_video(
                    page_img, clip_path,
                    duration=6.0,
                    target_size=target_size,
                    fps=fps, use_gpu=use_gpu,
                )
            else:
                # Single page → auto detect strategy
                auto_render_page(
                    page_img, panels, clip_path,
                    important_indices=important,
                    target_size=target_size,
                    fps=fps, use_gpu=use_gpu,
                )
            if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
                clip_paths.append(clip_path)

        if not clip_paths:
            raise RuntimeError("No clips produced")

        # Concatenate
        if len(clip_paths) == 1:
            import shutil
            shutil.copy2(clip_paths[0], output_path)
        else:
            # Simple concat (xfade can be added later)
            concat_file = f"{tmpdir}/concat.txt"
            with open(concat_file, "w") as f:
                for cp in clip_paths:
                    f.write(f"file '{cp}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file, "-c", "copy", str(output_path),
            ], capture_output=True, timeout=120)

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    if Path(output_path).exists():
        size = Path(output_path).stat().st_size // 1024
        log.info(f"Final Short: {size}KB ({len(clip_paths)} pages)")
    return output_path


# ── Fair Use validation gate ────────────────────────────────────
MAX_PANELS_PER_SHORT = 5

def validate_fair_use(
    video_path: str,
    has_narration_audio: bool,
    has_subtitles: bool,
    num_panels: int,
    has_original_commentary: bool = True,
) -> tuple[bool, list[str]]:
    """Validate a Short meets Fair Use requirements before upload.

    Returns (is_valid, list_of_issues).
    A Short MUST have narration + subtitles + limited panels to be uploaded.
    """
    issues = []

    if not has_narration_audio:
        issues.append("BLOCKED: No narration audio — cannot upload without original voice commentary")

    if not has_subtitles:
        issues.append("BLOCKED: No subtitles — narrated text must be visible on screen")

    if num_panels > MAX_PANELS_PER_SHORT:
        issues.append(f"BLOCKED: {num_panels} panels exceeds limit of {MAX_PANELS_PER_SHORT} — reduce to avoid copyright issues")

    if not has_original_commentary:
        issues.append("BLOCKED: No original commentary — Short must include analysis/reflection, not just show panels")

    if not Path(video_path).exists():
        issues.append("BLOCKED: Video file does not exist")

    is_valid = len(issues) == 0

    if is_valid:
        log.info(f"Fair Use validation PASSED: {video_path}")
    else:
        log.warning(f"Fair Use validation FAILED: {video_path}")
        for issue in issues:
            log.warning(f"  {issue}")

    return is_valid, issues
