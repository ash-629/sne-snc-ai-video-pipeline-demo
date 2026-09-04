#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a short "soft intro" clip to prepend before the main long-form video.

Replaces the old 1-frame cover. The intro shows the cover image (封面.png) held
for `hold` seconds, then crossfades over `fade` seconds into the MAIN video's
first frame, so the cut into the main body is seamless. The intro is silent.

  [封面 held hold s] → [fade s crossfade → main's first frame] → (caller concats main)

Total intro duration = hold + fade (default 1.0s). The first output frame is the
cover, so YouTube's thumbnail picker still gets a clean frame at t=0.

Because this prepends `hold + fade` seconds before the body, any caption SRT
(which is body-time / 0-based) is that much early on the final video — upload
caption tracks with `captions.py --offset <hold+fade>`.

Used by both wrap scripts (channel-agnostic):
  - skills/subtitle-burn/scripts/wrap_episode.py        (SNC mono + podcast)
  - skills/sne-video-pipeline/scripts/wrap_cover_outro.py (SNE mono + podcast)

Usage (as a module):
  from soft_intro import build
  intro_path, dur = build(cover_png, main_mp4, out_mp4, hold=0.5, fade=0.5)
"""
import subprocess
from pathlib import Path


def build(cover, main, out, hold: float = 0.5, fade: float = 0.5,
          crf: int = 18, preset: str = "fast"):
    """Render the soft-intro clip. Returns (Path(out), duration_seconds).

    cover : cover image (封面.png)
    main  : the composited main video — its first frame is the crossfade target
    out   : output mp4 path for the intro clip
    """
    cover = Path(cover)
    main = Path(main)
    out = Path(out)
    if not cover.exists():
        raise SystemExit(f"soft_intro: cover not found: {cover}")
    if not main.exists():
        raise SystemExit(f"soft_intro: main video not found: {main}")

    total = round(hold + fade, 3)

    # 1) extract the main body's first frame (crossfade target)
    first = out.with_name(out.stem + "_firstframe.png")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(main),
        "-vf", r"select=eq(n\,0)", "-frames:v", "1",
        str(first),
    ], check=True)

    # 2) cover (held total s) xfade→ first frame (fade s, starting at offset=hold).
    #    Normalize BOTH branches (scale/setsar/fps/format) — the main's first frame
    #    may carry a non-1 SAR (e.g. SNE composite overlay), which makes xfade fail.
    fc = (
        "[0:v]scale=1920:1080,setsar=1,fps=30,format=yuv420p[cov];"
        "[1:v]scale=1920:1080,setsar=1,fps=30,format=yuv420p[ff];"
        f"[cov][ff]xfade=transition=fade:duration={fade}:offset={hold},format=yuv420p[v]"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{total}", "-i", str(cover),
        "-loop", "1", "-t", f"{fade}", "-i", str(first),
        "-f", "lavfi", "-t", f"{total}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-shortest", str(out),
    ], check=True)

    try:
        first.unlink()
    except OSError:
        pass
    return out, total
