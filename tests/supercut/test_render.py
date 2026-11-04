from __future__ import annotations

import subprocess

import pytest

from apps.media.models import Mezzanine, media_cache_dir
from apps.supercut import lessons, planner, render, tts
from tests.supercut.helpers import fake_tts, integrated_lufs, needs_ffmpeg, probe, seed_fear_world
from utils.ffmpeg import FFmpegError

MEZZ = Mezzanine(path="m.mkv", start_ms=4_000, end_ms=12_000, requested_start_ms=5_000, requested_end_ms=10_000)


# ── unidades: comandos y textos ─────────────────────────────────────


@pytest.mark.unit
def test_segment_cmd_cuts_relative_to_mezzanine_and_maps_streams():
    cmd = render.build_segment_cmd(MEZZ, 5_000, 9_500, "seg.mkv", draws=["drawtext=x"])
    assert cmd[cmd.index("-ss") + 1] == "1.000" and cmd[cmd.index("-t") + 1] == "4.500"
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "boxblur" in graph and "overlay" in graph and "drawtext=x" in graph
    assert "[0:a:0]" in graph and "sidechaincompress" not in graph
    assert "pcm_s16le" in cmd and cmd[cmd.index("-map_chapters") + 1] == "-1"
    with pytest.raises(ValueError):
        render.build_segment_cmd(MEZZ, 3_000, 9_000, "seg.mkv", draws=[])


@pytest.mark.unit
def test_segment_cmd_with_narration_ducks_and_silent_source_gets_anullsrc():
    cmd = render.build_segment_cmd(MEZZ, 5_000, 9_000, "seg.mkv", draws=[], narration="n.mp3", has_audio=False)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "anullsrc" in " ".join(cmd) and "[1:a]" in graph and "[2:a]" in graph
    assert "sidechaincompress" in graph and "amix=inputs=2" in graph


@pytest.mark.unit
def test_final_cmd_two_pass_loudnorm_and_faststart(tmp_path):
    measured = {"input_i": -20.1, "input_tp": -3.0, "input_lra": 5.0, "input_thresh": -30.0, "target_offset": 0.2}
    cmd = render.build_final_cmd(tmp_path / "l.txt", tmp_path / "o.mp4", measured)
    af = cmd[cmd.index("-af") + 1]
    assert "I=-14" in af and "measured_I=-20.1" in af and "linear=true" in af
    assert cmd[cmd.index("-c:v") + 1] == "copy" and "+faststart" in cmd and "-map_chapters" in cmd
    single = render.build_final_cmd(tmp_path / "l.txt", tmp_path / "o.mp4", None)
    assert "measured_I" not in single[single.index("-af") + 1]


@pytest.mark.unit
def test_wrap_lines_and_text_files_use_lf_only(tmp_path):
    assert render.wrap_lines("Primera línea\nsegunda") == ["Primera línea", "segunda"]
    long = render.wrap_lines("una frase muy larga " * 6, width=20, max_lines=2)
    assert len(long) == 2 and long[-1].endswith("…")
    tf = render.TextFiles(tmp_path)
    escaped = tf.path("hola\r\nmundo")
    assert next(tmp_path.glob("*.txt")).read_bytes() == b"hola\nmundo"      # sin CR
    assert "\\" not in escaped.replace("\\:", "") and ":" not in escaped.replace("\\:", "")
    dt = render.drawtext("font", escaped, size=40, y=10, box=True, enable="lt(t,3)")
    assert "expansion=none" in dt and "box=1" in dt and "enable='lt(t,3)'" in dt


@pytest.mark.unit
def test_concat_list_quotes_paths(tmp_path):
    lst = render.write_concat_list([tmp_path / "a b.mkv", tmp_path / "it's.mkv"], tmp_path / "c.txt")
    text = lst.read_bytes().decode()
    assert "\r" not in text and text.count("file '") == 2 and "it'\\''s.mkv" in text


# ── integración: render real con masters sintéticos ─────────────────


def _lesson(sconn, masters, **kw):
    seed_fear_world(sconn, masters)
    return planner.plan_lesson(sconn, "emotion:fear", max_duration_s=kw.pop("max_duration_s", 16), **kw)


@needs_ffmpeg
@pytest.mark.integration
@pytest.mark.slow
def test_render_lesson_produces_vertical_short(sconn, masters):
    lesson = _lesson(sconn, masters)
    stages = []
    res = render.render_lesson(sconn, lesson["id"], progress=lambda s, p, d: stages.append((s, p)), narrate=False)
    out = lessons.video_path(lesson["id"])
    assert res["output_path"] == str(out) and out.exists()
    info = probe(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["codec_name"]) == (1080, 1920, "h264")
    assert audio["codec_name"] == "aac" and int(audio["sample_rate"]) == 48_000
    assert len(info["streams"]) == 2                                        # sin pistas de datos/capítulos
    expected = sum(i["out_ms"] - i["in_ms"] for i in lesson["items"]) / 1000 + render.END_CARD_S
    assert abs(res["duration_s"] - expected) < 0.35 and res["duration_s"] <= 16.3
    assert abs(integrated_lufs(out) - render.TARGET_LUFS) < 1.5
    after = lessons.get_lesson(sconn, lesson["id"])
    assert after["status"] == "rendered" and after["video_url"] == f"/api/lessons/{lesson['id']}/video"
    assert stages[-1] == ("done", 100) and [p for _, p in stages] == sorted(p for _, p in stages)
    assert not any(media_cache_dir("work").iterdir())                       # carpeta de trabajo borrada
    chapters = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "csv", str(out)],
                              capture_output=True, text=True).stdout.strip()
    assert chapters == ""


@needs_ffmpeg
@pytest.mark.integration
@pytest.mark.slow
def test_render_with_narration_calls_tts_per_segment_and_outro(sconn, masters, monkeypatch):
    calls = []

    def spy(text, **kw):
        calls.append(text)
        return fake_tts(text, **kw)

    monkeypatch.setattr(tts, "synthesize", spy)
    lesson = _lesson(sconn, masters)
    res = render.render_lesson(sconn, lesson["id"])                          # narrate=None → hay guion
    assert res["narration"] is True and len(calls) == len(lesson["items"]) + 1
    assert calls[0].startswith(lesson["script"]["hook"])                     # gancho + 1er tramo
    assert abs(integrated_lufs(res["output_path"]) - render.TARGET_LUFS) < 1.5


@needs_ffmpeg
@pytest.mark.integration
def test_render_failure_returns_lesson_to_draft(sconn, masters, tmp_path):
    lesson = _lesson(sconn, masters)
    sconn.execute("UPDATE media_assets SET master_uri = ?", (str(tmp_path / "missing.mkv"),))
    sconn.commit()
    with pytest.raises(FFmpegError):
        render.render_lesson(sconn, lesson["id"], narrate=False)
    assert lessons.get_status(sconn, lesson["id"]) == "draft"


@pytest.mark.integration
def test_render_refuses_locked_lesson_and_narration_without_script(sconn):
    seed_fear_world(sconn)
    lesson = planner.plan_lesson(sconn, "emotion:fear")
    lessons.begin_render(sconn, lesson["id"])
    with pytest.raises(lessons.InvalidState):
        render.render_lesson(sconn, lesson["id"], narrate=False)
    sconn.execute("UPDATE lessons SET status = 'draft', script_json = NULL WHERE id = ?", (lesson["id"],))
    sconn.commit()
    with pytest.raises(ValueError):
        render.render_lesson(sconn, lesson["id"], narrate=True)
