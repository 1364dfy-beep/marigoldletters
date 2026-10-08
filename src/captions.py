"""Subtitle/overlay files (ASS): word captions for narrated mode, animated text slides for slideshow mode."""
import re


# ---------------------------------------------------------------- narrated mode helpers
def _proportional(text: str, duration: float):
    words = text.split()
    total = sum(len(w) + 1 for w in words)
    t, out = 0.0, []
    for w in words:
        d = duration * (len(w) + 1) / total
        out.append((w, t, t + d))
        t += d
    return out


def word_timings(wav_path: str, narration: str, duration: float, whisper_model: str):
    """Try faster-whisper for exact word times; fall back to proportional timing."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(wav_path, word_timestamps=True, language="en")
        words = [(w.word.strip(), w.start, w.end) for s in segments for w in (s.words or [])]
        if len(words) >= 20:
            return words
        print("[captions] whisper returned too few words, using proportional timing")
    except Exception as e:  # noqa: BLE001
        print(f"[captions] whisper unavailable ({str(e)[:120]}), using proportional timing")
    return _proportional(narration, duration)


# ---------------------------------------------------------------- shared ASS helpers
def _ts(sec: float) -> str:
    sec = max(sec, 0.0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text: str) -> str:
    return re.sub(r"[{}\\]", "", text)


def _bgr(hex_rgb: str) -> str:
    """'F4B6C2' (RGB) -> ASS colour '&H00C2B6F4' (BGR)."""
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _header(width: int, height: int, cfg: dict, wrap_style: int, slide: dict | None = None) -> str:
    sl = slide or {"font": cfg["font"], "size": cfg.get("slide_font_size", 78), "outline": 6, "accent": "E8B44F"}
    accent = _bgr(sl["accent"])
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: {wrap_style}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{cfg['font']},{cfg['font_size']},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,7,3,5,90,90,0,1
Style: Slide,{sl['font']},{sl['size']},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,{sl['outline']},3,5,120,120,0,1
Style: Cta,{sl['font']},44,{accent},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,4,0,1,3,2,5,120,120,0,1
Style: Brand,{sl['font']},34,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,9,0,1,2,1,8,60,60,150,1
Style: HudL,DejaVu Sans Mono,44,&H00D8D8D8,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,3,1,7,60,60,150,1
Style: HudR,DejaVu Sans Mono,40,&H00B8B8B8,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,3,1,9,60,60,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _hud_lines(hud: dict, total: float) -> list[str]:
    """rec: blinking red REC dot + timestamp + part label (horror). brand: small channel name (quotes)."""
    if hud.get("style") == "brand":
        return [f"Dialogue: 1,{_ts(0)},{_ts(total)},Brand,,0,0,0,,{{\\alpha&H50&}}{_clean(hud['text'])}"]
    lines = []
    for s in range(int(total) + 1):
        dot_alpha = "&H00&" if s % 2 == 0 else "&HFF&"
        lines.append(
            f"Dialogue: 1,{_ts(s)},{_ts(min(s + 1, total))},HudL,,0,0,0,,"
            f"{{\\1c&H2020E0&\\alpha{dot_alpha}}}\u25cf{{\\1c&HD8D8D8&\\alpha&H00&}} REC  {hud['time']}"
        )
    lines.append(f"Dialogue: 1,{_ts(0)},{_ts(total)},HudR,,0,0,0,,{hud['right']}")
    return lines


def _write(path: str, header: str, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")


# ---------------------------------------------------------------- narrated: word-by-word captions
def write_ass(words, path: str, width: int, height: int, cfg: dict, hud: dict | None = None,
              total: float = 0.0) -> None:
    per = cfg["words_per_line"]
    chunks = [words[i:i + per] for i in range(0, len(words), per)]
    lines = []
    for i, chunk in enumerate(chunks):
        start = chunk[0][1]
        end = chunks[i + 1][0][1] if i + 1 < len(chunks) else chunk[-1][2] + 0.3
        end = max(end, start + 0.15)
        text = _clean(" ".join(w[0] for w in chunk).upper())
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")
    if hud and total > 0:
        lines += _hud_lines(hud, total)
    _write(path, _header(width, height, cfg, 2), lines)


# ---------------------------------------------------------------- slideshow: animated text slides
def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?\u2026])\s+", text.strip())
    return [p for p in parts if p]


def _block_height(sents: list[str], size: int, width: int) -> int:
    """Rough height (px) of the wrapped text block, used to size the soft scrim behind it."""
    chars_per_line = max(8, int((width - 240) / (size * 0.62) * 0.9))
    lines = sum(max(1, -(-len(s) // chars_per_line)) for s in sents) + max(0, len(sents) - 1)  # blank line between sentences
    return int(lines * size * 1.22)


def _scrim(t0: float, t1: float, center_y: int, block_h: int, width: int, pad: int = 170) -> str:
    """A soft, blurred, semi-transparent dark band behind the text so it stays readable on bright photos."""
    h = block_h + 2 * pad
    top = int(center_y - h / 2)
    shape = f"m 0 0 l {width} 0 {width} {h} 0 {h}"
    return (f"Dialogue: 0,{_ts(t0)},{_ts(t1)},Slide,,0,0,0,,"
            f"{{\\an7\\pos(0,{top})\\p1\\1c&H000000&\\1a&HB0&\\bord0\\shad0\\blur70\\fad(350,350)}}{shape}")


def write_slides_ass(slides: list[dict], durs: list[float], reveals: list[list[float]], path: str,
                     width: int, height: int, cfg: dict, hud: dict | None, total: float,
                     cta: str | None = None, slide: dict | None = None) -> None:
    """One event per slide. Layout is fixed from the first frame; each sentence fades in at its own
    time (via \\t alpha transforms), so nothing jumps around, and everything fades out at the end.
    A soft dark scrim (layer 0) sits behind the text (layer 1) for readability."""
    lines, t0 = [], 0.0
    accent = _bgr((slide or {}).get("accent", "E8B44F"))
    size = int((slide or {}).get("size", 78))
    cy = int(height * 0.47)
    for i, (sl, dur, offs) in enumerate(zip(slides, durs, reveals)):
        sents = split_sentences(sl["text"])
        parts = []
        for j, (sent, off) in enumerate(zip(sents, offs)):
            a, b = int(off * 1000), int(off * 1000) + 380
            end_ms = int(dur * 1000)
            color = f"\\1c{accent}&" if (i == 0 and j == 0) else "\\1c&HFFFFFF&"  # slide-1 hook in the accent colour
            parts.append(
                f"{{{color}\\alpha&HFF&\\t({a},{b},\\alpha&H00&)\\t({max(end_ms - 350, b)},{end_ms - 30},\\alpha&HFF&)}}"
                f"{_clean(sent)}"
            )
        text = "\\N\\N".join(parts)
        lines.append(_scrim(t0, t0 + dur, cy, _block_height(sents, size, width), width))
        lines.append(
            f"Dialogue: 1,{_ts(t0)},{_ts(t0 + dur)},Slide,,0,0,0,,{{\\an5\\pos({width // 2},{cy})}}{text}"
        )
        if cta and i == len(slides) - 1:
            s = t0 + dur * 0.45
            cta_y = int(height * 0.72)
            lines.append(_scrim(s, t0 + dur, cta_y, 90, width, pad=110))
            lines.append(
                f"Dialogue: 1,{_ts(s)},{_ts(t0 + dur)},Cta,,0,0,0,,"
                f"{{\\an5\\pos({width // 2},{cta_y})\\fad(350,350)}}{_clean(cta)}"
            )
        t0 += dur
    if hud and total > 0:
        lines += _hud_lines(hud, total)
    _write(path, _header(width, height, cfg, 0, slide), lines)
