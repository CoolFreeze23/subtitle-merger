#!/usr/bin/env python3
"""Batch merge pairs of SRT subtitle files into styled ASS files (GUI)."""

import re
import os
import sys
import json
import subprocess
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
from pathlib import Path
from difflib import SequenceMatcher

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

try:
    import sv_ttk
    HAS_THEME = True
except ImportError:
    HAS_THEME = False

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "batch_2srt2ass_config.json"

# ---------------------------------------------------------------------------
# Configuration system
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "top_lang_name": "English",
    "top_lang_code": "en",
    "top_lang_tags": "en,eng,english",
    "bot_lang_name": "Portuguese",
    "bot_lang_code": "pt",
    "bot_lang_tags": "pt,por,portuguese",
    "bot_primary_colour": "&H0000FFFF",
    "bot_outline_colour": "&H00000000",
    "bot_back_colour": "&H80000000",
    "bot_fontsize_reduction": 4,
    "output_pattern": "{basename}.{lang}.ass",
    "track_title": "For Julia <3",
    "last_top_dir": "",
    "last_bot_dir": "",
    "last_mkv_dir": "",
    "last_tpl_path": "",
    "window_geometry": "",
    "templates": {},
}

_cfg: dict = {}


def load_config() -> dict:
    raw: dict = {}
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k, v in DEFAULT_CONFIG.items():
        if k not in raw:
            raw[k] = v
    return raw


def save_config(data: dict):
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def init_config():
    global _cfg
    _cfg = load_config()


def cfg_get(key: str):
    return _cfg.get(key, DEFAULT_CONFIG.get(key))


def cfg_set(key: str, value):
    _cfg[key] = value


def cfg_save():
    save_config(_cfg)


def load_templates() -> dict[str, str]:
    return _cfg.get("templates", {})


def save_templates(templates: dict[str, str]):
    _cfg["templates"] = templates
    cfg_save()


def get_top_tags() -> set[str]:
    return {t.strip().lower() for t in cfg_get("top_lang_tags").split(",") if t.strip()}


def get_bot_tags() -> set[str]:
    return {t.strip().lower() for t in cfg_get("bot_lang_tags").split(",") if t.strip()}


# ---------------------------------------------------------------------------
# Color conversion helpers (ASS &HBBGGRR <-> #RRGGBB)
# ---------------------------------------------------------------------------

def ass_color_to_rgb(ass_color: str) -> str:
    h = ass_color.replace("&H", "").replace("&h", "").lstrip("0") or "0"
    h = h.zfill(6)
    if len(h) == 8:
        h = h[2:]
    elif len(h) > 6:
        h = h[-6:]
    h = h.zfill(6)
    bb, gg, rr = h[0:2], h[2:4], h[4:6]
    return f"#{rr}{gg}{bb}"


def rgb_to_ass_color(rgb_hex: str, alpha: str = "00") -> str:
    rgb_hex = rgb_hex.lstrip("#").zfill(6)
    rr, gg, bb = rgb_hex[0:2], rgb_hex[2:4], rgb_hex[4:6]
    return f"&H{alpha}{bb}{gg}{rr}".upper()


# ---------------------------------------------------------------------------
# ASS template parsing
# ---------------------------------------------------------------------------

def parse_ass_template(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    script_info: list[str] = []
    styles: list[str] = []
    current: list[str] | None = None

    for line in lines:
        stripped = line.strip()
        if stripped == "[Script Info]":
            current = script_info
            current.append(stripped)
            continue
        if stripped == "[V4+ Styles]":
            current = styles
            current.append(stripped)
            continue
        if stripped.startswith("["):
            current = None
            continue
        if current is not None and stripped:
            if stripped.startswith(";"):
                continue
            current.append(stripped)

    return script_info, styles

# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------

SRT_BLOCK = re.compile(
    r"(\d+)\s*\r?\n"
    r"(\d{2}:\d{2}:\d{2})[.,](\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2})[.,](\d{3})\s*\r?\n"
    r"((?:(?!\r?\n\r?\n).)*)",
    re.DOTALL,
)

HTML_TAG = re.compile(r"<[^>]+>")


def srt_ts_to_ass(hms: str, ms: str) -> str:
    h, m, s = hms.split(":")
    centiseconds = int(ms[:2]) if len(ms) >= 2 else int(ms) * 10
    return f"{int(h)}:{m}:{s}.{centiseconds:02d}"


def parse_srt(path: Path) -> list[dict]:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    text = text.strip() + "\n\n"
    cues = []
    for m in SRT_BLOCK.finditer(text):
        start = srt_ts_to_ass(m.group(2), m.group(3))
        end = srt_ts_to_ass(m.group(4), m.group(5))
        body = m.group(6).strip()
        body = HTML_TAG.sub("", body)
        body = body.replace("\r\n", "\n").replace("\r", "\n")
        body = re.sub(r"\n", r"\\N", body)
        cues.append({"start": start, "end": end, "text": body})
    return cues

# ---------------------------------------------------------------------------
# ASS generation
# ---------------------------------------------------------------------------

def build_ass(
    script_info: list[str],
    styles: list[str],
    top_cues: list[dict],
    bot_cues: list[dict],
) -> str:
    track_title = cfg_get("track_title")
    bot_code = cfg_get("bot_lang_code")
    lines: list[str] = []

    for l in script_info:
        if l.startswith("Title:"):
            continue
        lines.append(l)
    lines.insert(1, f"Title: {track_title}")
    lines.insert(2, f"Language: {bot_code}")
    lines.append("")

    for l in styles:
        lines.append(l)
    lines.append("")

    lines.append("[Events]")
    lines.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )

    events = []
    for c in top_cues:
        events.append((c["start"], "Top", c))
    for c in bot_cues:
        events.append((c["start"], "Bot", c))

    events.sort(key=lambda e: e[0])

    for _ts, style, cue in events:
        lines.append(
            f"Dialogue: 0,{cue['start']},{cue['end']},{style},,0,0,0,,{cue['text']}"
        )

    return "\r\n".join(lines) + "\r\n"

# ---------------------------------------------------------------------------
# File matching
# ---------------------------------------------------------------------------

LANG_SUFFIXES = re.compile(
    r"[._-](?:en|eng|english|pt|por|pt-br|ptbr|portuguese|es|esp|spa|spanish|"
    r"fr|fre|fra|french|de|deu|ger|german|it|ita|italian|ja|jpn|japanese|"
    r"ko|kor|korean|zh|chi|zho|chinese|ru|rus|russian|ar|ara|arabic|"
    r"hi|hin|hindi|tr|tur|turkish|pl|pol|polish|nl|dut|nld|dutch|"
    r"sv|swe|swedish|da|dan|danish|no|nor|norwegian|fi|fin|finnish|"
    r"cs|cze|ces|czech|hu|hun|hungarian|ro|ron|rum|romanian|"
    r"th|tha|thai|vi|vie|vietnamese|id|ind|indonesian|ms|msa|malay|"
    r"uk|ukr|ukrainian|el|gre|ell|greek|he|heb|hebrew|"
    r"sdh|cc|forced|full|default|hearing.impaired|hi)"
    r"$",
    re.IGNORECASE,
)


def base_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = LANG_SUFFIXES.sub("", stem)
    stem = LANG_SUFFIXES.sub("", stem)
    return stem.lower().strip()


def match_files(
    top_files: list[str], bot_files: list[str]
) -> tuple[list[tuple[str, str, float]], list[str], list[str]]:
    top_bases = {f: base_name(f) for f in top_files}
    bot_bases = {f: base_name(f) for f in bot_files}

    pairs: list[tuple[str, str, float]] = []
    used_bot: set[str] = set()

    for tf in top_files:
        best_score = 0.0
        best_bf = ""
        for bf in bot_files:
            if bf in used_bot:
                continue
            if top_bases[tf] == bot_bases[bf]:
                score = 1.0
            else:
                score = SequenceMatcher(None, top_bases[tf], bot_bases[bf]).ratio()
            if score > best_score:
                best_score = score
                best_bf = bf
        if best_score >= 0.4 and best_bf:
            pairs.append((tf, best_bf, best_score))
            used_bot.add(best_bf)

    unmatched_top = [f for f in top_files if not any(p[0] == f for p in pairs)]
    unmatched_bot = [f for f in bot_files if f not in used_bot]

    pairs.sort(key=lambda p: p[0].lower())
    return pairs, unmatched_top, unmatched_bot


INTERMEDIATE_SUFFIXES = re.compile(r"\.prepared$", re.IGNORECASE)


def output_name(top_srt: str) -> str:
    stem = Path(top_srt).stem
    stem = INTERMEDIATE_SUFFIXES.sub("", stem)
    cleaned = LANG_SUFFIXES.sub("", stem)
    cleaned = LANG_SUFFIXES.sub("", cleaned)
    pattern = cfg_get("output_pattern")
    lang = cfg_get("bot_lang_code")
    return pattern.replace("{basename}", cleaned).replace("{lang}", lang)

# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------

def find_ffmpeg() -> tuple[str, str]:
    for name in ("ffmpeg", "ffprobe"):
        if shutil.which(name):
            continue
        fallback = Path(r"C:\ffmpeg\bin") / f"{name}.exe"
        if fallback.is_file():
            os.environ["PATH"] = str(fallback.parent) + os.pathsep + os.environ.get("PATH", "")
        else:
            raise FileNotFoundError(
                f"{name} not found on PATH or at {fallback}.\n"
                "Install FFmpeg and make sure it's on your PATH."
            )
    return (shutil.which("ffmpeg") or "ffmpeg",
            shutil.which("ffprobe") or "ffprobe")


FORCED_TITLE_RE = re.compile(r"\bforced\b", re.IGNORECASE)


