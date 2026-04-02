"""2.5D Parallax video generation using MiDaS depth estimation.

Takes a static manga panel image, estimates depth, separates into
foreground/background layers, and creates a parallax animation
where layers move at different speeds creating a 3D-like effect.

Dependencies: transformers, torch, cv2, numpy
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Cache model globally to avoid reloading per panel
_depth_model = None
_depth_processor = None


def _load_depth_model():
    """Load MiDaS depth estimation model (cached)."""
    global _depth_model, _depth_processor
    if _depth_model is not None:
        return _depth_model, _depth_processor

    import torch
    from transformers import DPTForDepthEstimation, DPTImageProcessor

    _depth_processor = DPTImageProcessor.from_pretrained("Intel/dpt-hybrid-midas")
    _depth_model = DPTForDepthEstimation.from_pretrained("Intel/dpt-hybrid-midas")

    if torch.cuda.is_available():
        _depth_model = _depth_model.cuda()
        log.info("MiDaS loaded on CUDA")
    else:
        log.info("MiDaS loaded on CPU")

    _depth_model.eval()
    return _depth_model, _depth_processor


def estimate_depth(image_path: str) -> np.ndarray:
    """Estimate depth map for an image. Returns normalized depth (0-255)."""
    import torch

    model, processor = _load_depth_model()
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {image_path}")

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    inputs = processor(images=img_rgb, return_tensors="pt")

    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        depth = outputs.predicted_depth

    # Interpolate to original size
    depth = torch.nn.functional.interpolate(
        depth.unsqueeze(1),
        size=img.shape[:2],
        mode="bicubic",
        align_corners=False,
    ).squeeze()

    depth_np = depth.cpu().numpy()
    # Normalize to 0-255
    depth_np = (depth_np - depth_np.min()) / (depth_np.max() - depth_np.min() + 1e-8)
    depth_map = (depth_np * 255).astype(np.uint8)

    return depth_map


def create_parallax_frames(
    image_path: str,
    depth_map: np.ndarray,
    num_frames: int = 90,
    max_shift: int = 30,
    direction: str = "right",
    zoom_factor: float = 1.05,
) -> list[np.ndarray]:
    """Create parallax animation frames from image + depth map.

    Foreground (closer, brighter depth) shifts more than background.
    Creates a smooth 3D-like camera movement effect.

    Args:
        image_path: Path to source image
        depth_map: Grayscale depth map (0=far, 255=near)
        num_frames: Total frames to generate
        max_shift: Maximum pixel displacement for foreground
        direction: Camera movement direction (right, left, up, down, zoom)
        zoom_factor: Max zoom multiplier for zoom direction
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]

    # Normalize depth to 0-1
    depth_norm = depth_map.astype(np.float32) / 255.0

    frames = []
    for i in range(num_frames):
        # Progress: 0 → 1 → 0 (smooth back and forth)
        t = i / max(num_frames - 1, 1)
        # Ease in-out for smooth motion
        progress = 0.5 - 0.5 * np.cos(t * 2 * np.pi)

        # Compute per-pixel displacement based on depth
        shift = (progress - 0.5) * max_shift * 2

        y_coords, x_coords = np.mgrid[0:h, 0:w].astype(np.float32)

        if direction == "zoom":
            scale = 1.0 + (zoom_factor - 1.0) * progress
            cx, cy = np.float32(w / 2), np.float32(h / 2)
            depth_scale = (1.0 + (scale - 1.0) * depth_norm).astype(np.float32)
            map_x = (cx + (x_coords - cx) / depth_scale).astype(np.float32)
            map_y = (cy + (y_coords - cy) / depth_scale).astype(np.float32)

        elif direction in ("right", "left"):
            sign = 1.0 if direction == "right" else -1.0
            displacement = (shift * sign * depth_norm).astype(np.float32)
            map_x = (x_coords - displacement).astype(np.float32)
            map_y = y_coords.copy()

        elif direction in ("up", "down"):
            sign = -1.0 if direction == "up" else 1.0
            displacement = (shift * sign * depth_norm).astype(np.float32)
            map_x = x_coords.copy()
            map_y = (y_coords - displacement).astype(np.float32)

        else:
            map_x = x_coords.copy()
            map_y = y_coords.copy()

        frame = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        frames.append(frame)

    return frames


