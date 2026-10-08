"""Video assembly with plain ffmpeg (free, no extra libs)."""
import random
import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print("FFMPEG FAILED:", " ".join(cmd))
        print(e.stderr[-2000:])
        raise


def duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


ENC = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"]


def _image_segment(img: str, dur: float, out: Path, v: dict, idx: int, workdir: Path,
                   dim: float = 0.0, look: str = "horror", fades: bool = True) -> None:
    w, h, fps = v["width"], v["height"], v["fps"]
    d = f"{dur:.3f}"
    if look == "romantic":
        _romantic_segment(img, dur, out, v, idx, workdir, dim)
        return
    # --- horror look: slow pan + desaturated grade, grain, flicker, vignette
    big = int(h * 1.09)
    pre = workdir / f"pre_{idx}.png"  # scale once (cheap) instead of every frame
    _run(["ffmpeg", "-y", "-i", img, "-vf", f"scale=-2:{big}:flags=lanczos", str(pre)])
    xexpr = f"(iw-{w})*t/{d}" if idx % 2 == 0 else f"(iw-{w})*(1-t/{d})"
    vf = (
        f"crop={w}:{h}:x='{xexpr}':y='(ih-{h})/2',"
        "eq=contrast=1.08:saturation=0.85:brightness='-0.02+0.015*sin(37*t)*sin(2.3*t)':eval=frame,"
        "noise=alls=14:allf=t,vignette=PI/4,"
        + (f"lutyuv=y='val*{1 - dim:.2f}'," if dim > 0 else "")  # darken so slide text stays readable
        + f"fade=t=in:st=0:d=0.2,fade=t=out:st={max(dur - 0.2, 0):.3f}:d=0.2,format=yuv420p"
    )
    _run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(pre),
          "-t", d, "-vf", vf, *ENC, str(out)])


def _mean_luma(path: str) -> float:
    """Average brightness (0-255) of an image, from a tiny 48x84 grayscale decode. 100 if anything fails."""
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=48:84,format=gray", "-frames:v", "1",
             "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
        return sum(raw) / len(raw) if raw else 100.0
    except Exception:  # noqa: BLE001
        return 100.0


def adaptive_tone(luma: float, max_dim: float) -> tuple[float, float]:
    """(dim, lift) for a photo of average brightness `luma`.
    Bright photos get up to `max_dim` darkening so text stays readable; dark photos are lifted a little
    instead of being darkened further, so the video feels warm instead of gloomy."""
    dim = max(0.0, min(1.0, (luma - 70.0) / 70.0)) * max_dim
    lift = 1.0 if luma >= 75 else min(1.35, 75.0 / max(luma, 40.0))
    return round(dim, 3), round(lift, 3)


def _romantic_segment(img: str, dur: float, out: Path, v: dict, idx: int, workdir: Path, dim: float) -> None:
    """Photo -> slow Ken Burns zoom (in on even slides, out on odd), warm grade, soft glow, light grain.
    `dim` is the MAXIMUM darkening; the real amount depends on how bright the photo is."""
    dim, lift = adaptive_tone(_mean_luma(img), dim)
    w, h, fps = v["width"], v["height"], v["fps"]
    d = f"{dur:.3f}"
    zmax = 0.15
    W2, H2 = int(w * (1 + zmax)), int(h * (1 + zmax))
    pre = workdir / f"pre_{idx}.png"  # cover-crop once to the largest zoom size
    _run(["ffmpeg", "-y", "-i", img, "-vf",
          f"scale={W2}:{H2}:force_original_aspect_ratio=increase:flags=lanczos,crop={W2}:{H2}", str(pre)])
    z = f"{zmax}*t/{d}" if idx % 2 == 0 else f"{zmax}*(1-t/{d})"
    vf = (
        f"scale=w='trunc({w}*(1+{z})/2)*2':h='trunc({h}*(1+{z})/2)*2':eval=frame:flags=bicubic,"
        f"crop={w}:{h}:x='(iw-{w})/2':y='(ih-{h})/2',"
        "eq=contrast=1.06:saturation=1.08,colorbalance=rs=0.05:bs=-0.05:rm=0.03:bm=-0.03,"
        f"split[a][b];[b]scale={w // 4}:{h // 4},gblur=sigma=6,scale={w}:{h}[c];"  # cheap soft glow
        "[a][c]blend=all_mode=screen:all_opacity=0.22,"
        "noise=alls=6:allf=t,vignette=PI/5,"
        + (f"lutyuv=y='val*{1 - dim:.2f}'," if dim > 0 else "")
        + (f"lutyuv=y='min(255,val*{lift:.2f})'," if lift > 1.0 else "")
        + "format=yuv420p"
    )
    _run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(pre),
          "-t", d, "-vf", vf, *ENC, str(out)])


def _dark_segment(dur: float, out: Path, v: dict, look: str = "horror", idx: int = 0) -> None:
    """Fallback when no image exists. horror: dark grain. romantic: soft dusk-rose gradient."""
    w, h, fps = v["width"], v["height"], v["fps"]
    if look == "romantic":
        pal = [("0x3a2447", "0xd98880"), ("0x1f3a4d", "0xe8b4a0"), ("0x4a2c3e", "0xf0c9a8")][idx % 3]
        vf = f"noise=alls=6:allf=t,vignette=PI/5,scale={w}:{h}:flags=bicubic,format=yuv420p"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
              f"gradients=s={w // 2}x{h // 2}:c0={pal[0]}:c1={pal[1]}:x0=0:y0=0:x1={w // 2}:y1={h // 2}:duration={dur:.3f}:rate={fps}",
              "-vf", vf, *ENC, str(out)])
        return
    vf = f"noise=alls=22:allf=t,vignette=PI/3,scale={w}:{h}:flags=bicubic,format=yuv420p"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x08080d:s={w // 2}x{h // 2}:r={fps}:d={dur:.3f}",
          "-vf", vf, *ENC, str(out)])


