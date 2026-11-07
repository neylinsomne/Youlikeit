"""Test content cycle: generate 3 video types for Deep Mind."""
import sys, os, json, shutil, subprocess, asyncio, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
import edge_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

OUTPUT_BASE = Path("outputs/content_cycle_test")
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

VOICE = "en-US-AndrewMultilingualNeural"

# 3 video types with different tones
VIDEOS = [
    {
        "type": "narration",
        "tone": "narrative",
        "title": "Berserk: The Night Everything Changed #Shorts",
        "rate": "-5%", "pitch": "-8Hz",
        "segments": [
            "It was the night that changed everything.",
            "Griffith, broken and desperate, held the Crimson Behelit.",
            "And in that moment, he made a choice that would echo through eternity.",
            "The Band of the Hawk, his brothers, his family. All sacrificed.",
            "Guts lost his arm. He lost his eye. He lost everything. But he kept fighting.",
            "Maybe that is what makes him human. Not the strength. The refusal to stop.",
        ],
    },
    {
        "type": "personality",
        "tone": "critical",
        "title": "Griffith Was RIGHT and You Know It #Shorts",
        "rate": "-3%", "pitch": "-5Hz",
        "segments": [
            "Griffith was right. And deep down, you know it.",
            "Every great leader in history has sacrificed others for their vision.",
            "Alexander, Caesar, Napoleon. They all made the same choice Griffith made.",
            "The only difference? Griffith was honest about the cost.",
            "Guts calls it betrayal. History calls it ambition.",
            "So before you judge Griffith, ask yourself. What would you sacrifice for your dream?",
        ],
    },
    {
        "type": "test",
        "tone": "emotional",
        "title": "I Cannot Watch This Scene Without Crying #Shorts",
        "rate": "-8%", "pitch": "-10Hz",
        "segments": [
            "I have watched this scene a hundred times.",
            "And every single time, it breaks me.",
            "Casca. Guts. The Band of the Hawk.",
            "They were a family. They trusted each other with their lives.",
            "And one man, the man they loved most, destroyed all of it.",
            "If you have ever been betrayed by someone you loved, you understand.",
        ],
    },
]


def generate_audio(segments, out_dir, voice, rate, pitch):
    """Generate edge-tts audio for all segments."""
    audio_files = []
    narration_data = []
    t = 0.0

    for old in out_dir.glob("seg_*.wav"):
        old.unlink()

    for i, text in enumerate(segments):
        wav_path = str(out_dir / f"seg_{i:02d}.wav")
        mp3_path = str(out_dir / f"seg_{i:02d}.mp3")

        async def gen(t=text, mp3=mp3_path):
            c = edge_tts.Communicate(t, voice, rate=rate, pitch=pitch)
            await c.save(mp3)
        asyncio.run(gen())

        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "1",
             "-c:a", "pcm_s16le", wav_path],
            capture_output=True, timeout=15,
        )
        Path(mp3_path).unlink(missing_ok=True)

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", wav_path],
            capture_output=True, text=True,
        )
        dur = float(probe.stdout.strip()) if probe.stdout.strip() else 3.0

        audio_files.append(wav_path)
        narration_data.append({"text": text, "start_s": t, "duration_s": dur, "emotion": "dark"})
        t += dur
        log.info(f"  seg{i}: {dur:.1f}s")

    # Concat
    full_audio = str(out_dir / "full_audio.wav")
    concat_list = str(out_dir / "concat.txt")
    with open(concat_list, "w") as f:
        for af in audio_files:
            f.write(f"file '{os.path.abspath(af)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", full_audio],
        capture_output=True, text=True, timeout=30,
    )
    log.info(f"  Total audio: {t:.1f}s")
    return audio_files, narration_data, full_audio, t


def render_video(narration_data, audio_files, full_audio, out_dir, vtype):
    """Render video with manga panels + subtitles."""
    from apps.production.animated_subs import generate_ass_subtitles
    from apps.production.video_director import VideoDirector, EditDecision

    # Subtitles
    sub_segments = [{
        "text": ns["text"],
        "start_s": ns["start_s"],
        "end_s": ns["start_s"] + ns["duration_s"],
        "emotion": "dark",
    } for ns in narration_data]
    ass_path = str(out_dir / "subtitles.ass")
    generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")

    # Director
    director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)
    pages = sorted(Path("data/manga_panels").rglob("*.[jp][pn]g"))[:20]
    pages_per_seg = max(1, len(pages) // max(len(narration_data), 1))

    import tempfile
    tmpdir = tempfile.mkdtemp(prefix=f"cycle_{vtype}_")

    edl = []
    for i, ns in enumerate(narration_data):
        page_idx = min(i * pages_per_seg, len(pages) - 1)
        camera = director._camera_for_emotion("dark")
        transition = director._transition_for_shift("dark", i)
        edl.append(EditDecision(
            visual_type="manga_panel",
            visual_path=str(pages[page_idx]),
            duration=ns["duration_s"],
            narration_text=ns["text"],
            narration_audio=audio_files[i],
            emotion="dark",
            camera=camera,
            transition_in=transition,
            j_cut_s=0.3 if i > 0 else 0,
        ))

    clip_paths = []
    for i, decision in enumerate(edl):
        clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        director._render_panel_segment(decision, clip_path)
        if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
            clip_paths.append(clip_path)

    # Concatenate
    video_only = os.path.join(tmpdir, "assembled.mp4")
    cf = os.path.join(tmpdir, "vconcat.txt")
    with open(cf, "w") as f:
        for c in clip_paths:
            f.write(f"file '{c}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cf, "-c", "copy", video_only],
        capture_output=True, timeout=60,
    )

    # Merge video + audio
    merged = os.path.join(tmpdir, "merged.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_only, "-i", full_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", merged,
    ], capture_output=True, text=True, timeout=120)

    # Burn subtitles
    final = str(out_dir / f"FINAL_{vtype.upper()}.mp4")
    ass_esc = ass_path.replace("\\", "/").replace(":", "\\\\:")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", merged,
        "-vf", f"ass='{ass_esc}'",
        "-c:v", "h264_nvenc", "-b:v", "5M", "-c:a", "copy", final,
    ], capture_output=True, text=True, timeout=120)

    if not Path(final).exists():
        fallback = merged if Path(merged).exists() else video_only
        if Path(fallback).exists():
            shutil.copy(fallback, final)
            log.warning("  Subtitles failed, using version without subs")

    shutil.rmtree(tmpdir, ignore_errors=True)
    return final


# ── Main ──
for video in VIDEOS:
    vtype = video["type"]
    log.info(f"\n=== {vtype.upper()} ({video['tone']}) ===")

    out_dir = OUTPUT_BASE / vtype
    out_dir.mkdir(exist_ok=True)

    audio_files, narration_data, full_audio, total_dur = generate_audio(
        video["segments"], out_dir, VOICE, video["rate"], video["pitch"],
    )

    final = render_video(narration_data, audio_files, full_audio, out_dir, vtype)

    size = Path(final).stat().st_size // 1024 if Path(final).exists() else 0
    log.info(f"  OUTPUT: {final} ({size}KB)")

log.info("\n=== ALL 3 VIDEOS GENERATED ===")
for vtype in ["narration", "personality", "test"]:
    f = OUTPUT_BASE / vtype / f"FINAL_{vtype.upper()}.mp4"
    if f.exists():
        log.info(f"  {vtype:12s}: {f} ({f.stat().st_size // 1024}KB)")
