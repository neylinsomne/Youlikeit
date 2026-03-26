"""
Animated subtitles for YouTube Shorts.
Words appear synchronized with narration, with colored highlights on key words.
Uses ASS (Advanced SubStation Alpha) format for rich styling.
"""
import re
import os
import json
import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

# Color palette for keyword highlights (ASS uses &HBBGGRR& format)
HIGHLIGHT_COLORS = {
    'epic':    '&H00FFFF&',    # cyan
    'dark':    '&H5050FF&',    # red-ish
    'tragic':  '&H8080FF&',   # salmon
    'hopeful': '&H80FF80&',   # green
    'default': '&H00E8FF&',   # gold/yellow
}

# Words to auto-highlight (dramatic/emotional keywords)
HIGHLIGHT_WORDS = {
    'sacrifice', 'death', 'blood', 'war', 'dream', 'betrayal', 'eclipse',
    'darkness', 'sword', 'fight', 'hope', 'destiny', 'fate', 'power',
    'sacrifice', 'demon', 'hawk', 'god', 'hand', 'kill', 'survive',
    'love', 'revenge', 'pain', 'scream', 'chaos', 'fire', 'storm',
    'shadow', 'light', 'rise', 'fall', 'broken', 'legend', 'warrior',
    # Spanish
    'sacrificio', 'muerte', 'sangre', 'guerra', 'sueño', 'traición',
    'oscuridad', 'espada', 'lucha', 'esperanza', 'destino', 'poder',
    'demonio', 'venganza', 'dolor', 'caos', 'fuego', 'sombra', 'luz',
}


def generate_ass_subtitles(
    segments: List[Dict],
    output_path: str,
    style: str = 'shorts',
    emotion: str = 'default',
) -> str:
    """
    Generate ASS subtitle file with animated word-by-word appearance.

    segments: [{"text": "...", "start_s": 0.0, "end_s": 5.0, "emotion": "dark"}]
    """
    highlight_color = HIGHLIGHT_COLORS.get(emotion, HIGHLIGHT_COLORS['default'])

    if style == 'shorts':
        ass_content = _generate_shorts_style(segments, highlight_color)
    elif style == 'karaoke':
        ass_content = _generate_karaoke_style(segments, highlight_color)
    else:
        ass_content = _generate_simple_style(segments, highlight_color)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)

    log.info(f"ASS subtitles saved: {output_path}")
    return output_path


