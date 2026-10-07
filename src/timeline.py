"""Map narration scenes onto the audio timeline using word timings."""


def scene_durations(scenes: list[dict], words: list[tuple], total: float) -> list[float]:
    """words: [(word, start, end), ...] from captions.word_timings. Returns one duration per scene,
    summing exactly to `total` (audio length + tail)."""
    counts = [max(1, len(sc["text"].split())) for sc in scenes]
    all_words, n = sum(counts), len(words)
    starts, cum = [], 0
    for i, c in enumerate(counts):
        idx = min(int(round(cum / all_words * n)), n - 1)
        starts.append(0.0 if i == 0 else float(words[idx][1]))
        cum += c
    ends = starts[1:] + [total]
    durs = [max(e - s, 1.5) for s, e in zip(starts, ends)]
    k = total / sum(durs)
    return [d * k for d in durs]


# ---------------------------------------------------------------- slideshow mode
def slide_durations(slides: list[dict], target: float, wps: float, min_s: float) -> list[float]:
    """Reading time per slide (words / reading speed + a beat), scaled so the video is exactly `target` s."""
    raw = [max(min_s, len(sl["text"].split()) / wps + 1.2) for sl in slides]
    k = target / sum(raw)
    return [d * k for d in raw]


def reveal_offsets(sentences: list[str], dur: float) -> list[float]:
    """When each sentence of a slide fades in (seconds from slide start). Everything is on screen
    by ~55% of the slide, leaving the rest as reading time."""
    counts = [max(1, len(s.split())) for s in sentences]
    tot, cum, offs = sum(counts), 0, []
    for c in counts:
        offs.append(0.3 + (cum / tot) * dur * 0.5)
        cum += c
    return offs
