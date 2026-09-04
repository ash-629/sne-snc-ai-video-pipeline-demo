#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wrap the composited main video with a soft cover intro at the start and an outro at the end.

DEFAULT = soft intro (2026-06-16, see memory feedback_soft_intro_default): the 封面.png is
held still for --cover-hold (0.5s) then crossfades into the body over --fade (0.5s) — a 1.0s
soft open, NOT the old ~10s animated intro and NOT a 1-frame flash. The held cover still gives
the YouTube thumbnail picker a clean frame. `--no-soft-intro` falls back to the legacy 1-frame
cover (~33ms). NOTE: the final video gains 1.0s at the front, so caption tracks uploaded for it
need captions.py --offset 1.0 (burned karaoke is inside the body and stays in sync).

All three inputs are normalized to 30fps / 1920x1080 / yuv420p / aac 48kHz stereo
before concat to avoid the demuxer's silent codec-mismatch failure mode (HEVC+H264
mixed → only first segment output).

Usage:
  python wrap_cover_outro.py \
    --episode-dir "g:/.../episodes/0519 whats up" \
    --outro "g:/.../上传素材/片尾_A.mp4" \
    --title "What's Up"
"""
import argparse
import random
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent.parent / '_shared'))
from soft_intro import build as build_soft_intro


def resolve_outro(outro_arg: str) -> Path:
    """Resolve the --outro argument to a concrete file.

    If it points to a directory, randomly pick one of the `片尾_*.mp4` files
    inside (fallback: any `*.mp4`). If it points to a file, use it as-is.
    This makes every wrap pick a different outro instead of a fixed one.
    """
    p = Path(outro_arg)
    if p.is_dir():
        cands = sorted(p.glob('片尾_*.mp4')) or sorted(p.glob('*.mp4'))
        if not cands:
            raise SystemExit(f'no outro mp4 found in directory: {p}')
        chosen = random.choice(cands)
        print(f'outro: randomly picked {chosen.name} (from {len(cands)} candidates)', flush=True)
        return chosen
    if not p.exists():
        raise SystemExit(f'outro not found: {p}')
    return p

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def safe_filename(title: str) -> str:
    """Strip filesystem-illegal chars but keep apostrophes/spaces (titles look natural)."""
    return re.sub(r'[<>:"/\\|?*]', '', title).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode-dir', required=True)
    ap.add_argument('--main', help='Composited main video (default: <ep>/final_with_bg_karaoke.mp4)')
    ap.add_argument('--cover', help='Cover PNG (default: <ep>/封面.png)')
    ap.add_argument('--outro', required=True,
                    help='Outro mp4 file, OR a directory — if a directory, randomly picks one '
                         'of the 片尾_*.mp4 inside (e.g. 上传素材/)')
    ap.add_argument('--title', required=True,
                    help='Output filename stem (e.g. "What\'s Up" → "What\'s Up.mp4")')
    ap.add_argument('--output', help='Override output path (default: <ep>/<title>.mp4)')
    ap.add_argument('--cover-frames', type=float, default=0.034,
                    help='Cover duration in seconds (default 0.034 = 1 frame @ 30fps; only with --no-soft-intro)')
    ap.add_argument('--soft-intro', action=argparse.BooleanOptionalAction, default=True,
                    help='Soft intro: hold 封面 cover-hold s + fade s crossfade into the body (default on); '
                         '--no-soft-intro falls back to the 1-frame cover')
    ap.add_argument('--cover-hold', type=float, default=0.5, help='soft-intro cover hold seconds')
    ap.add_argument('--fade', type=float, default=0.5, help='soft-intro crossfade seconds')
    ap.add_argument('--crf', type=int, default=20)
    ap.add_argument('--preset', default='fast')
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    main_v = Path(args.main) if args.main else ep / 'final_with_bg_karaoke.mp4'
    cover = Path(args.cover) if args.cover else ep / '封面.png'
    outro = resolve_outro(args.outro)

    if args.output:
        output = Path(args.output)
    else:
        output = ep / f'{safe_filename(args.title)}.mp4'

    # All three segments forced to 30fps 1920x1080 yuv420p aac 48k stereo before concat.
    norm = (
        '[0:v]fps=30,scale=1920:1080,format=yuv420p,setsar=1[v0];'
        '[1:v]fps=30,scale=1920:1080,format=yuv420p,setsar=1[v1];'
        '[2:v]fps=30,scale=1920:1080,format=yuv420p,setsar=1[v2];'
    )

    if args.soft_intro:
        # 软开场：封面定格 + 淡入正片首帧，自动合成片头 mp4（自带静音轨）作为第一段
        soft = ep / '_soft_intro.mp4'
        print(f'soft intro: hold {args.cover_hold}s + {args.fade}s fade → {soft.name}', flush=True)
        build_soft_intro(cover, main_v, soft, hold=args.cover_hold, fade=args.fade)
        filter_complex = (
            norm +
            '[0:a]aresample=48000:async=1,aformat=channel_layouts=stereo[a0];'
            '[1:a]aresample=48000:async=1,aformat=channel_layouts=stereo[a1];'
            '[2:a]aresample=48000:async=1,aformat=channel_layouts=stereo[a2];'
            '[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]'
        )
        inputs = ['-i', str(soft), '-i', str(main_v), '-i', str(outro)]
    else:
        # 旧模式：1 帧封面 + anullsrc 静音
        t = f'{args.cover_frames:.3f}'
        filter_complex = (
            norm +
            '[3:a]aresample=48000,aformat=channel_layouts=stereo[a0];'
            '[1:a]aresample=48000:async=1,aformat=channel_layouts=stereo[a1];'
            '[2:a]aresample=48000:async=1,aformat=channel_layouts=stereo[a2];'
            '[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]'
        )
        inputs = ['-loop', '1', '-t', t, '-i', str(cover),
                  '-i', str(main_v),
                  '-i', str(outro),
                  '-f', 'lavfi', '-t', t, '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']

    print(f'wrapping → {output}', flush=True)
    subprocess.run([
        'ffmpeg', '-y', *inputs,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '[a]',
        '-c:v', 'libx264', '-preset', args.preset, '-crf', str(args.crf),
        '-c:a', 'aac', '-b:a', '192k',
        str(output),
    ], check=True)
    print(f'wrote {output}', flush=True)


if __name__ == '__main__':
    main()