def _ass_header(play_res_x=1080, play_res_y=1920) -> str:
    """ASS file header for 9:16 vertical video."""
    return f"""[Script Info]
Title: YouLikeIt Animated Subtitles
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial Black,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,400,1
Style: Highlight,Arial Black,78,&H00FFFF00,&H000000FF,&H00000000,&H80000000,-1,0,0,0,105,105,0,0,1,4,2,2,40,40,400,1
Style: Small,Arial,48,&H00CCCCCC,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,40,40,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _format_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.CC"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _generate_shorts_style(segments: List[Dict], highlight_color: str) -> str:
    """
    YouTube Shorts style: 2-3 words at a time, centered,
    key words highlighted in color with scale pop effect.
    """
    ass = _ass_header()

    for seg in segments:
        text = seg['text']
        start = seg['start_s']
        end = seg['end_s']
        emotion = seg.get('emotion', 'default')
        hl_color = HIGHLIGHT_COLORS.get(emotion, highlight_color)

        words = text.split()
        if not words:
            continue

        # Calculate timing per word group (2-3 words per display)
        duration = end - start
        group_size = 3 if len(words) > 8 else 2
        groups = []
        for i in range(0, len(words), group_size):
            groups.append(words[i:i + group_size])

        time_per_group = duration / max(len(groups), 1)

        for gi, group in enumerate(groups):
            g_start = start + (gi * time_per_group)
            g_end = g_start + time_per_group + 0.15  # slight overlap

            # Build styled text with highlights
            styled_words = []
            for word in group:
                clean = re.sub(r'[^\w]', '', word.lower())
                if clean in HIGHLIGHT_WORDS:
                    # Highlighted word: color + scale pop + bold
                    styled_words.append(
                        f"{{\\c{hl_color}\\fscx110\\fscy110\\t(0,150,\\fscx100\\fscy100)}}{word}"
                    )
                else:
                    styled_words.append(f"{{\\c&H00FFFFFF&}}{word}")

            display_text = ' '.join(styled_words)

            # Fade in (100ms) + fade out (100ms)
            fade = "{\\fad(100,100)}"

            ass += (
                f"Dialogue: 0,{_format_time(g_start)},{_format_time(g_end)},"
                f"Main,,0,0,0,,{fade}{display_text}\n"
            )

    return ass


def _generate_karaoke_style(segments: List[Dict], highlight_color: str) -> str:
    """
    Karaoke style: full sentence visible, words light up one by one.
    """
    ass = _ass_header()

    for seg in segments:
        text = seg['text']
        start = seg['start_s']
        end = seg['end_s']
        words = text.split()
        if not words:
            continue

        duration_cs = int((end - start) * 100)
        time_per_word_cs = duration_cs // max(len(words), 1)

        # Build karaoke line
        kara_parts = []
        for word in words:
            kara_parts.append(f"{{\\k{time_per_word_cs}}}{word} ")

        kara_text = ''.join(kara_parts)

        ass += (
            f"Dialogue: 0,{_format_time(start)},{_format_time(end)},"
            f"Main,,0,0,0,,{kara_text}\n"
        )

    return ass


def _generate_simple_style(segments: List[Dict], highlight_color: str) -> str:
    """Simple subtitles with fade."""
    ass = _ass_header()

    for seg in segments:
        text = seg['text']
        start = seg['start_s']
        end = seg['end_s']

        # Wrap long lines
        words = text.split()
        lines = []
        current = []
        for w in words:
            current.append(w)
            if len(' '.join(current)) > 25:
                lines.append(' '.join(current))
                current = []
        if current:
            lines.append(' '.join(current))

        display = '\\N'.join(lines)

        ass += (
            f"Dialogue: 0,{_format_time(start)},{_format_time(end)},"
            f"Main,,0,0,0,,{{\\fad(200,200)}}{display}\n"
        )

    return ass


def burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
    use_gpu: bool = True,
) -> str:
    """
    Burn ASS subtitles into video using FFmpeg.
    """
    # Normalize paths for FFmpeg (forward slashes, escape colons on Windows)
    ass_ffmpeg = ass_path.replace('\\', '/').replace(':', '\\:')

    encoder = 'h264_nvenc' if use_gpu else 'libx264'

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', f"ass='{ass_ffmpeg}'",
        '-c:v', encoder,
        '-b:v', '5M',
        '-c:a', 'copy',
        output_path,
    ]

    log.info(f"Burning subtitles: {ass_path} -> {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        # Fallback: try with drawtext if ASS fails
        log.warning(f"ASS burn failed, trying drawtext fallback: {result.stderr[:200]}")
        return _burn_drawtext_fallback(video_path, ass_path, output_path, encoder)

    log.info(f"Subtitled video: {output_path}")
    return output_path


def _burn_drawtext_fallback(
    video_path: str,
    ass_path: str,
    output_path: str,
    encoder: str,
) -> str:
    """Fallback: read ASS and use drawtext filters."""
    # Parse the ASS to extract dialogue lines
    segments = parse_ass_dialogues(ass_path)
    if not segments:
        log.warning("No dialogues found in ASS, returning original video")
        return video_path

    # Build drawtext filter chain
    filters = []
    for seg in segments:
        text = seg['text'].replace("'", "\\'").replace('"', '\\"')
        # Remove ASS formatting tags
        text = re.sub(r'\{[^}]*\}', '', text)
        text = text.replace('\\N', '\n')

        filters.append(
            f"drawtext=text='{text}':"
            f"fontsize=60:fontcolor=white:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y=h*0.75:"
            f"enable='between(t,{seg['start']},{seg['end']})'"
        )

    vf = ','.join(filters) if filters else 'null'

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', vf,
        '-c:v', encoder,
        '-b:v', '5M',
        '-c:a', 'copy',
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log.error(f"Drawtext fallback also failed: {result.stderr[:200]}")
        return video_path

    return output_path


def parse_ass_dialogues(ass_path: str) -> List[Dict]:
    """Parse ASS file to extract dialogue timing and text."""
    dialogues = []
    with open(ass_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('Dialogue:'):
                parts = line.split(',', 9)
                if len(parts) >= 10:
                    start = _parse_ass_time(parts[1].strip())
                    end = _parse_ass_time(parts[2].strip())
                    text = parts[9].strip()
                    dialogues.append({'start': start, 'end': end, 'text': text})
    return dialogues


def _parse_ass_time(time_str: str) -> float:
    """Parse ASS time H:MM:SS.CC to seconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s_cs = parts[2].split('.')
        s = int(s_cs[0])
        cs = int(s_cs[1]) if len(s_cs) > 1 else 0
        return h * 3600 + m * 60 + s + cs / 100
    return 0.0


def create_subtitles_from_narration(
    narration_segments: List[Dict],
    output_dir: str,
    style: str = 'shorts',
) -> str:
    """
    Create ASS subtitle file from narration segments.

    narration_segments: [
        {"text": "In the darkness...", "start_s": 0.0, "duration_s": 3.5, "emotion": "dark"},
        {"text": "Griffith betrayed...", "start_s": 3.5, "duration_s": 4.0, "emotion": "tragic"},
    ]
    """
    segments = []
    for ns in narration_segments:
        segments.append({
            'text': ns['text'],
            'start_s': ns['start_s'],
            'end_s': ns['start_s'] + ns['duration_s'],
            'emotion': ns.get('emotion', 'default'),
        })

    # Determine dominant emotion for overall style
    emotions = [s.get('emotion', 'default') for s in segments]
    dominant = max(set(emotions), key=emotions.count) if emotions else 'default'

    ass_path = os.path.join(output_dir, 'subtitles.ass')
    return generate_ass_subtitles(segments, ass_path, style=style, emotion=dominant)
