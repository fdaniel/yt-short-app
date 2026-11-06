"""Find the parts of a trailer that survive the 9:16 crop: no on-screen words sliced at its edges.

A 16:9 trailer cropped to a vertical frame keeps only its centre, so a title or caption across the
centre comes out as "EDUCE" or "PCHAF". The owner saw this in the first videos and asked for it to stop.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from shorts.media.crop import letterbox
from shorts.media.shots import Shot

log = logging.getLogger(__name__)

CELL_S = 0.4  # one frame read per this many seconds: at 0.8 s short flashes of text slipped through
MIN_CLIP_S = 1.6
MAX_CLIP_S = 4.0
SCAN_WIDTH = 960  # frames are read at this width: big enough for trailer captions, four times faster
MIN_LETTERS = 3
SENTENCE_LETTERS = 15  # small print ("Requires in-game purchases") reads badly even when it fits
MIN_CONFIDENCE = 0.5
DARK, BRIGHT = 35, 225  # mean brightness of a black frame between scenes, and of a white flash


@dataclass(frozen=True)
class TextBox:
    left: float
    right: float
    text: str
    confidence: float


@dataclass(frozen=True)
class Moment:
    start: float
    problem: str | None  # what makes this moment unusable, None when it is clean
    motion: float


TextReader = Callable[[np.ndarray], Sequence[TextBox]]


def _letters(text: str) -> int:
    return sum(c.isalpha() for c in text)


def frame_problem(boxes: Sequence[TextBox], *, brightness: float, width: float, height: float,
                  picture_height: float | None = None) -> str | None:
    """Why this frame can't be shown cropped to 9:16: sliced words, small print, black or a white flash.
    `picture_height`: the picture between letterbox bars, whose crop is narrower."""
    if brightness < DARK:
        return "dark"
    if brightness > BRIGHT:
        return "white flash"
    # the render may crop either window: the whole height, or the picture between letterbox bars
    windows = [h * 9 / 16 for h in dict.fromkeys((height, picture_height or height))]
    for b in boxes:
        letters = _letters(b.text)
        if b.confidence <= MIN_CONFIDENCE or letters < MIN_LETTERS:
            continue
        for window in windows:
            x0, x1 = (width - window) / 2, (width + window) / 2
            seen = b.right > x0 and b.left < x1
            if seen and (b.left < x0 or b.right > x1 or letters >= SENTENCE_LETTERS):
                return b.text
    return None


def spread_problems(moments: Sequence[Moment]) -> list[Moment]:
    """A moment next to a problem is one too: text fades in and out between two samples."""
    out = []
    for i, m in enumerate(moments):
        nearby = [n.problem for n in moments[max(0, i - 1): i + 2] if n.problem]
        out.append(m if m.problem or not nearby else replace(m, problem=nearby[0]))
    return out


def _runs(moments: Sequence[Moment]) -> list[list[Moment]]:
    runs, run = [], []
    for m in moments:
        if m.problem:
            if run:
                runs.append(run)
            run = []
        else:
            run.append(m)
    return runs + ([run] if run else [])


def clean_clips(moments: Sequence[Moment], source: Path, asset_id: int | None) -> list[Shot]:
    """Clips of MIN_CLIP_S to MAX_CLIP_S cut from each run of clean moments, scored by their motion."""
    clips = []
    for run in _runs(moments):
        begin, stop = run[0].start, run[-1].start + CELL_S
        while stop - begin >= MIN_CLIP_S - 1e-6:
            end = min(begin + MAX_CLIP_S, stop)
            inside = [m.motion for m in run if begin <= m.start < end - 1e-6]
            clips.append(Shot(source, asset_id, begin, end, float(np.mean(inside)) if inside else 0.0))
            begin = end
    return clips


def _read_moment(frame: np.ndarray, previous: np.ndarray | None, read_text: TextReader,
                 at: float) -> tuple[Moment, np.ndarray]:
    scale = min(1.0, SCAN_WIDTH / frame.shape[1])
    small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    thumb = cv2.resize(grey, (240, 135))
    motion = 0.0 if previous is None else float(np.abs(thumb - previous).mean())
    _, picture = letterbox(grey.mean(axis=1))
    problem = frame_problem(read_text(small), brightness=float(thumb.mean()), width=small.shape[1],
                            height=small.shape[0], picture_height=picture)
    return Moment(at, problem, motion), thumb


def _frame_at(capture: cv2.VideoCapture, seconds: float) -> np.ndarray | None:
    """The first frame at or after `seconds`, reading forward; None at the end of the video."""
    while True:
        if not capture.grab():
            return None
        if capture.get(cv2.CAP_PROP_POS_MSEC) >= seconds * 1000 - 1:
            ok, frame = capture.retrieve()
            return frame if ok else None


def scan_trailer(path: Path, asset_id: int | None, read_text: TextReader, *, start: float,
                 end: float) -> list[Shot]:
    """The clean clips between `start` and `end` seconds of the trailer."""
    capture = cv2.VideoCapture(str(path))
    moments, previous = [], None
    try:
        # one seek, then frames in order: a seek per sample decoded from the last keyframe every time
        capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        at = start
        while at + CELL_S <= end + 1e-6:
            frame = _frame_at(capture, at + CELL_S / 2)
            if frame is None:
                break
            moment, previous = _read_moment(frame, previous, read_text, at)
            moments.append(moment)
            at += CELL_S
    finally:
        capture.release()
    clips = clean_clips(spread_problems(moments), path, asset_id)
    log.info("%s: %d of %d moments clean, %d clips", path.name, sum(not m.problem for m in moments),
             len(moments), len(clips))
    return clips


@cache
def rapidocr_reader() -> TextReader:
    """The free RapidOCR text reader (Apache-2.0), loaded once per process."""
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()

    def read(frame: np.ndarray) -> list[TextBox]:
        found, _ = engine(frame)
        return [TextBox(min(p[0] for p in points), max(p[0] for p in points), str(text), float(score))
                for points, text, score in (found or [])]

    return read