def probe_subtitles(mkv_path: Path) -> list[dict]:
    _, ffprobe = find_ffmpeg()
    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-select_streams", "s",
        str(mkv_path),
    ]
    result = subprocess.run(cmd, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{result.stderr.decode('utf-8', errors='replace')}")

    stdout = result.stdout.decode("utf-8", errors="replace").strip() if result.stdout else ""
    if not stdout:
        return []
    data = json.loads(stdout)
    tracks: list[dict] = []
    for s in data.get("streams", []):
        tags = s.get("tags", {})
        disp = s.get("disposition", {})
        title = tags.get("title", "")
        forced = bool(disp.get("forced", 0)) or bool(FORCED_TITLE_RE.search(title))
        tracks.append({
            "index": s["index"],
            "codec": s.get("codec_name", "?"),
            "language": tags.get("language", "und"),
            "title": title,
            "forced": forced,
        })
    return tracks


def extract_subtitle(mkv_path: Path, stream_index: int, out_path: Path,
                     codec: str = "srt") -> Path:
    ffmpeg, _ = find_ffmpeg()
    is_ass = codec.lower() in ("ass", "ssa")
    if is_ass:
        out_path = out_path.with_suffix(".ass")
    cmd = [
        ffmpeg, "-y", "-v", "quiet",
        "-i", str(mkv_path),
        "-map", f"0:{stream_index}",
        "-c:s", "copy" if is_ass else "srt",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg extraction failed:\n{result.stderr.decode('utf-8', errors='replace')}")
    return out_path


def auto_pick_tracks(tracks: list[dict], skip_forced: bool = True) -> tuple[list[dict], list[dict]]:
    pool = [t for t in tracks if not (skip_forced and t.get("forced"))]
    top_tags = get_top_tags()
    bot_tags = get_bot_tags()
    top = [t for t in pool if t["language"].lower() in top_tags]
    bot = [t for t in pool if t["language"].lower() in bot_tags]
    return top, bot

# ---------------------------------------------------------------------------
# ASS-to-ASS merge helpers
# ---------------------------------------------------------------------------

POS_TAG_RE = re.compile(r"\\(?:pos|move)\([^)]*\)")
LAYER_RE = re.compile(r"^(Dialogue|Comment):\s*(\d+)(,.*)$")
ENG_LAYER_OFFSET = 10

POS_XY_RE = re.compile(r"\\pos\(([^,]+),([^)]+)\)")
MOVE_XY_RE = re.compile(r"\\move\(([^,]+),([^,]+),([^,]+),([^,)]+)")


def _offset_pos_y(raw_line: str, y_offset: int) -> str:
    def shift_pos(m):
        x, y = m.group(1), m.group(2)
        try:
            return f"\\pos({x},{int(float(y)) + y_offset})"
        except ValueError:
            return m.group(0)

    def shift_move(m):
        x1, y1, x2, y2 = m.group(1), m.group(2), m.group(3), m.group(4)
        try:
            new_y1 = int(float(y1)) + y_offset
            new_y2 = int(float(y2)) + y_offset
            return f"\\move({x1},{new_y1},{x2},{new_y2}"
        except ValueError:
            return m.group(0)

    raw_line = POS_XY_RE.sub(shift_pos, raw_line)
    raw_line = MOVE_XY_RE.sub(shift_move, raw_line)
    return raw_line


FS_OVERRIDE_RE = re.compile(r"\\fs(\d+(?:\.\d+)?)")


def _ass_time_to_cs(ts: str) -> int:
    parts = ts.split(":")
    h, m = int(parts[0]), int(parts[1])
    s_parts = parts[2].split(".")
    s, cs = int(s_parts[0]), int(s_parts[1])
    return h * 360000 + m * 6000 + s * 100 + cs


def _parse_event_times(raw_line: str) -> tuple[str, str] | None:
    parts = raw_line.split(",", 3)
    if len(parts) >= 3:
        return parts[1].strip(), parts[2].strip()
    return None


def _get_event_pos_y(raw_line: str) -> int | None:
    m = POS_XY_RE.search(raw_line)
    if m:
        try:
            return int(float(m.group(2)))
        except ValueError:
            pass
    return None


def _get_event_font_size(raw_line: str, style_font_map: dict[str, int]) -> int:
    m = FS_OVERRIDE_RE.search(raw_line)
    if m:
        try:
            return int(float(m.group(1)))
        except ValueError:
            pass
    parts = raw_line.split(",", 4)
    if len(parts) >= 5:
        style = parts[3].strip()
        return style_font_map.get(style, 20)
    return 20


def _build_style_font_map(style_lines: list[str]) -> dict[str, int]:
    font_map: dict[str, int] = {}
    for line in style_lines:
        if not line.startswith("Style:"):
            continue
        parts = line.split(",")
        if len(parts) >= 3:
            name = parts[0].replace("Style:", "").strip()
            try:
                font_map[name] = int(float(parts[2].strip()))
            except ValueError:
                pass
    return font_map


POR_BOT_GAP = 2
SIGN_PROXIMITY_PX = 60


def _compute_sign_offsets(
    eng_events: list[tuple[str, str]],
    por_events: list[tuple[str, str]],
    style_font_map: dict[str, int],
) -> dict[int, int]:
    eng_signs: list[tuple[int, int, int, int]] = []
    for _ts, raw in eng_events:
        parts = raw.split(",", 4)
        if len(parts) < 5:
            continue
        style = parts[3].strip()
        if _is_dialogue_style(style):
            continue
        pos_y = _get_event_pos_y(raw)
        times = _parse_event_times(raw)
        if pos_y is None or times is None:
            continue
        fs = _get_event_font_size(raw, style_font_map)
        eng_signs.append((
            _ass_time_to_cs(times[0]),
            _ass_time_to_cs(times[1]),
            pos_y,
            fs,
        ))

    offsets: dict[int, int] = {}
    for idx, (_ts, raw) in enumerate(por_events):
        parts = raw.split(",", 4)
        if len(parts) < 5:
            continue
        style = parts[3].strip()
        if _is_dialogue_style(style):
            continue
        por_y = _get_event_pos_y(raw)
        times = _parse_event_times(raw)
        if por_y is None or times is None:
            continue
        por_fs = _get_event_font_size(raw, style_font_map)
        por_start = _ass_time_to_cs(times[0])
        por_end = _ass_time_to_cs(times[1])

        best_eng_bottom = 0
        for eng_s, eng_e, eng_y, eng_fs in eng_signs:
            if por_start >= eng_e or por_end <= eng_s:
                continue
            if abs(por_y - eng_y) > SIGN_PROXIMITY_PX:
                continue
            eng_bottom = eng_y + eng_fs + POR_BOT_GAP
            best_eng_bottom = max(best_eng_bottom, eng_bottom)

        if best_eng_bottom > 0 and por_y < best_eng_bottom:
            offsets[idx] = best_eng_bottom - por_y

    return offsets


def _bump_event_layer(raw_line: str, offset: int) -> str:
    m = LAYER_RE.match(raw_line)
    if m:
        old_layer = int(m.group(2))
        return f"{m.group(1)}: {old_layer + offset}{m.group(3)}"
    return raw_line


def rename_ass_styles(text: str, suffix: str = "_BR") -> str:
    lines = text.splitlines()
    style_names: list[str] = []
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Style:"):
            parts = stripped.split(",", 1)
            name = parts[0].replace("Style:", "").strip()
            new_name = name + suffix
            style_names.append(name)
            out.append(f"Style: {new_name},{parts[1]}")
            continue
        out.append(line)

    if not style_names:
        return "\n".join(out)

    result_lines: list[str] = []
    for line in out:
        stripped = line.strip()
        if stripped.startswith("Dialogue:") or stripped.startswith("Comment:"):
            parts = stripped.split(",", 4)
            if len(parts) >= 5:
                style = parts[3].strip()
                if style in style_names:
                    parts[3] = style + suffix
                line = ",".join(parts)
        result_lines.append(line)

    return "\n".join(result_lines)


def strip_position_tags(text: str) -> str:
    r"""Remove \pos(...) and \move(...) from dialogue events only."""
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Dialogue:") or stripped.startswith("Comment:"):
            parts = stripped.split(",", 4)
            if len(parts) >= 5:
                style = parts[3].strip()
                if _is_dialogue_style(style):
                    line = POS_TAG_RE.sub("", line)
        out.append(line)
    return "\n".join(out)


def _read_ass_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def parse_ass_sections(path: Path) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    text = _read_ass_text(path)
    lines = text.splitlines()

    script_info: list[str] = []
    styles: list[str] = []
    events: list[tuple[str, str]] = []
    current: list[str] | None = None

    for line in lines:
        stripped = line.strip()
        if stripped == "[Script Info]":
            current = script_info
            current.append(stripped)
            continue
        if stripped == "[V4+ Styles]":
            current = styles
            current.append(stripped)
            continue
        if stripped == "[Events]":
            current = None
            continue
        if stripped.startswith("["):
            current = None
            continue

        if current is not None and stripped:
            if stripped.startswith(";"):
                continue
            current.append(stripped)

        if stripped.startswith("Dialogue:") or stripped.startswith("Comment:"):
            parts = stripped.split(",", 2)
            if len(parts) >= 3:
                events.append((parts[1].strip(), stripped))

    return script_info, styles, events


def parse_ass_events(path: Path) -> list[tuple[str, str]]:
    _, _, events = parse_ass_sections(path)
    return events


SIGN_MODES = ("shift", "strip")


def _get_style_names(style_lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in style_lines:
        if line.startswith("Style:"):
            name = line.split(",", 1)[0].replace("Style:", "").strip()
            names.add(name)
    return names


def _check_duplicate_styles(eng_styles: list[str], por_styles: list[str]) -> list[str]:
    """Return list of style names that appear in both sets."""
    eng_names = _get_style_names(eng_styles)
    por_names = _get_style_names(por_styles)
    return sorted(eng_names & por_names)


def build_ass_merged(
    script_info: list[str],
    eng_styles: list[str],
    por_styles: list[str],
    eng_events: list[tuple[str, str]],
    por_events: list[tuple[str, str]],
    sign_mode: str = "shift",
    match_font_to_top: bool = False,
) -> str:
    track_title = cfg_get("track_title")
    bot_code = cfg_get("bot_lang_code")
    lines: list[str] = []

    for l in script_info:
        if l.startswith("Title:") or l.startswith("Collisions:"):
            continue
        lines.append(l)
    lines.insert(1, f"Title: {track_title}")
    lines.insert(2, f"Language: {bot_code}")
    lines.append("")

    lines.append("[V4+ Styles]")
    fmt_line = None
    eng_style_lines: list[str] = []
    for l in eng_styles:
        if l.startswith("Format:"):
            fmt_line = l
        elif l.startswith("Style:"):
            eng_style_lines.append(l)

    por_style_lines: list[str] = []
    for l in por_styles:
        if l.startswith("Format:") and fmt_line is None:
            fmt_line = l
        elif l.startswith("Style:"):
            por_style_lines.append(l)

    eng_style_lines = adjust_eng_styles(eng_style_lines)

    font_info = None
    if match_font_to_top:
        font_info = _extract_primary_dialogue_font(eng_style_lines)

    play_res_y = _get_play_res_y(script_info)
    max_eng_bot_mv = _get_max_bottom_dialogue_margin(eng_style_lines)
    por_bot_mv = play_res_y - max_eng_bot_mv + POR_BOT_GAP

    max_eng_top_bottom = _get_max_top_dialogue_bottom(eng_style_lines)
    por_top_mv = max_eng_top_bottom + POR_BOT_GAP if max_eng_top_bottom > 0 else None

    por_style_lines = adjust_por_styles(
        por_style_lines,
        por_bot_margin=por_bot_mv,
        por_top_margin=por_top_mv,
        match_font=font_info,
    )

    if fmt_line:
        lines.append(fmt_line)
    for l in eng_style_lines:
        lines.append(l)
    for l in por_style_lines:
        lines.append(l)
    lines.append("")

    lines.append("[Events]")
    lines.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )

    all_style_lines = eng_style_lines + por_style_lines
    style_font_map = _build_style_font_map(all_style_lines)

    sign_offsets: dict[int, int] = {}
    if sign_mode == "shift":
        sign_offsets = _compute_sign_offsets(
            eng_events, por_events, style_font_map,
        )

    tagged: list[tuple[str, int, str]] = []
    for ts, raw in eng_events:
        tagged.append((ts, 0, _bump_event_layer(raw, ENG_LAYER_OFFSET)))
    for idx, (ts, raw) in enumerate(por_events):
        parts = raw.split(",", 4)
        if len(parts) >= 5:
            style = parts[3].strip()
            if not _is_dialogue_style(style):
                if sign_mode == "shift" and idx in sign_offsets:
                    raw = _offset_pos_y(raw, sign_offsets[idx])
                elif sign_mode == "strip":
                    raw = POS_TAG_RE.sub("", raw)
        tagged.append((ts, 1, raw))
    tagged.sort(key=lambda e: (e[0], e[1]))

    for _ts, _order, raw_line in tagged:
        lines.append(raw_line)

    return "\r\n".join(lines) + "\r\n"


ASS_BOTTOM_ALIGNMENTS = {"1", "2", "3"}
ASS_TOP_ALIGNMENTS = {"7", "8", "9"}
BOTTOM_TO_TOP_ALIGN = {"1": "7", "2": "8", "3": "9"}

SIGN_STYLE_RE = re.compile(
    r"(?:sign|title|eyecatch|lyric|cred|show_|ep_|next_)",
    re.IGNORECASE,
)


def _is_dialogue_style(name: str) -> bool:
    clean = name.replace("_BR", "").strip()
    return SIGN_STYLE_RE.search(clean) is None


def _get_play_res_y(script_info: list[str]) -> int:
    for line in script_info:
        if line.startswith("PlayResY:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return 360


def _get_max_bottom_dialogue_margin(style_lines: list[str]) -> int:
    max_mv = 0
    for line in style_lines:
        if not line.startswith("Style:"):
            continue
        parts = line.split(",")
        if len(parts) >= 22:
            name = parts[0].replace("Style:", "").strip()
            alignment = parts[18].strip()
            if alignment in ASS_BOTTOM_ALIGNMENTS and _is_dialogue_style(name):
                try:
                    max_mv = max(max_mv, int(parts[21].strip()))
                except ValueError:
                    pass
    return max_mv


def _get_max_top_dialogue_bottom(style_lines: list[str]) -> int:
    max_bottom = 0
    for line in style_lines:
        if not line.startswith("Style:"):
            continue
        parts = line.split(",")
        if len(parts) >= 22:
            name = parts[0].replace("Style:", "").strip()
            alignment = parts[18].strip()
            if alignment in ASS_TOP_ALIGNMENTS and _is_dialogue_style(name):
                try:
                    mv = int(parts[21].strip())
                    fs = int(float(parts[2].strip()))
                    max_bottom = max(max_bottom, mv + fs)
                except ValueError:
                    pass
    return max_bottom


def adjust_eng_styles(style_lines: list[str], margin_offset: int = 20) -> list[str]:
    out: list[str] = []
    for line in style_lines:
        if not line.startswith("Style:"):
            out.append(line)
            continue
        parts = line.split(",")
        if len(parts) >= 22:
            name = parts[0].replace("Style:", "").strip()
            alignment = parts[18].strip()
            if alignment in ASS_BOTTOM_ALIGNMENTS and _is_dialogue_style(name):
                try:
                    mv = int(parts[21].strip())
                    parts[21] = str(mv + margin_offset)
                except ValueError:
                    pass
        out.append(",".join(parts))
    return out


def _extract_primary_dialogue_font(style_lines: list[str]) -> dict | None:
    """Extract font properties from the first dialogue style found.

    ASS Style format indices:
      0=Name, 1=Fontname, 2=Fontsize, 3=PrimaryColour, 4=SecondaryColour,
      5=OutlineColour, 6=BackColour, 7=Bold, 8=Italic, 9=Underline,
      10=StrikeOut, 11=ScaleX, 12=ScaleY, 13=Spacing, 14=Angle,
      15=BorderStyle, 16=Outline, 17=Shadow, 18=Alignment, ...

    Returns dict with font-related fields to copy, or None.
    """
    for line in style_lines:
        if not line.startswith("Style:"):
            continue
        parts = line.split(",")
        if len(parts) < 23:
            continue
        name = parts[0].replace("Style:", "").strip()
        if _is_dialogue_style(name):
            return {
                "fontname": parts[1].strip(),
                "bold": parts[7].strip(),
                "italic": parts[8].strip(),
                "underline": parts[9].strip(),
                "strikeout": parts[10].strip(),
                "scale_x": parts[11].strip(),
                "scale_y": parts[12].strip(),
                "spacing": parts[13].strip(),
                "border_style": parts[15].strip(),
                "outline": parts[16].strip(),
                "shadow": parts[17].strip(),
            }
    return None


def adjust_por_styles(
    style_lines: list[str],
    por_bot_margin: int | None = None,
    por_top_margin: int | None = None,
    match_font: dict | None = None,
) -> list[str]:
    por_primary = cfg_get("bot_primary_colour")
    por_outline = cfg_get("bot_outline_colour")
    por_back = cfg_get("bot_back_colour")
    por_fs_reduction = int(cfg_get("bot_fontsize_reduction"))

    out: list[str] = []
    for line in style_lines:
        if not line.startswith("Style:"):
            out.append(line)
            continue
        parts = line.split(",")
        if len(parts) < 23:
            out.append(line)
            continue

        name = parts[0].replace("Style:", "").strip()
        is_dialogue = _is_dialogue_style(name)

        if is_dialogue:
            try:
                fs = float(parts[2].strip())
                parts[2] = str(max(10, int(fs - por_fs_reduction)))
            except ValueError:
                pass

            parts[3] = por_primary
            parts[5] = por_outline
            parts[6] = por_back

            if match_font:
                parts[1] = " " + match_font["fontname"]
                parts[7] = " " + match_font["bold"]
                parts[8] = " " + match_font["italic"]
                parts[9] = " " + match_font["underline"]
                parts[10] = " " + match_font["strikeout"]
                parts[11] = " " + match_font["scale_x"]
                parts[12] = " " + match_font["scale_y"]
                parts[13] = " " + match_font["spacing"]
                parts[15] = " " + match_font["border_style"]
                parts[16] = " " + match_font["outline"]
                parts[17] = " " + match_font["shadow"]

            alignment = parts[18].strip()
            if alignment in ASS_BOTTOM_ALIGNMENTS and por_bot_margin is not None:
                parts[18] = BOTTOM_TO_TOP_ALIGN[alignment]
                parts[21] = str(por_bot_margin)
            elif alignment in ASS_TOP_ALIGNMENTS and por_top_margin is not None:
                parts[21] = str(por_top_margin)

        out.append(",".join(parts))
    return out


def prepare_ass_for_merge(path: Path, is_portuguese: bool = False) -> Path:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    if is_portuguese:
        text = rename_ass_styles(text, "_BR")

    text = strip_position_tags(text)

    out_path = path.with_suffix(".prepared.ass")
    out_path.write_text(text, encoding="utf-8-sig")
    return out_path

# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

COLOR_PRESETS = {
    "Yellow": "&H0000FFFF",
    "White": "&H00FFFFFF",
    "Cyan": "&H00FFFF00",
    "Green": "&H0000FF00",
    "Orange": "&H0000A5FF",
    "Pink": "&H00CB69FF",
    "Red": "&H000000FF",
    "Light Blue": "&H00FF9B00",
}


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.grab_set()
        self.result = False

        pad = dict(padx=8, pady=3)
        row = 0

        # --- Language Pair ---
        lang_frame = ttk.LabelFrame(self, text="Language Pair", padding=8)
        lang_frame.grid(row=row, column=0, sticky="ew", **pad)
        row += 1

        ttk.Label(lang_frame, text="Top Language").grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(lang_frame, text="Name:").grid(row=1, column=0, sticky="w", padx=(0, 4))
        self.top_name_var = tk.StringVar(value=cfg_get("top_lang_name"))
        ttk.Entry(lang_frame, textvariable=self.top_name_var, width=15).grid(row=1, column=1, padx=2)

        ttk.Label(lang_frame, text="Code:").grid(row=1, column=2, sticky="w", padx=(8, 4))
        self.top_code_var = tk.StringVar(value=cfg_get("top_lang_code"))
        ttk.Entry(lang_frame, textvariable=self.top_code_var, width=6).grid(row=1, column=3, padx=2)

        ttk.Label(lang_frame, text="Tags (comma-sep):").grid(row=2, column=0, sticky="w", padx=(0, 4))
        self.top_tags_var = tk.StringVar(value=cfg_get("top_lang_tags"))
        ttk.Entry(lang_frame, textvariable=self.top_tags_var, width=35).grid(row=2, column=1, columnspan=3, sticky="ew", padx=2)

        ttk.Separator(lang_frame, orient="horizontal").grid(row=3, column=0, columnspan=4, sticky="ew", pady=6)

        ttk.Label(lang_frame, text="Bottom Language").grid(row=4, column=0, columnspan=4, sticky="w")

        ttk.Label(lang_frame, text="Name:").grid(row=5, column=0, sticky="w", padx=(0, 4))
        self.bot_name_var = tk.StringVar(value=cfg_get("bot_lang_name"))
        ttk.Entry(lang_frame, textvariable=self.bot_name_var, width=15).grid(row=5, column=1, padx=2)

        ttk.Label(lang_frame, text="Code:").grid(row=5, column=2, sticky="w", padx=(8, 4))
        self.bot_code_var = tk.StringVar(value=cfg_get("bot_lang_code"))
        ttk.Entry(lang_frame, textvariable=self.bot_code_var, width=6).grid(row=5, column=3, padx=2)

        ttk.Label(lang_frame, text="Tags (comma-sep):").grid(row=6, column=0, sticky="w", padx=(0, 4))
        self.bot_tags_var = tk.StringVar(value=cfg_get("bot_lang_tags"))
        ttk.Entry(lang_frame, textvariable=self.bot_tags_var, width=35).grid(row=6, column=1, columnspan=3, sticky="ew", padx=2)

        # --- Bottom Subtitle Style ---
        style_frame = ttk.LabelFrame(self, text="Bottom Subtitle Style", padding=8)
        style_frame.grid(row=row, column=0, sticky="ew", **pad)
        row += 1

        ttk.Label(style_frame, text="Text Color:").grid(row=0, column=0, sticky="w")
        self.bot_color_var = tk.StringVar(value=cfg_get("bot_primary_colour"))
        self._color_preview = tk.Canvas(style_frame, width=24, height=24, highlightthickness=1)
        self._color_preview.grid(row=0, column=1, padx=4)
        color_combo = ttk.Combobox(style_frame, textvariable=self.bot_color_var, width=20,
                                   values=list(COLOR_PRESETS.values()))
        color_combo.grid(row=0, column=2, padx=2)
        ttk.Button(style_frame, text="Pick", width=5,
                   command=lambda: self._pick_color(self.bot_color_var)).grid(row=0, column=3, padx=2)
        self.bot_color_var.trace_add("write", lambda *_: self._update_color_preview())

        ttk.Label(style_frame, text="Outline Color:").grid(row=1, column=0, sticky="w")
        self.bot_outline_var = tk.StringVar(value=cfg_get("bot_outline_colour"))
        self._outline_preview = tk.Canvas(style_frame, width=24, height=24, highlightthickness=1)
        self._outline_preview.grid(row=1, column=1, padx=4)
        ttk.Combobox(style_frame, textvariable=self.bot_outline_var, width=20,
                     values=list(COLOR_PRESETS.values())).grid(row=1, column=2, padx=2)
        ttk.Button(style_frame, text="Pick", width=5,
                   command=lambda: self._pick_color(self.bot_outline_var)).grid(row=1, column=3, padx=2)
        self.bot_outline_var.trace_add("write", lambda *_: self._update_color_preview())

        ttk.Label(style_frame, text="Font Size Reduction:").grid(row=2, column=0, sticky="w")
        self.fs_reduction_var = tk.IntVar(value=int(cfg_get("bot_fontsize_reduction")))
        fs_spin = ttk.Spinbox(style_frame, from_=0, to=20, width=5, textvariable=self.fs_reduction_var)
        fs_spin.grid(row=2, column=1, columnspan=2, sticky="w", padx=4)
        ttk.Label(style_frame, text="px smaller than top").grid(row=2, column=2, columnspan=2, sticky="w")

        # --- Output ---
        out_frame = ttk.LabelFrame(self, text="Output", padding=8)
        out_frame.grid(row=row, column=0, sticky="ew", **pad)
        row += 1

        ttk.Label(out_frame, text="Filename Pattern:").grid(row=0, column=0, sticky="w")
        self.pattern_var = tk.StringVar(value=cfg_get("output_pattern"))
        ttk.Entry(out_frame, textvariable=self.pattern_var, width=35).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(out_frame, text="Tokens: {basename} {lang}", foreground="gray").grid(
            row=1, column=1, sticky="w", padx=4)

        ttk.Label(out_frame, text="Track Title:").grid(row=2, column=0, sticky="w")
        self.title_var = tk.StringVar(value=cfg_get("track_title"))
        ttk.Entry(out_frame, textvariable=self.title_var, width=35).grid(row=2, column=1, sticky="ew", padx=4)

        # --- Buttons ---
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=row, column=0, sticky="e", **pad)

        ttk.Button(btn_frame, text="Reset Defaults", command=self._reset_defaults).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right", padx=4)

        self._update_color_preview()
        self.columnconfigure(0, weight=1)

    def _pick_color(self, var: tk.StringVar):
        try:
            initial = ass_color_to_rgb(var.get())
        except Exception:
            initial = "#FFFFFF"
        result = colorchooser.askcolor(color=initial, parent=self, title="Choose Color")
        if result and result[1]:
            var.set(rgb_to_ass_color(result[1]))

    def _update_color_preview(self):
        try:
            rgb = ass_color_to_rgb(self.bot_color_var.get())
            self._color_preview.configure(bg=rgb)
        except Exception:
            self._color_preview.configure(bg="#000000")
        try:
            rgb = ass_color_to_rgb(self.bot_outline_var.get())
            self._outline_preview.configure(bg=rgb)
        except Exception:
            self._outline_preview.configure(bg="#000000")

    def _reset_defaults(self):
        self.top_name_var.set(DEFAULT_CONFIG["top_lang_name"])
        self.top_code_var.set(DEFAULT_CONFIG["top_lang_code"])
        self.top_tags_var.set(DEFAULT_CONFIG["top_lang_tags"])
        self.bot_name_var.set(DEFAULT_CONFIG["bot_lang_name"])
        self.bot_code_var.set(DEFAULT_CONFIG["bot_lang_code"])
        self.bot_tags_var.set(DEFAULT_CONFIG["bot_lang_tags"])
        self.bot_color_var.set(DEFAULT_CONFIG["bot_primary_colour"])
        self.bot_outline_var.set(DEFAULT_CONFIG["bot_outline_colour"])
        self.fs_reduction_var.set(DEFAULT_CONFIG["bot_fontsize_reduction"])
        self.pattern_var.set(DEFAULT_CONFIG["output_pattern"])
        self.title_var.set(DEFAULT_CONFIG["track_title"])

    def _save(self):
        cfg_set("top_lang_name", self.top_name_var.get().strip())
        cfg_set("top_lang_code", self.top_code_var.get().strip())
        cfg_set("top_lang_tags", self.top_tags_var.get().strip())
        cfg_set("bot_lang_name", self.bot_name_var.get().strip())
        cfg_set("bot_lang_code", self.bot_code_var.get().strip())
        cfg_set("bot_lang_tags", self.bot_tags_var.get().strip())
        cfg_set("bot_primary_colour", self.bot_color_var.get().strip())
        cfg_set("bot_outline_colour", self.bot_outline_var.get().strip())
        cfg_set("bot_fontsize_reduction", self.fs_reduction_var.get())
        cfg_set("output_pattern", self.pattern_var.get().strip() or DEFAULT_CONFIG["output_pattern"])
        cfg_set("track_title", self.title_var.get().strip() or DEFAULT_CONFIG["track_title"])
        cfg_save()
        self.result = True
        self.destroy()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def _parse_dnd_paths(data: str) -> list[Path]:
    paths: list[Path] = []
    raw = data.strip()
    i = 0
    while i < len(raw):
        if raw[i] == "{":
            end = raw.index("}", i)
            paths.append(Path(raw[i + 1 : end]))
            i = end + 2
        elif raw[i] == " ":
            i += 1
        else:
            end = raw.find(" ", i)
            if end == -1:
                end = len(raw)
            paths.append(Path(raw[i:end]))
            i = end + 1
    return paths


class App(TkinterDnD.Tk if HAS_DND else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Subtitle Merger")
        self.minsize(900, 680)
        self.resizable(True, True)

        if HAS_THEME:
            sv_ttk.set_theme("dark")

        geo = cfg_get("window_geometry")
        if geo:
            try:
                self.geometry(geo)
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.pairs: list[tuple[str, str, float]] = []
        self.unmatched_top: list[str] = []
        self.unmatched_bot: list[str] = []
        self.template_path: Path | None = None
        self.script_info: list[str] = []
        self.styles: list[str] = []

        self.top_file_paths: dict[str, Path] = {}
        self.bot_file_paths: dict[str, Path] = {}
        self.saved_templates: dict[str, str] = load_templates()
        self._intermediate_files: list[Path] = []
        self._last_output_dir: Path | None = None
        self._converting = False
        self._remembered_top: dict | None = None
        self._remembered_bot: dict | None = None

        self._build_ui()
        self._bind_shortcuts()

    def _on_close(self):
        cfg_set("window_geometry", self.geometry())
        cfg_save()
        self.destroy()

    def _bind_shortcuts(self):
        self.bind_all("<Control-o>", lambda e: self._browse_mkv())
        self.bind_all("<Control-m>", lambda e: self._auto_match())
        self.bind_all("<Control-Return>", lambda e: self._convert_all())
        self.bind_all("<Delete>", lambda e: self._remove_pair())
        self.bind_all("<Control-comma>", lambda e: self._open_settings())

    # ---- UI construction ----

    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        # -- Menu bar --
        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open MKV...  (Ctrl+O)", command=self._browse_mkv)
        file_menu.add_separator()
        file_menu.add_command(label="Settings...  (Ctrl+,)", command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        # -- MKV drop zone --
        mkv_frame = ttk.LabelFrame(self, text="MKV Import", padding=6)
        mkv_frame.pack(fill="x", **pad)
        self.mkv_label = ttk.Label(
            mkv_frame,
            text="Drag MKV file(s) here or click Browse (Ctrl+O)",
            anchor="center", padding=10, relief="groove",
        )
        self.mkv_label.pack(side="left", fill="x", expand=True)
        ttk.Button(mkv_frame, text="Browse MKV", command=self._browse_mkv).pack(side="left", padx=(6, 0))
        self.skip_forced_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mkv_frame, text="Skip forced",
                         variable=self.skip_forced_var).pack(side="left", padx=(6, 0))
        ttk.Button(mkv_frame, text="Reset track memory", command=self._reset_track_memory).pack(side="left", padx=(6, 0))
        if HAS_DND:
            self.mkv_label.drop_target_register(DND_FILES)
            self.mkv_label.dnd_bind("<<Drop>>", self._on_drop_mkv)

        # -- Mode toggle --
        mode_frame = ttk.Frame(self)
        mode_frame.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value="folder")
        ttk.Label(mode_frame, text="Mode:").pack(side="left", padx=(0, 6))
        self._folder_radio = ttk.Radiobutton(mode_frame, text="Folder Mode", variable=self.mode_var,
                         value="folder", command=self._toggle_mode)
        self._folder_radio.pack(side="left", padx=4)
        self._file_radio = ttk.Radiobutton(mode_frame, text="File Mode", variable=self.mode_var,
                         value="file", command=self._toggle_mode)
        self._file_radio.pack(side="left", padx=4)
        self._ass_radio = ttk.Radiobutton(mode_frame, text="ASS Merge Mode", variable=self.mode_var,
                         value="ass_merge", command=self._toggle_mode)
        self._ass_radio.pack(side="left", padx=4)
        ttk.Button(mode_frame, text="\u2699 Settings", command=self._open_settings).pack(side="right", padx=4)

        # -- Container that swaps between folder / file UI --
        self.input_container = ttk.Frame(self)
        self.input_container.pack(fill="both", **pad)

        # -- Template row with saved templates (hidden in ASS Merge Mode) --
        self.tpl_frame = ttk.LabelFrame(self, text="Template", padding=6)
        tpl_outer = self.tpl_frame

        tpl_top_row = ttk.Frame(tpl_outer)
        tpl_top_row.pack(fill="x")
        ttk.Label(tpl_top_row, text="Template .ass:").pack(side="left")
        self.tpl_var = tk.StringVar(value=cfg_get("last_tpl_path"))
        tpl_entry = ttk.Entry(tpl_top_row, textvariable=self.tpl_var, width=50)
        tpl_entry.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(tpl_top_row, text="Browse", command=self._browse_tpl).pack(side="left")
        if HAS_DND:
            tpl_entry.drop_target_register(DND_FILES)
            tpl_entry.dnd_bind("<<Drop>>", self._on_drop_tpl)

        tpl_saved_row = ttk.Frame(tpl_outer)
        tpl_saved_row.pack(fill="x", pady=(4, 0))
        ttk.Label(tpl_saved_row, text="Saved:").pack(side="left")
        self.tpl_combo = ttk.Combobox(tpl_saved_row, state="readonly", width=30)
        self.tpl_combo.pack(side="left", padx=4)
        self.tpl_combo.bind("<<ComboboxSelected>>", self._on_template_selected)
        ttk.Button(tpl_saved_row, text="Save", command=self._save_template).pack(side="left", padx=2)
        ttk.Button(tpl_saved_row, text="Delete", command=self._delete_template).pack(side="left", padx=2)
        self._refresh_template_combo()

        # -- Auto-Match button --
        self._auto_match_btn = ttk.Button(self, text="Auto-Match (Ctrl+M)", command=self._auto_match)
        self._auto_match_btn.pack(anchor="e", padx=12, pady=(4, 2))

        # -- Results table --
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, **pad)

        cols = ("#", "top_srt", "bot_srt", "conf")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("#", text="#", anchor="center")
        self.tree.heading("top_srt", text=f"Top ({cfg_get('top_lang_name')})", anchor="w")
        self.tree.heading("bot_srt", text=f"Bot ({cfg_get('bot_lang_name')})", anchor="w")
        self.tree.heading("conf", text="Conf.", anchor="center")
        self.tree.column("#", width=40, minwidth=30, stretch=False, anchor="center")
        self.tree.column("top_srt", width=300, minwidth=120)
        self.tree.column("bot_srt", width=300, minwidth=120)
        self.tree.column("conf", width=70, minwidth=50, stretch=False, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # -- Bottom buttons --
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text="Edit Pair", command=self._edit_pair).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Remove Pair", command=self._remove_pair).pack(side="left", padx=4)
        self._convert_btn = ttk.Button(btn_row, text="Convert All (Ctrl+Enter)", command=self._convert_all)
        self._convert_btn.pack(side="right", padx=4)
        self._open_folder_btn = ttk.Button(btn_row, text="Open Output Folder", command=self._open_output_folder, state="disabled")
        self._open_folder_btn.pack(side="right", padx=4)
        self.cleanup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(btn_row, text="Clean up intermediate files",
                         variable=self.cleanup_var).pack(side="right", padx=8)

        # -- Status bar with progress --
        status_frame = ttk.Frame(self)
        status_frame.pack(fill="x", side="bottom", **pad)

        self.progress = ttk.Progressbar(status_frame, mode="determinate", length=200)
        self.progress.pack(side="right", padx=(8, 0))
        self.progress.pack_forget()

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, relief="sunken", anchor="w", padding=4)
        self.status_label.pack(fill="x", side="left", expand=True)

        self._build_folder_ui()
        self._build_file_ui()
        self._build_ass_merge_ui()
        self._toggle_mode()

    def _update_dynamic_labels(self):
        top_name = cfg_get("top_lang_name")
        bot_name = cfg_get("bot_lang_name")
        self.tree.heading("top_srt", text=f"Top ({top_name})")
        self.tree.heading("bot_srt", text=f"Bot ({bot_name})")
        self._folder_radio.configure(text="Folder Mode")
        self._file_radio.configure(text="File Mode")
        self._ass_radio.configure(text="ASS Merge Mode")
        if hasattr(self, "folder_frame"):
            for widget in self.folder_frame.winfo_children():
                if isinstance(widget, ttk.Label):
                    text = widget.cget("text")
                    if "Top Folder" in text:
                        widget.configure(text=f"Top Folder ({top_name}):")
                    elif "Bot Folder" in text:
                        widget.configure(text=f"Bot Folder ({bot_name}):")

    # -- Folder mode UI --

    def _build_folder_ui(self):
        self.folder_frame = ttk.LabelFrame(self.input_container, text="Folders", padding=8)
        top_name = cfg_get("top_lang_name")
        bot_name = cfg_get("bot_lang_name")

        ttk.Label(self.folder_frame, text=f"Top Folder ({top_name}):").grid(row=0, column=0, sticky="w")
        self.top_dir_var = tk.StringVar(value=cfg_get("last_top_dir"))
        top_entry = ttk.Entry(self.folder_frame, textvariable=self.top_dir_var, width=55)
        top_entry.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(self.folder_frame, text="Browse", command=self._browse_top_dir).grid(row=0, column=2)

        ttk.Label(self.folder_frame, text=f"Bot Folder ({bot_name}):").grid(row=1, column=0, sticky="w")
        self.bot_dir_var = tk.StringVar(value=cfg_get("last_bot_dir"))
        bot_entry = ttk.Entry(self.folder_frame, textvariable=self.bot_dir_var, width=55)
        bot_entry.grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(self.folder_frame, text="Browse", command=self._browse_bot_dir).grid(row=1, column=2)

        self.folder_frame.columnconfigure(1, weight=1)

        if HAS_DND:
            for entry, var in [(top_entry, self.top_dir_var), (bot_entry, self.bot_dir_var)]:
                entry.drop_target_register(DND_FILES)
                entry.dnd_bind("<<Drop>>", self._make_folder_drop(var))

    # -- File mode UI --

    def _build_file_ui(self):
        self.file_frame = ttk.Frame(self.input_container)
        top_name = cfg_get("top_lang_name")
        bot_name = cfg_get("bot_lang_name")

        for col, (label_text, attr, add_cmd, clear_attr) in enumerate([
            (f"Top SRT Files ({top_name})", "top_listbox", "_browse_top_files", "top"),
            (f"Bot SRT Files ({bot_name})", "bot_listbox", "_browse_bot_files", "bot"),
        ]):
            col_frame = ttk.LabelFrame(self.file_frame, text=label_text, padding=4)
            col_frame.grid(row=0, column=col, sticky="nsew", padx=4)

            lb = tk.Listbox(col_frame, width=38, height=6, selectmode="extended")
            lb.pack(side="left", fill="both", expand=True)
            sb = ttk.Scrollbar(col_frame, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            sb.pack(side="left", fill="y")
            setattr(self, attr, lb)

            btn_fr = ttk.Frame(col_frame)
            btn_fr.pack(side="left", fill="y", padx=(4, 0))
            ttk.Button(btn_fr, text="+", width=3, command=getattr(self, add_cmd)).pack(pady=2)
            ttk.Button(btn_fr, text="-", width=3,
                       command=lambda a=attr: self._remove_selected_files(a)).pack(pady=2)

            if HAS_DND:
                lb.drop_target_register(DND_FILES)
                lb.dnd_bind("<<Drop>>", self._make_file_drop(attr))

        self.file_frame.columnconfigure(0, weight=1)
        self.file_frame.columnconfigure(1, weight=1)
        self.file_frame.rowconfigure(0, weight=1)

    # -- ASS merge mode UI --

    def _build_ass_merge_ui(self):
        self.ass_merge_frame = ttk.Frame(self.input_container)
        top_name = cfg_get("top_lang_name")
        bot_name = cfg_get("bot_lang_name")

        for col, (label_text, attr, add_cmd) in enumerate([
            (f"{top_name} ASS Files", "ass_top_listbox", "_browse_ass_top_files"),
            (f"{bot_name} ASS Files", "ass_bot_listbox", "_browse_ass_bot_files"),
        ]):
            col_frame = ttk.LabelFrame(self.ass_merge_frame, text=label_text, padding=4)
            col_frame.grid(row=0, column=col, sticky="nsew", padx=4)

            lb = tk.Listbox(col_frame, width=38, height=6, selectmode="extended")
            lb.pack(side="left", fill="both", expand=True)
            sb = ttk.Scrollbar(col_frame, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            sb.pack(side="left", fill="y")
            setattr(self, attr, lb)

            btn_fr = ttk.Frame(col_frame)
            btn_fr.pack(side="left", fill="y", padx=(4, 0))
            ttk.Button(btn_fr, text="+", width=3, command=getattr(self, add_cmd)).pack(pady=2)
            ttk.Button(btn_fr, text="-", width=3,
                       command=lambda a=attr: self._remove_selected_files(a)).pack(pady=2)

            if HAS_DND:
                lb.drop_target_register(DND_FILES)
                lb.dnd_bind("<<Drop>>", self._make_ass_file_drop(attr))

        sign_frame = ttk.LabelFrame(self.ass_merge_frame, text="Sign / Title Handling", padding=4)
        sign_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(6, 0))
        self.sign_mode_var = tk.StringVar(value="shift")
        ttk.Radiobutton(
            sign_frame, text="Shift below top language (keep position, offset to avoid overlap)",
            variable=self.sign_mode_var, value="shift",
        ).pack(anchor="w")
        ttk.Radiobutton(
            sign_frame, text="Strip positioning (remove \\pos, let renderer auto-place)",
            variable=self.sign_mode_var, value="strip",
        ).pack(anchor="w")

        font_frame = ttk.LabelFrame(self.ass_merge_frame, text="Font Matching", padding=4)
        font_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(6, 0))
        self.match_font_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            font_frame,
            text="Match bottom font to top (copies font, bold, outline style from top language — keeps color and size separate)",
            variable=self.match_font_var,
        ).pack(anchor="w")

        self.ass_merge_frame.columnconfigure(0, weight=1)
        self.ass_merge_frame.columnconfigure(1, weight=1)
        self.ass_merge_frame.rowconfigure(0, weight=1)

    def _toggle_mode(self):
        for child in self.input_container.winfo_children():
            child.pack_forget()
        mode = self.mode_var.get()
        if mode == "folder":
            self.folder_frame.pack(fill="x", expand=False)
            self.tpl_frame.pack(fill="x", padx=8, pady=4,
                                before=self._auto_match_btn)
        elif mode == "file":
            self.file_frame.pack(fill="both", expand=True)
            self.tpl_frame.pack(fill="x", padx=8, pady=4,
                                before=self._auto_match_btn)
        elif mode == "ass_merge":
            self.ass_merge_frame.pack(fill="both", expand=True)
            self.tpl_frame.pack_forget()

    # ---- Settings ----

    def _open_settings(self):
        dlg = SettingsDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._update_dynamic_labels()
            self.status_var.set("Settings saved.")

    def _show_shortcuts(self):
        messagebox.showinfo("Keyboard Shortcuts",
            "Ctrl+O  —  Browse MKV\n"
            "Ctrl+M  —  Auto-Match\n"
            "Ctrl+Enter  —  Convert All\n"
            "Delete  —  Remove selected pair\n"
            "Ctrl+,  —  Open Settings",
            parent=self,
        )

    def _show_about(self):
        messagebox.showinfo("About Subtitle Merger",
            "Subtitle Merger v1.2.0\n\n"
            "Batch dual-subtitle merger with\n"
            "MKV extraction, style management,\n"
            "and Plex-compatible output.\n\n"
            "github.com/CoolFreeze23/subtitle-merger",
            parent=self,
        )

    # ---- Drag-and-drop helpers ----

    @staticmethod
    def _make_folder_drop(var: tk.StringVar):
        def handler(event):
            paths = _parse_dnd_paths(event.data)
            if paths:
                p = paths[0]
                var.set(str(p.parent if p.is_file() else p))
        return handler

    def _on_drop_tpl(self, event):
        paths = _parse_dnd_paths(event.data)
        for p in paths:
            if p.is_file():
                self.tpl_var.set(str(p))
                return

    # ---- MKV import ----

    def _browse_mkv(self):
        initial = cfg_get("last_mkv_dir") or ""
        files = filedialog.askopenfilenames(
            title="Select MKV file(s)",
            initialdir=initial or None,
            filetypes=[("MKV files", "*.mkv"), ("All video", "*.mkv;*.mp4;*.avi;*.ts"), ("All files", "*.*")],
        )
        if files:
            cfg_set("last_mkv_dir", str(Path(files[0]).parent))
            cfg_save()
            self._process_mkvs([Path(f) for f in files])

    def _reset_track_memory(self):
        self._remembered_top = None
        self._remembered_bot = None
        self.status_var.set("Track memory cleared — next MKV will prompt for selection.")

    def _on_drop_mkv(self, event):
        try:
            paths = _parse_dnd_paths(event.data)
            mkvs = [p for p in paths if p.is_file() and p.suffix.lower() in (".mkv", ".mp4", ".avi", ".ts")]
            if mkvs:
                self._process_mkvs(mkvs)
            else:
                self.status_var.set("No video files found in drop")
        except Exception as e:
            messagebox.showerror("Drop error", f"Error processing drop:\n{e}")

    def _process_mkvs(self, mkv_paths: list[Path]):
        try:
            find_ffmpeg()
        except FileNotFoundError as e:
            messagebox.showerror("FFmpeg not found", str(e))
            return

        any_ass = False
        extracted = 0
        for mkv in mkv_paths:
            self.status_var.set(f"Scanning: {mkv.name}...")
            self.update_idletasks()
            try:
                tracks = probe_subtitles(mkv)
            except Exception as e:
                messagebox.showerror("Probe failed", f"{mkv.name}:\n{e}")
                continue

            if not tracks:
                messagebox.showwarning("No subtitles", f"No subtitle tracks found in:\n{mkv.name}")
                continue

            eng_tracks, por_tracks = auto_pick_tracks(
                tracks, skip_forced=self.skip_forced_var.get(),
            )

            top_lang = cfg_get("top_lang_name")
            bot_lang = cfg_get("bot_lang_name")
            eng_pick = self._resolve_track(mkv.name, f"{top_lang} (Top)", eng_tracks, tracks, is_top=True)
            if eng_pick is None:
                continue
            por_pick = self._resolve_track(mkv.name, f"{bot_lang} (Bot)", por_tracks, tracks, is_top=False)
            if por_pick is None:
                continue

            eng_skipped = eng_pick is self._SKIP_TRACK
            por_skipped = por_pick is self._SKIP_TRACK
            if eng_skipped and por_skipped:
                self.status_var.set(f"Both languages skipped for {mkv.name}")
                continue

            stem = mkv.stem
            top_code = cfg_get("top_lang_code")
            bot_code = cfg_get("bot_lang_code")

            eng_out: Path | None = None
            por_out: Path | None = None
            eng_ext = ""
            por_ext = ""

            try:
                if not eng_skipped:
                    eng_codec = eng_pick.get("codec", "srt")
                    eng_ext = ".ass" if eng_codec in ("ass", "ssa") else ".srt"
                    eng_out = mkv.parent / f"{stem}.{top_code}{eng_ext}"
                    self.status_var.set(f"Extracting {top_lang} from {mkv.name}...")
                    self.update_idletasks()
                    eng_out = extract_subtitle(mkv, eng_pick["index"], eng_out, eng_codec)
                    self._intermediate_files.append(eng_out)

                if not por_skipped:
                    por_codec = por_pick.get("codec", "srt")
                    por_ext = ".ass" if por_codec in ("ass", "ssa") else ".srt"
                    por_out = mkv.parent / f"{stem}.{bot_code}{por_ext}"
                    self.status_var.set(f"Extracting {bot_lang} from {mkv.name}...")
                    self.update_idletasks()
                    por_out = extract_subtitle(mkv, por_pick["index"], por_out, por_codec)
                    self._intermediate_files.append(por_out)
            except Exception as e:
                messagebox.showerror("Extraction failed", f"{mkv.name}:\n{e}")
                continue

            both_extracted = eng_out is not None and por_out is not None
            both_ass = both_extracted and eng_ext == ".ass" and por_ext == ".ass"
            if both_ass:
                any_ass = True
                self.status_var.set(f"Preparing ASS files for {mkv.name}...")
                self.update_idletasks()
                try:
                    eng_prepared = prepare_ass_for_merge(eng_out, is_portuguese=False)
                    por_prepared = prepare_ass_for_merge(por_out, is_portuguese=True)
                    self._intermediate_files.append(eng_prepared)
                    self._intermediate_files.append(por_prepared)
                    eng_out = eng_prepared
                    por_out = por_prepared
                except Exception as e:
                    messagebox.showerror("Preparation failed", f"{mkv.name}:\n{e}")
                    continue
            elif eng_out and eng_ext == ".ass" and por_skipped:
                any_ass = True
                self.status_var.set(f"Preparing {top_lang} ASS for {mkv.name}...")
                self.update_idletasks()
                try:
                    eng_prepared = prepare_ass_for_merge(eng_out, is_portuguese=False)
                    self._intermediate_files.append(eng_prepared)
                    eng_out = eng_prepared
                except Exception as e:
                    messagebox.showerror("Preparation failed", f"{mkv.name}:\n{e}")
                    continue
            elif por_out and por_ext == ".ass" and eng_skipped:
                any_ass = True
                self.status_var.set(f"Preparing {bot_lang} ASS for {mkv.name}...")
                self.update_idletasks()
                try:
                    por_prepared = prepare_ass_for_merge(por_out, is_portuguese=True)
                    self._intermediate_files.append(por_prepared)
                    por_out = por_prepared
                except Exception as e:
                    messagebox.showerror("Preparation failed", f"{mkv.name}:\n{e}")
                    continue

            if eng_out:
                eng_name = eng_out.name
                if eng_name not in self.top_file_paths:
                    self.top_file_paths[eng_name] = eng_out
                if any_ass:
                    self.ass_top_listbox.insert("end", eng_name)
                else:
                    self.top_listbox.insert("end", eng_name)

            if por_out:
                por_name = por_out.name
                if por_name not in self.bot_file_paths:
                    self.bot_file_paths[por_name] = por_out
                if any_ass:
                    self.ass_bot_listbox.insert("end", por_name)
                else:
                    self.bot_listbox.insert("end", por_name)

            extracted += 1

        if any_ass:
            self.mode_var.set("ass_merge")
        else:
            self.mode_var.set("file")
        self._toggle_mode()

        self._update_file_count()
        if extracted:
            skipped_any = any(
                p is self._SKIP_TRACK for p in (eng_pick, por_pick)
            ) if extracted == 1 else False
            hint = " Add external files for skipped languages, then Auto-Match." if skipped_any else " Click Auto-Match to pair."
            self.status_var.set(f"Extracted subtitles from {extracted} file(s).{hint}")

    def _resolve_track(self, mkv_name: str, label: str,
                       candidates: list[dict], all_tracks: list[dict],
                       is_top: bool = True) -> dict | None:
        remembered = self._remembered_top if is_top else self._remembered_bot

        if remembered and candidates:
            by_index = next((t for t in candidates if t["index"] == remembered["index"]), None)
            if by_index:
                self.status_var.set(
                    f"Auto-selected #{by_index['index']} "
                    f"({by_index['language']} - {by_index.get('title','')}) for {mkv_name}")
                self.update_idletasks()
                return by_index
            by_title = next(
                (t for t in candidates
                 if t.get("title", "").strip().lower() == remembered.get("title", "").strip().lower()
                 and t["language"] == remembered["language"]),
                None,
            )
            if by_title:
                self.status_var.set(
                    f"Auto-selected #{by_title['index']} "
                    f"({by_title['language']} - {by_title.get('title','')}) for {mkv_name}")
                self.update_idletasks()
                return by_title

        if len(candidates) == 1:
            pick = candidates[0]
            if is_top:
                self._remembered_top = pick
            else:
                self._remembered_bot = pick
            return pick

        if len(candidates) == 0:
            pick = self._pick_track_dialog(
                mkv_name, label,
                f"No {label.split('(')[0].strip()} tracks auto-detected.\n"
                "Choose manually, or skip to use an external file:",
                all_tracks, allow_skip=True,
            )
        else:
            pick = self._pick_track_dialog(
                mkv_name, label,
                f"Multiple {label.split('(')[0].strip()} tracks found.\n"
                "Choose one, or skip to use an external file:",
                candidates, allow_skip=True,
            )

        if pick is self._SKIP_TRACK:
            return pick

        if pick is not None:
            if is_top:
                self._remembered_top = pick
            else:
                self._remembered_bot = pick
        return pick

    _SKIP_TRACK = {"__skip__": True}

    def _pick_track_dialog(self, mkv_name: str, label: str,
                           message: str, tracks: list[dict],
                           allow_skip: bool = False) -> dict | None:
        dlg = tk.Toplevel(self)
        dlg.title(f"Select {label} - {mkv_name}")
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text=message, padding=8, wraplength=500).pack(anchor="w")

        cols = ("idx", "lang", "codec", "title")
        tree = ttk.Treeview(dlg, columns=cols, show="headings", height=min(len(tracks), 10),
                            selectmode="browse")
        tree.heading("idx", text="#")
        tree.heading("lang", text="Language")
        tree.heading("codec", text="Codec")
        tree.heading("title", text="Title")
        tree.column("idx", width=40, stretch=False)
        tree.column("lang", width=100)
        tree.column("codec", width=80)
        tree.column("title", width=280)
        tree.pack(padx=8, pady=4, fill="both")

        for t in tracks:
            title_disp = t["title"]
            if t.get("forced"):
                title_disp = "[FORCED] " + title_disp
            tree.insert("", "end", iid=str(t["index"]),
                        values=(t["index"], t["language"], t["codec"], title_disp))
        if tracks:
            tree.selection_set(str(tracks[0]["index"]))

        result: list[dict | None] = [None]

        def on_ok():
            sel = tree.selection()
            if sel:
                idx = int(sel[0])
                result[0] = next((t for t in tracks if t["index"] == idx), None)
            dlg.destroy()

        def on_skip():
            result[0] = self._SKIP_TRACK
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=8, pady=8)
        ttk.Button(bf, text="OK", command=on_ok).pack(side="right", padx=4)
        ttk.Button(bf, text="Cancel", command=on_cancel).pack(side="right", padx=4)
        if allow_skip:
            ttk.Button(bf, text="Skip — use external file",
                       command=on_skip).pack(side="left", padx=4)

        dlg.wait_window()
        return result[0]

    # ---- Saved templates ----

    def _refresh_template_combo(self):
        names = sorted(self.saved_templates.keys())
        self.tpl_combo["values"] = names
        if names and not self.tpl_combo.get():
            self.tpl_combo.current(0)
            self._on_template_selected()

    def _on_template_selected(self, event=None):
        name = self.tpl_combo.get()
        path = self.saved_templates.get(name, "")
        if path:
            self.tpl_var.set(path)

    def _save_template(self):
        current_path = self.tpl_var.get().strip()
        if not current_path:
            messagebox.showwarning("No template", "Set a template .ass path first.")
            return
        name = simpledialog.askstring("Save Template", "Template name:", parent=self)
        if not name:
            return
        self.saved_templates[name] = current_path
        save_templates(self.saved_templates)
        self._refresh_template_combo()
        self.tpl_combo.set(name)
        self.status_var.set(f"Template '{name}' saved.")

    def _delete_template(self):
        name = self.tpl_combo.get()
        if not name or name not in self.saved_templates:
            messagebox.showinfo("Nothing selected", "Select a saved template to delete.")
            return
        self.saved_templates.pop(name)
        save_templates(self.saved_templates)
        self.tpl_combo.set("")
        self._refresh_template_combo()
        self.status_var.set(f"Template '{name}' deleted.")

    def _make_file_drop(self, listbox_attr: str):
        def handler(event):
            paths = _parse_dnd_paths(event.data)
            lb: tk.Listbox = getattr(self, listbox_attr)
            store = self.top_file_paths if "top" in listbox_attr else self.bot_file_paths
            for p in paths:
                if p.is_file() and p.suffix.lower() in (".srt", ".ass"):
                    name = p.name
                    if name not in store:
                        store[name] = p
                        lb.insert("end", name)
            self._update_file_count()
        return handler

    def _make_ass_file_drop(self, listbox_attr: str):
        def handler(event):
            paths = _parse_dnd_paths(event.data)
            lb: tk.Listbox = getattr(self, listbox_attr)
            store = self.top_file_paths if "top" in listbox_attr else self.bot_file_paths
            for p in paths:
                if p.is_file() and p.suffix.lower() in (".ass", ".ssa"):
                    name = p.name
                    if name not in store:
                        store[name] = p
                        lb.insert("end", name)
            self._update_file_count()
        return handler

    def _remove_selected_files(self, listbox_attr: str):
        lb: tk.Listbox = getattr(self, listbox_attr)
        store = self.top_file_paths if "top" in listbox_attr else self.bot_file_paths
        for idx in reversed(lb.curselection()):
            name = lb.get(idx)
            store.pop(name, None)
            lb.delete(idx)
        self._update_file_count()

    def _update_file_count(self):
        t = len(self.top_file_paths)
        b = len(self.bot_file_paths)
        self.status_var.set(f"{t} Top file(s), {b} Bot file(s)")

    # ---- Browse callbacks ----

    def _browse_top_dir(self):
        initial = cfg_get("last_top_dir") or ""
        d = filedialog.askdirectory(title=f"Select Top ({cfg_get('top_lang_name')}) SRT folder",
                                    initialdir=initial or None)
        if d:
            self.top_dir_var.set(d)
            cfg_set("last_top_dir", d)
            cfg_save()

    def _browse_bot_dir(self):
        initial = cfg_get("last_bot_dir") or ""
        d = filedialog.askdirectory(title=f"Select Bot ({cfg_get('bot_lang_name')}) SRT folder",
                                    initialdir=initial or None)
        if d:
            self.bot_dir_var.set(d)
            cfg_set("last_bot_dir", d)
            cfg_save()

    def _browse_tpl(self):
        initial = cfg_get("last_tpl_path")
        initial_dir = str(Path(initial).parent) if initial else None
        f = filedialog.askopenfilename(
            title="Select template .ass file",
            initialdir=initial_dir,
            filetypes=[("ASS files", "*.ass"), ("All files", "*.*")],
        )
        if f:
            self.tpl_var.set(f)
            cfg_set("last_tpl_path", f)
            cfg_save()

    def _browse_top_files(self):
        files = filedialog.askopenfilenames(
            title=f"Select Top ({cfg_get('top_lang_name')}) SRT files",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")],
        )
        for f in files:
            p = Path(f)
            if p.name not in self.top_file_paths:
                self.top_file_paths[p.name] = p
                self.top_listbox.insert("end", p.name)
        self._update_file_count()

    def _browse_bot_files(self):
        files = filedialog.askopenfilenames(
            title=f"Select Bot ({cfg_get('bot_lang_name')}) SRT files",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")],
        )
        for f in files:
            p = Path(f)
            if p.name not in self.bot_file_paths:
                self.bot_file_paths[p.name] = p
                self.bot_listbox.insert("end", p.name)
        self._update_file_count()

    def _browse_ass_top_files(self):
        files = filedialog.askopenfilenames(
            title=f"Select {cfg_get('top_lang_name')} ASS files",
            filetypes=[("ASS files", "*.ass;*.ssa"), ("All files", "*.*")],
        )
        for f in files:
            p = Path(f)
            if p.name not in self.top_file_paths:
                self.top_file_paths[p.name] = p
                self.ass_top_listbox.insert("end", p.name)
        self._update_file_count()

    def _browse_ass_bot_files(self):
        files = filedialog.askopenfilenames(
            title=f"Select {cfg_get('bot_lang_name')} ASS files",
            filetypes=[("ASS files", "*.ass;*.ssa"), ("All files", "*.*")],
        )
        for f in files:
            p = Path(f)
            if p.name not in self.bot_file_paths:
                self.bot_file_paths[p.name] = p
                self.ass_bot_listbox.insert("end", p.name)
        self._update_file_count()

    # ---- Auto-match ----

    def _load_template(self) -> bool:
        tpl_path = self.tpl_var.get().strip()
        if not tpl_path:
            messagebox.showwarning("Missing template", "Please set the template .ass file.")
            return False
        self.template_path = Path(tpl_path)
        if not self.template_path.exists():
            messagebox.showerror("Not found", f"Template not found:\n{self.template_path}")
            return False
        try:
            self.script_info, self.styles = parse_ass_template(self.template_path)
        except Exception as e:
            messagebox.showerror("Template error", f"Failed to parse template:\n{e}")
            return False
        if not self.styles:
            messagebox.showerror("Template error", "No [V4+ Styles] section found in template.")
            return False
        cfg_set("last_tpl_path", tpl_path)
        cfg_save()
        return True

    def _auto_match(self):
        mode = self.mode_var.get()
        if mode != "ass_merge":
            if not self._load_template():
                return

        if mode == "folder":
            self._auto_match_folder()
        elif mode in ("file", "ass_merge"):
            self._auto_match_files()

    def _auto_match_folder(self):
        top_path = self.top_dir_var.get().strip()
        bot_path = self.bot_dir_var.get().strip()
        if not top_path or not bot_path:
            messagebox.showwarning("Missing paths", "Please set both folder paths.")
            return

        top_dir = Path(top_path)
        bot_dir = Path(bot_path)
        for label, p in [("Top folder", top_dir), ("Bot folder", bot_dir)]:
            if not p.exists():
                messagebox.showerror("Not found", f"{label} does not exist:\n{p}")
                return

        top_srts = sorted(f.name for f in top_dir.glob("*.srt"))
        bot_srts = sorted(f.name for f in bot_dir.glob("*.srt"))
        if not top_srts:
            messagebox.showwarning("No files", f"No .srt files in Top folder:\n{top_dir}")
            return
        if not bot_srts:
            messagebox.showwarning("No files", f"No .srt files in Bot folder:\n{bot_dir}")
            return

        self.top_file_paths = {f: top_dir / f for f in top_srts}
        self.bot_file_paths = {f: bot_dir / f for f in bot_srts}

        self.pairs, self.unmatched_top, self.unmatched_bot = match_files(top_srts, bot_srts)
        self._refresh_table()
        self.status_var.set(f"Matched {len(self.pairs)} pair(s), "
                            f"{len(self.unmatched_top) + len(self.unmatched_bot)} unmatched")

    def _auto_match_files(self):
        top_names = sorted(self.top_file_paths.keys())
        bot_names = sorted(self.bot_file_paths.keys())
        if not top_names:
            messagebox.showwarning("No files", "Add Top files first.")
            return
        if not bot_names:
            messagebox.showwarning("No files", "Add Bot files first.")
            return

        self.pairs, self.unmatched_top, self.unmatched_bot = match_files(top_names, bot_names)
        self._refresh_table()
        self.status_var.set(f"Matched {len(self.pairs)} pair(s), "
                            f"{len(self.unmatched_top) + len(self.unmatched_bot)} unmatched")

    # ---- Table refresh ----

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for i, (tf, bf, score) in enumerate(self.pairs, 1):
            tag = "low" if score < 0.8 else ""
            conf_text = f"{score:.0%}" + (" *" if score < 0.8 else "")
            self.tree.insert("", "end", iid=str(i), values=(i, tf, bf, conf_text), tags=(tag,))
        self.tree.tag_configure("low", foreground="#cc6600")

        if self.unmatched_top or self.unmatched_bot:
            self.tree.insert("", "end", iid="sep", values=("", "--- Unmatched ---", "", ""))
            for j, f in enumerate(self.unmatched_top):
                self.tree.insert("", "end", iid=f"ut_{j}", values=("", f, "(no match - Top)", ""))
            for j, f in enumerate(self.unmatched_bot):
                self.tree.insert("", "end", iid=f"ub_{j}", values=("", "(no match - Bot)", f, ""))

    # ---- Edit pair ----

    def _edit_pair(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a paired row first.")
            return
        iid = sel[0]
        try:
            idx = int(iid) - 1
        except ValueError:
            messagebox.showinfo("Invalid", "Select a paired row, not an unmatched entry.")
            return
        if idx < 0 or idx >= len(self.pairs):
            return

        tf, old_bf, _ = self.pairs[idx]
        available = sorted(set(self.unmatched_bot + [old_bf]))
        if not available:
            messagebox.showinfo("No files", "No Bot files available to choose from.")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Edit Pair")
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text=f"Top:  {tf}", padding=8).pack(anchor="w")
        ttk.Label(dlg, text="Choose Bot file:", padding=(8, 0)).pack(anchor="w")

        listbox = tk.Listbox(dlg, width=60, height=min(len(available), 15))
        listbox.pack(padx=8, pady=4, fill="both", expand=True)
        for bf in available:
            listbox.insert("end", bf)
        try:
            listbox.selection_set(available.index(old_bf))
            listbox.see(available.index(old_bf))
        except ValueError:
            pass

        def on_ok():
            cs = listbox.curselection()
            if not cs:
                return
            new_bf = available[cs[0]]
            if old_bf != new_bf:
                if old_bf not in self.unmatched_bot:
                    self.unmatched_bot.append(old_bf)
                if new_bf in self.unmatched_bot:
                    self.unmatched_bot.remove(new_bf)
            self.pairs[idx] = (tf, new_bf, 1.0)
            self._refresh_table()
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill="x", padx=8, pady=8)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side="right", padx=4)

    # ---- Remove pair ----

    def _remove_pair(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            idx = int(iid) - 1
        except ValueError:
            return
        if idx < 0 or idx >= len(self.pairs):
            return

        removed = self.pairs.pop(idx)
        self.unmatched_top.append(removed[0])
        self.unmatched_bot.append(removed[1])
        self._refresh_table()
        self.status_var.set(f"Removed pair. {len(self.pairs)} pair(s) remaining.")

    # ---- Open output folder ----

    def _open_output_folder(self):
        if self._last_output_dir and self._last_output_dir.is_dir():
            if sys.platform == "win32":
                os.startfile(str(self._last_output_dir))
            else:
                subprocess.Popen(["xdg-open", str(self._last_output_dir)])

    # ---- Convert (threaded) ----

    def _convert_all(self):
        if self._converting:
            return
        if not self.pairs:
            messagebox.showwarning("Nothing to convert", "No pairs to convert. Run Auto-Match first.")
            return

        self._converting = True
        self._convert_btn.configure(state="disabled")
        self.progress.pack(side="right", padx=(8, 0))
        self.progress["maximum"] = len(self.pairs)
        self.progress["value"] = 0

        thread = threading.Thread(target=self._convert_worker, daemon=True)
        thread.start()

    def _convert_worker(self):
        converted = 0
        errors = []
        out_dir: Path | None = None
        dupe_warnings: list[str] = []

        for i, (tf, bf, _) in enumerate(self.pairs):
            self.after(0, self._update_progress, i, tf)

            top_path = self.top_file_paths.get(tf)
            bot_path = self.bot_file_paths.get(bf)
            if not top_path or not bot_path:
                errors.append(f"{tf}: path lookup failed")
                continue

            out_name_str = output_name(tf)
            out_path = top_path.parent / out_name_str
            out_dir = top_path.parent

            is_ass_merge = (top_path.suffix.lower() in (".ass", ".ssa")
                            and bot_path.suffix.lower() in (".ass", ".ssa"))

            try:
                if is_ass_merge:
                    eng_info, eng_styles, eng_events = parse_ass_sections(top_path)
                    por_info, por_styles, por_events = parse_ass_sections(bot_path)
                    if not eng_events:
                        errors.append(f"{tf}: no events parsed (Top)")
                        continue
                    if not por_events:
                        errors.append(f"{bf}: no events parsed (Bot)")
                        continue

                    dupes = _check_duplicate_styles(eng_styles, por_styles)
                    if dupes:
                        dupe_warnings.append(f"{tf}: duplicate styles: {', '.join(dupes[:5])}")

                    merge_info = eng_info if eng_info else self.script_info
                    s_mode = getattr(self, "sign_mode_var", None)
                    m_font = getattr(self, "match_font_var", None)
                    ass_content = build_ass_merged(
                        merge_info, eng_styles, por_styles,
                        eng_events, por_events,
                        sign_mode=s_mode.get() if s_mode else "shift",
                        match_font_to_top=m_font.get() if m_font else False,
                    )
                else:
                    top_cues = parse_srt(top_path)
                    bot_cues = parse_srt(bot_path)
                    if not top_cues:
                        errors.append(f"{tf}: no cues parsed (Top)")
                        continue
                    if not bot_cues:
                        errors.append(f"{bf}: no cues parsed (Bot)")
                        continue
                    ass_content = build_ass(
                        self.script_info, self.styles, top_cues, bot_cues
                    )

                out_path.write_text(ass_content, encoding="utf-8-sig")
                converted += 1
            except Exception as e:
                errors.append(f"{tf}: {e}")

        cleaned = 0
        if self.cleanup_var.get() and converted > 0:
            for f in self._intermediate_files:
                try:
                    if f.is_file():
                        f.unlink()
                        cleaned += 1
                except OSError:
                    pass
            self._intermediate_files.clear()

        self.after(0, self._convert_done, converted, errors, out_dir, cleaned, dupe_warnings)

    def _update_progress(self, index: int, filename: str):
        self.progress["value"] = index
        self.status_var.set(f"Converting {index + 1}/{len(self.pairs)}: {filename}")

    def _convert_done(self, converted: int, errors: list[str],
                      out_dir: Path | None, cleaned: int, dupe_warnings: list[str]):
        self._converting = False
        self._convert_btn.configure(state="normal")
        self.progress["value"] = self.progress["maximum"]

        self._last_output_dir = out_dir
        if out_dir:
            self._open_folder_btn.configure(state="normal")

        msg = f"Converted {converted}/{len(self.pairs)} pair(s)."
        if cleaned:
            msg += f"\nCleaned up {cleaned} intermediate file(s)."
        if dupe_warnings:
            msg += "\n\nDuplicate style warnings:\n" + "\n".join(dupe_warnings)
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors)

        where = out_dir or "output folder"
        self.status_var.set(f"Done! {converted} file(s) written to {where}")
        messagebox.showinfo("Conversion complete", msg)

        self.after(2000, lambda: self.progress.pack_forget())


def main():
    init_config()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