def _crossfade_join(parts: list[Path], durs: list[float], T: float, out: Path) -> None:
    """Chain xfade between segments. Segment 0 lasts d0; later segments last d_k + T (their first T
    seconds overlap the previous slide), so slide k still *starts* at S_k = sum(d_0..d_k-1)."""
    cmd = ["ffmpeg", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    chain, prev, start = [], "0:v", durs[0]
    for k in range(1, len(parts)):
        label = f"v{k}"
        chain.append(f"[{prev}][{k}:v]xfade=transition=fade:duration={T}:offset={start - T:.3f}[{label}]")
        prev, start = label, start + durs[k]
    _run(cmd + ["-filter_complex", ";".join(chain), "-map", f"[{prev}]", *ENC, str(out)])


def build_background(images: list[str | None], durs: list[float], workdir: Path, v: dict,
                     dim: float = 0.0, look: str = "horror", transition: str = "dip") -> Path:
    cross = transition == "crossfade" and len(images) > 1
    T = float(v.get("crossfade_seconds", 0.4))
    parts = []
    for i, (img, dur) in enumerate(zip(images, durs)):
        p = workdir / f"seg_{i}.mp4"
        seg_len = dur + (T if (cross and i > 0) else 0.0)
        if img:
            _image_segment(img, seg_len, p, v, i, workdir, dim, look)
        else:
            _dark_segment(seg_len, p, v, look, i)
        parts.append(p)
    bg = workdir / "bg.mp4"
    if cross:
        _crossfade_join(parts, durs, T, bg)
    else:
        lst = workdir / "list.txt"
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(bg)])
    return bg


def make_ambient(out: Path, seconds: float) -> str:
    """Copyright-free dark drone: two low sines + brown noise, slow tremolo, low-passed."""
    d = f"{seconds:.2f}"
    fc = (
        "[0:a]volume=0.5[a];[1:a]tremolo=f=0.15:d=0.6,volume=0.35[b];[2:a]lowpass=f=260,volume=0.9[c];"
        f"[a][b][c]amix=inputs=3:normalize=0,lowpass=f=520,afade=t=in:d=3,afade=t=out:st={max(seconds - 3, 0):.2f}:d=3[o]"
    )
    _run(["ffmpeg", "-y",
          "-f", "lavfi", "-i", f"sine=frequency=55:duration={d}:sample_rate=44100",
          "-f", "lavfi", "-i", f"sine=frequency=82.4:duration={d}:sample_rate=44100",
          "-f", "lavfi", "-i", f"anoisesrc=color=brown:duration={d}:sample_rate=44100:amplitude=0.3",
          "-filter_complex", fc, "-map", "[o]", str(out)])
    return str(out)


def pick_music(music_dir: Path) -> str | None:
    tracks = [p for ext in ("*.mp3", "*.wav", "*.m4a", "*.ogg") for p in music_dir.glob(ext)]
    return str(random.choice(tracks)) if tracks else None


def _music_mode() -> str:
    """slideshow.music_mode in config/settings.yaml: both (default) | none | generated."""
    try:
        from .util import load_settings
        return str(load_settings().get("slideshow", {}).get("music_mode", "both"))
    except Exception:  # noqa: BLE001
        return "both"


def _render_video(bg: Path, ass_name: str, workdir: Path, out: Path, total: float) -> None:
    """Captions burned in, with a SILENT audio track (so every player treats the file normally)."""
    _run(["ffmpeg", "-y", "-i", str(bg.resolve()), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
          "-filter_complex", f"[0:v]ass={ass_name}[v]", "-map", "[v]", "-map", "1:a", "-t", f"{total:.3f}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", str(out.resolve())], cwd=workdir)


def _add_music(video: Path, music: str, volume: float, total: float, out: Path) -> None:
    """Replace the silent track with music. The video stream is copied (fast, no re-encode)."""
    _run(["ffmpeg", "-y", "-i", str(video.resolve()), "-stream_loop", "-1", "-i", str(Path(music).resolve()),
          "-filter_complex", f"[1:a]volume={volume}[a]", "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out.resolve())])


def final_mix(bg: Path, narration: str | None, ass_name: str, workdir: Path, out: Path,
              music: str | None, music_volume: float, total: float) -> None:
    """Slideshow (no narration), by `slideshow.music_mode`:
         both       out = SILENT video (for adding a trending sound inside TikTok) + <name>_music.mp4 backup
         none       out = silent video only
         generated  out = video with our generated music
       Narrated mode (narration given) always mixes voice + music into `out`.
       ass_name must be a file inside workdir (avoids ffmpeg path-escaping headaches)."""
    if narration is None:
        mode = _music_mode()
        if mode == "generated":
            if not music:
                raise ValueError("music_mode 'generated' needs a music track")
            _render_video(bg, ass_name, workdir, workdir / "silent.mp4", total)
            _add_music(workdir / "silent.mp4", music, music_volume, total, out)
        else:
            _render_video(bg, ass_name, workdir, out, total)
            if mode == "both" and music:
                _add_music(out, music, music_volume, total, out.with_name(out.stem + "_music.mp4"))
        return
    cmd = ["ffmpeg", "-y", "-i", str(bg.resolve()), "-i", str(Path(narration).resolve())]
    mus = None
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        mus = 2
    fc = "[0:v]ass=" + ass_name + "[v];"
    fc += (f"[{mus}:a]volume={music_volume}[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
           if mus else "[1:a]anull[a]")
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out.resolve())]
    _run(cmd, cwd=workdir)
