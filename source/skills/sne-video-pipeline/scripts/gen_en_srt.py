#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate English SRT for an SNE episode from script.txt + audio/ WAV durations.

One cue per dialogue turn (no further sub-segmentation). Timing is the accumulated
WAV duration — never Whisper — so SRT is exactly aligned with final.mp4.

Usage:
  python gen_en_srt.py --episode-dir "g:/.../episodes/0519 whats up"
  python gen_en_srt.py --script script.txt --audio-dir audio --output 英文.srt
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def get_duration(p: Path) -> float:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(p)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def fmt_ts(seconds: float) -> str:
    ms_total = int(round(seconds * 1000))
    h, rem = divmod(ms_total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_script(script_path: Path):
    out = []
    for line in script_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        if ':' in line:
            speaker, text = line.split(':', 1)
        elif '：' in line:
            speaker, text = line.split('：', 1)
        else:
            continue
        out.append((speaker.strip(), text.strip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode-dir', help='Episode dir containing script.txt + audio/')
    ap.add_argument('--script', help='Script .txt path (overrides --episode-dir)')
    ap.add_argument('--audio-dir', help='Audio dir (overrides --episode-dir)')
    ap.add_argument('--output', help='Output SRT path (default: <episode>/英文.srt)')
    args = ap.parse_args()

    if args.episode_dir:
        ep = Path(args.episode_dir)
        script = Path(args.script) if args.script else ep / 'script.txt'
        audio_dir = Path(args.audio_dir) if args.audio_dir else ep / 'audio'
        output = Path(args.output) if args.output else ep / '英文.srt'
    else:
        script = Path(args.script)
        audio_dir = Path(args.audio_dir)
        output = Path(args.output)

    turns = parse_script(script)
    wavs = sorted(audio_dir.glob('*.wav'))
    if len(turns) != len(wavs):
        raise SystemExit(f'script turns ({len(turns)}) != audio files ({len(wavs)})')

    lines = []
    cum = 0.0
    for i, ((speaker, text), wav) in enumerate(zip(turns, wavs), 1):
        dur = get_duration(wav)
        start = cum
        end = cum + dur
        cum = end
        lines.append(f'{i}\n{fmt_ts(start)} --> {fmt_ts(end)}\n{text}\n')

    output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'wrote {output} ({len(turns)} cues, total {cum:.2f}s)', flush=True)


if __name__ == '__main__':
    main()