def render_parallax_video(
    image_path: str,
    output_path: str,
    duration_s: float = 3.0,
    direction: str = "right",
    max_shift: int = 12,
    zoom_factor: float = 1.02,
    fps: int = 30,
    target_size: tuple = (1080, 1920),
    use_gpu: bool = True,
) -> str:
    """Render a 2.5D parallax video from a single manga panel.

    Args:
        image_path: Source panel image
        output_path: Output .mp4 path
        duration_s: Duration in seconds
        direction: Camera direction (right, left, up, down, zoom)
        max_shift: Max parallax displacement pixels
        zoom_factor: Max zoom for zoom direction
        fps: Frame rate
        target_size: (width, height) of output
        use_gpu: Use NVENC for encoding
    """
    num_frames = int(duration_s * fps)

    # Step 1: Normalize image
    tw, th = target_size
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {image_path}")
    ih, iw = img.shape[:2]
    total_pixels = ih * iw
    min_pixels = tw * th * 0.15  # At least 15% of target resolution

    log.info(f"  Panel: {iw}x{ih} ({total_pixels//1000}Kpx) | target: {tw}x{th}")

    # If panel is too small, upscale with sharpening
    if total_pixels < min_pixels:
        upscale = max(2.0, (min_pixels / total_pixels) ** 0.5)
        log.info(f"  Upscaling {upscale:.1f}x (panel too small)")
        new_w_up = int(iw * upscale)
        new_h_up = int(ih * upscale)
        img = cv2.resize(img, (new_w_up, new_h_up), interpolation=cv2.INTER_LANCZOS4)
        # Sharpen to reduce blur from upscaling
        kernel = np.array([[-0.5, -1, -0.5],
                           [-1,   7, -1],
                           [-0.5, -1, -0.5]]) / 2.0
        img = cv2.filter2D(img, -1, kernel)
        img = np.clip(img, 0, 255).astype(np.uint8)
        ih, iw = img.shape[:2]

    # Step 2: Estimate depth
    # Save normalized image temporarily for depth estimation
    tmp_norm = str(Path(output_path).with_suffix('.norm.png'))
    cv2.imwrite(tmp_norm, img)
    log.info(f"  Estimating depth for {Path(image_path).name}...")
    depth_map = estimate_depth(tmp_norm)

    # Step 3: Smart crop to 9:16 — center on content, not geometry
    # Use depth map to find the "interesting" center (highest depth variance)
    scale = max(tw / iw, th / ih)
    new_w, new_h = int(iw * scale), int(ih * scale)
    img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    depth_resized = cv2.resize(depth_map, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    # Find content center using depth variance in sliding windows
    if new_w > tw:
        # Horizontal crop needed — find the most "interesting" horizontal slice
        best_x = (new_w - tw) // 2  # default: center
        best_score = 0
        step = max(1, (new_w - tw) // 20)
        for xo in range(0, new_w - tw, step):
            region = depth_resized[:, xo:xo + tw]
            score = float(np.std(region)) + float(np.mean(region)) * 0.5
            if score > best_score:
                best_score = score
                best_x = xo
        x_off = best_x
    else:
        x_off = (new_w - tw) // 2

    if new_h > th:
        # Vertical crop needed — find the most "interesting" vertical slice
        best_y = (new_h - th) // 2
        best_score = 0
        step = max(1, (new_h - th) // 20)
        for yo in range(0, new_h - th, step):
            region = depth_resized[yo:yo + th, :]
            score = float(np.std(region)) + float(np.mean(region)) * 0.5
            if score > best_score:
                best_score = score
                best_y = yo
        y_off = best_y
    else:
        y_off = (new_h - th) // 2

    # Clamp offsets
    x_off = max(0, min(x_off, new_w - tw))
    y_off = max(0, min(y_off, new_h - th))

    img_cropped = img_resized[y_off:y_off + th, x_off:x_off + tw]
    depth_cropped = depth_resized[y_off:y_off + th, x_off:x_off + tw]

    log.info(f"  Cropped: {img_cropped.shape[1]}x{img_cropped.shape[0]} (offset: {x_off},{y_off})")

    # Save cropped for frame generation
    tmp_img = str(Path(output_path).with_suffix('.crop.png'))
    cv2.imwrite(tmp_img, img_cropped)

    # Step 3: Generate parallax frames
    log.info(f"  Generating {num_frames} parallax frames ({direction})...")
    frames = create_parallax_frames(
        tmp_img, depth_cropped,
        num_frames=num_frames,
        max_shift=max_shift,
        direction=direction,
        zoom_factor=zoom_factor,
    )

    # Step 4: Encode to video
    log.info(f"  Encoding video ({tw}x{th} @ {fps}fps)...")
    tmpdir = tempfile.mkdtemp(prefix="parallax_")
    try:
        # Write frames
        for idx, frame in enumerate(frames):
            cv2.imwrite(f"{tmpdir}/frame_{idx:05d}.png", frame)

        encoder = "h264_nvenc" if use_gpu else "libx264"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{tmpdir}/frame_%05d.png",
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-preset", "fast" if use_gpu else "medium",
            "-b:v", "4M",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 and use_gpu:
            log.warning("GPU encode failed, falling back to libx264")
            cmd[cmd.index("h264_nvenc")] = "libx264"
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error(f"FFmpeg failed: {result.stderr[-200:]}")
    finally:
        # Cleanup frames
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Cleanup temp files
    for p in [tmp_img, tmp_norm]:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass

    log.info(f"  Parallax video saved: {output_path}")
    return output_path


def render_manga_short_parallax(
    panel_images: list[str],
    output_path: str,
    audio_paths: list[str] | None = None,
    panel_durations: list[float] | None = None,
    directions: list[str] | None = None,
    transition_duration: float = 0.5,
    fps: int = 30,
    target_size: tuple = (1080, 1920),
    use_gpu: bool = True,
) -> str:
    """Render a complete manga Short with parallax panels + transitions.

    Args:
        panel_images: List of panel image paths
        output_path: Final output video path
        audio_paths: Optional narration audio per panel
        panel_durations: Duration per panel (default 3s each)
        directions: Camera direction per panel (cycles through defaults)
        transition_duration: Crossfade duration between panels
        fps: Frame rate
        target_size: Output resolution
        use_gpu: Use GPU encoding
    """
    if not panel_images:
        raise ValueError("No panel images provided")

    n = len(panel_images)
    if panel_durations is None:
        panel_durations = [3.0] * n
    if directions is None:
        # Cycle through different movements for variety
        default_dirs = ["right", "zoom", "left", "up", "zoom", "down"]
        directions = [default_dirs[i % len(default_dirs)] for i in range(n)]

    # Step 1: Render individual parallax clips
    import shutil
    tmpdir = tempfile.mkdtemp(prefix="manga_short_")
    clip_paths = []
    try:
        for i, (img_path, dur, direction) in enumerate(zip(panel_images, panel_durations, directions)):
            clip_path = f"{tmpdir}/clip_{i:03d}.mp4"
            render_parallax_video(
                img_path, clip_path,
                duration_s=dur,
                direction=direction,
                fps=fps,
                target_size=target_size,
                use_gpu=use_gpu,
            )
            clip_paths.append(clip_path)

        # Step 2: Concatenate with crossfade transitions
        if len(clip_paths) == 1:
            shutil.copy2(clip_paths[0], output_path)
        else:
            _concat_with_xfade(clip_paths, output_path, panel_durations,
                               transition_duration, fps, use_gpu)

        # Step 3: Add audio if provided
        if audio_paths and any(Path(a).exists() for a in audio_paths if a):
            _merge_audio(output_path, audio_paths, panel_durations)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    log.info(f"Final manga Short: {output_path}")
    return output_path


def _concat_with_xfade(
    clip_paths: list[str],
    output_path: str,
    durations: list[float],
    transition_dur: float,
    fps: int,
    use_gpu: bool,
):
    """Concatenate clips with xfade crossfade transitions."""
    n = len(clip_paths)
    if n < 2:
        return

    # Build inputs
    inputs = []
    for cp in clip_paths:
        inputs.extend(["-i", cp])

    # Build xfade filter chain
    # For n clips: n-1 xfade operations
    filters = []
    offset = durations[0] - transition_dur
    prev_label = "[0:v]"

    for i in range(1, n):
        out_label = f"[v{i}]" if i < n - 1 else "[vout]"
        filters.append(
            f"{prev_label}[{i}:v]xfade=transition=fade:duration={transition_dur}:offset={offset:.2f}{out_label}"
        )
        if i < n - 1:
            offset += durations[i] - transition_dur
        prev_label = out_label

    filter_str = ";".join(filters)

    encoder = "h264_nvenc" if use_gpu else "libx264"
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[vout]",
        "-c:v", encoder,
        "-pix_fmt", "yuv420p",
        "-preset", "fast" if use_gpu else "medium",
        "-b:v", "4M",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        log.warning(f"xfade failed: {result.stderr[-200:]}")
        # Fallback: simple concat without transitions
        concat_file = Path(output_path).with_suffix('.concat.txt')
        with open(concat_file, 'w') as f:
            for cp in clip_paths:
                f.write(f"file '{cp}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c", "copy", output_path
        ], capture_output=True, timeout=120)
        concat_file.unlink(missing_ok=True)


def _merge_audio(video_path: str, audio_paths: list[str], durations: list[float]):
    """Merge narration audio tracks into the video, sequenced by panel timing."""
    import shutil

    valid_audios = [(a, d) for a, d in zip(audio_paths, durations) if a and Path(a).exists()]
    if not valid_audios:
        return

    tmp_out = str(Path(video_path).with_suffix('.with_audio.mp4'))

    # Build audio filter: adelay each audio to its panel start time
    inputs = ["-i", video_path]
    filters = []
    offset_ms = 0

    for i, (audio_path, dur) in enumerate(valid_audios):
        inputs.extend(["-i", audio_path])
        audio_idx = i + 1
        if offset_ms > 0:
            filters.append(f"[{audio_idx}:a]adelay={offset_ms}|{offset_ms}[a{i}]")
        else:
            filters.append(f"[{audio_idx}:a]acopy[a{i}]")
        offset_ms += int(dur * 1000)

    # Mix all audio tracks
    mix_inputs = "".join(f"[a{i}]" for i in range(len(valid_audios)))
    filters.append(f"{mix_inputs}amix=inputs={len(valid_audios)}:duration=longest[aout]")

    filter_str = ";".join(filters)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        tmp_out,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0:
        shutil.move(tmp_out, video_path)
    else:
        log.warning(f"Audio merge failed: {result.stderr[-200:]}")
        Path(tmp_out).unlink(missing_ok=True)
