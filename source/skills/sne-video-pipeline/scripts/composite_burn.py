#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composite final.mp4 into the SNE background template's video window and burn the karaoke ASS.

Layout (1920x1080):
  - background image (背景图.png) scaled to fill canvas
  - final.mp4 (the speaker-pair dialogue video) scaled+cropped to fit the
    template's transparent video window
  - karaoke ASS burned on top, positioned over the white subtitle bar

Usage:
  python composite_burn.py --episode-dir "g:/.../episodes/0519 whats up"
"""
import argparse
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Canvas
W, H = 1920, 1080
# Video window on 1920x1080 (derived from SNE 1280x720 template, scaled 1.5x)
# Template transparent region: x=714..1199, y=25..285 → 1070..1798 / 38..430 → 730 x 392
DEFAULT_WIN_X, DEFAULT_WIN_Y, DEFAULT_WIN_W, DEFAULT_WIN_H = 1070, 38, 730, 392


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode-dir', required=True)
    ap.add_argument('--bg', help='Background PNG (default: <ep>/背景图.png)')
    ap.add_argument('--video', help='Speaker-pair video (default: <ep>/final.mp4)')
    ap.add_argument('--ass', help='Karaoke ASS (default: <ep>/全片.ass)')
    ap.add_argument('--output', help='Output MP4 (default: <ep>/final_with_bg_karaoke.mp4)')
    ap.add_argument('--win-x', type=int, default=DEFAULT_WIN_X)
    ap.add_argument('--win-y', type=int, default=DEFAULT_WIN_Y)
    ap.add_argument('--win-w', type=int, default=DEFAULT_WIN_W)
    ap.add_argument('--win-h', type=int, default=DEFAULT_WIN_H)
    ap.add_argument('--crf', type=int, default=20)
    ap.add_argument('--preset', default='fast')
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    bg = Path(args.bg) if args.bg else ep / '背景图.png'
    video = Path(args.video) if args.video else ep / 'final.mp4'
    ass = Path(args.ass) if args.ass else ep / '全片.ass'
    output = Path(args.output) if args.output else ep / 'final_with_bg_karaoke.mp4'

    for p, name in [(bg, 'bg'), (video, 'video'), (ass, 'ass')]:
        if not p.exists():
            raise SystemExit(f'missing {name}: {p}')

    # ffmpeg ass filter on Windows: escape `:` in drive paths and `\` → `/`
    ass_path = str(ass).replace('\\', '/').replace(':', '\\:')
    filter_complex = (
        f"[0:v]scale={W}:{H}[bg];"
        f"[1:v]scale={args.win_w}:-2,crop={args.win_w}:{args.win_h}[fg];"
        f"[bg][fg]overlay={args.win_x}:{args.win_y}[mid];"
        f"[mid]ass='{ass_path}'[v]"
    )

    print(f'compositing → {output}', flush=True)
    subprocess.run([
        'ffmpeg', '-y',
        '-loop', '1', '-i', str(bg),
        '-i', str(video),
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '1:a',
        '-c:v', 'libx264', '-preset', args.preset, '-crf', str(args.crf),
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        '-shortest',
        str(output),
    ], check=True)
    print(f'wrote {output}', flush=True)


if __name__ == '__main__':
    main()
