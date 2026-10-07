"""Royalty-free generative music: pad + bass + sparse echoing plucks (+ soft heartbeat in dark mood) + reverb.
mood="dark" (minor key, horror) or mood="warm" (major key, hopeful/romantic).

Every episode gets its own key, tempo and chord progression (seeded), so tracks never repeat.
Pure numpy -> free, no samples, no licensing issues.
"""
import random
import wave

import numpy as np

SR = 44100

WARM_PROGRESSIONS = [  # bright, hopeful, romantic (major keys)
    [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")],   # I  V  vi IV
    [(9, "min"), (5, "maj"), (0, "maj"), (7, "maj")],   # vi IV I  V
    [(0, "maj"), (4, "min"), (5, "maj"), (7, "maj")],   # I  iii IV V
    [(5, "maj"), (0, "maj"), (7, "maj"), (9, "min")],   # IV I  V  vi
]
WARM_TONICS = [48, 50, 52, 53, 55, 57]  # C3 .. A3

# (semitones above the tonic, chord quality) - dark minor-key progressions
PROGRESSIONS = [
    [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")],   # i  VI  III VII
    [(0, "min"), (5, "min"), (8, "maj"), (7, "maj")],    # i  iv  VI  V
    [(0, "min"), (3, "maj"), (8, "maj"), (5, "min")],    # i  III VI  iv
    [(0, "min"), (10, "maj"), (8, "maj"), (10, "maj")],  # i  VII VI  VII
]
TRIADS = {"min": (0, 3, 7), "maj": (0, 4, 7)}
TONICS = [45, 46, 47, 48, 50, 52, 53, 55]  # A2 .. G3


def _hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    e = np.ones(n, dtype=np.float32)
    a, r = min(a, n // 2), min(r, n // 2)
    e[:a] = np.linspace(0, 1, a, dtype=np.float32) ** 1.5
    e[n - r:] = np.linspace(1, 0, r, dtype=np.float32) ** 1.5
    return e


def _tone(freq: float, n: int, harmonics=(1.0, 0.45, 0.2, 0.1, 0.05), detune=(0.997, 1.0, 1.003)) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros(n, dtype=np.float32)
    for d in detune:
        for k, amp in enumerate(harmonics, start=1):
            out += amp * np.sin(2 * np.pi * freq * d * k * t)
    return out / (len(detune) * sum(harmonics))


def _add(buf: np.ndarray, sig: np.ndarray, start: int) -> None:
    end = min(len(buf), start + len(sig))
    if start < end:
        buf[start:end] += sig[: end - start]


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1.0 / (1.0 + (freqs / cutoff) ** 4)
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def _reverb(x: np.ndarray, rng: np.random.Generator, seconds: float = 2.4, wet: float = 0.28) -> np.ndarray:
    n_ir = int(seconds * SR)
    t = np.arange(n_ir, dtype=np.float32) / SR
    ir = rng.standard_normal(n_ir).astype(np.float32) * np.exp(-t / (seconds / 3.2))
    ir = _lowpass(ir, 3500.0)
    size = 1 << int(np.ceil(np.log2(len(x) + n_ir)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)].astype(np.float32)
    y /= max(1e-6, float(np.max(np.abs(y))))
    return (1 - wet) * x + wet * y * float(np.max(np.abs(x)))


def generate(path: str, seconds: float, seed: int, mood: str = "dark") -> dict:
    warm = mood == "warm"
    rnd = random.Random(seed)
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    bpm = rnd.choice([66, 72, 76, 80] if warm else [60, 64, 68, 72])
    beat = 60.0 / bpm
    bar = 4 * beat
    tonic = rnd.choice(WARM_TONICS if warm else TONICS)
    prog = rnd.choice(WARM_PROGRESSIONS if warm else PROGRESSIONS)
    n_bars = int(seconds / bar) + 2

    pad = np.zeros(n, dtype=np.float32)
    bass = np.zeros(n, dtype=np.float32)
    plucks = np.zeros((2, n), dtype=np.float32)
    thud = np.zeros(n, dtype=np.float32)

    # heartbeat-style thud shape (pitch drops 95 -> 45 Hz)
    tk = np.arange(int(0.35 * SR), dtype=np.float32) / SR
    thud_shape = np.sin(2 * np.pi * (45 * tk + 50 * (1 - np.exp(-tk * 18)) / 18)) * np.exp(-tk * 11)

    for b in range(n_bars):
        off, quality = prog[b % len(prog)]
        start = int(b * bar * SR)
        chord = [tonic + 12 + off + i for i in TRIADS[quality]]
        pad_notes = chord + ([tonic + 12 + off + 14] if warm else [])
        length = int((bar + 1.6) * SR)  # overlap into next bar for a smooth pad
        env = _env(length, 1.4, 1.6)
        for m in pad_notes:
            _add(pad, _tone(_hz(m), length) * env * (0.27 if warm else 0.33), start)
        root = tonic + off
        _add(bass, _tone(_hz(root), length, harmonics=(1.0, 0.5, 0.15), detune=(1.0,)) * _env(length, 0.12, 0.9) * (0.38 if warm else 0.5), start)

        # sparse plucked arpeggio, echoing through the reverb
        step = beat / 2
        for s in range(8):
            if rnd.random() < (0.30 if warm else 0.38):
                continue
            m = rnd.choice(chord) + rnd.choice([24, 24, 36] if warm else [12, 12, 24])
            ln = int(1.6 * SR)
            tt = np.arange(ln, dtype=np.float32) / SR
            sig = (np.sin(2 * np.pi * _hz(m) * tt) + 0.3 * np.sin(2 * np.pi * _hz(m) * 2 * tt)) * np.exp(-tt / (0.55 if warm else 0.28))
            _add(plucks[s % 2], sig.astype(np.float32) * (0.13 if warm else 0.16), start + int((s * step) * SR))

        # soft thud on beats 1 and 3
        for k in ((0, 2) if not warm else ()):
            _add(thud, thud_shape * 0.45, start + int(k * beat * SR))

    # tape-style echo on the plucks (3 taps)
    for ch in range(2):
        dry = plucks[ch].copy()
        for i, g in enumerate((0.45, 0.25, 0.12), start=1):
            d = int(i * beat * 0.75 * SR)
            plucks[ch][d:] += dry[: n - d] * g

    cutoff = 3600 if warm else 2200
    left = _lowpass(pad + bass, cutoff) + plucks[0] + thud
    right = _lowpass(pad + bass, cutoff) + plucks[1] + thud
    # slow stereo movement on the pad
    lfo = (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * np.arange(n, dtype=np.float32) / SR)) * 0.08
    left, right = left * (1 - lfo), right * (1 + lfo)

    left, right = _reverb(left, rng), _reverb(right, rng)
    stereo = np.stack([left, right])
    stereo /= max(1e-6, float(np.max(np.abs(stereo))))
    stereo *= 0.85

    fin, fout = int(2.0 * SR), int(3.0 * SR)
    stereo[:, :fin] *= np.linspace(0, 1, fin, dtype=np.float32)
    stereo[:, n - fout:] *= np.linspace(1, 0, fout, dtype=np.float32)

    pcm = (stereo.T * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return {"mood": mood, "bpm": bpm, "tonic_midi": tonic, "progression": [f"{o}{q}" for o, q in prog]}
