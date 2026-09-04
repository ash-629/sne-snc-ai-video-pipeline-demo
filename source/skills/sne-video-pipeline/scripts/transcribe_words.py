#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whisper word-timestamp every WAV in audio/ for karaoke highlighting.

Output: {episode}/全片_words.json — {cum: total_secs, cues: [[{w,start,end}, ...], ...]}
        with absolute timestamps (start of each WAV offset by sum of prior WAVs).

Only used for *timing* (which word is being spoken when). The actual text shown in
subtitles comes from script.txt — see build_karaoke_ass.py.

Usage:
  python transcribe_words.py --episode-dir "g:/.../episodes/0519 whats up"

Requires: faster-whisper, CUDA DLLs in .venv/Lib/site-packages/ctranslate2/
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def get_duration(p: Path) -> float:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(p)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode-dir', required=True)
    ap.add_argument('--audio-dir', help='Override audio dir (default: <ep>/audio)')
    ap.add_argument('--output', help='Output JSON path (default: <ep>/全片_words.json)')
    ap.add_argument('--model', default='Systran/faster-whisper-large-v2',
                    help='faster-whisper model name (default: large-v2)')
    ap.add_argument('--language', default='en')
    ap.add_argument('--force', action='store_true', help='Re-transcribe even if cache exists')
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    audio_dir = Path(args.audio_dir) if args.audio_dir else ep / 'audio'
    output = Path(args.output) if args.output else ep / '全片_words.json'

    if output.exists() and not args.force:
        cached = json.loads(output.read_text(encoding='utf-8'))
        print(f'cache exists: {output} ({len(cached["cues"])} cues, cum {cached["cum"]:.2f}s) — pass --force to redo',
              flush=True)
        return

    wavs = sorted(audio_dir.glob('*.wav'))
    if not wavs:
        raise SystemExit(f'no wavs in {audio_dir}')

    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(args.model, device='cuda', compute_type='float16')
        print('model loaded on cuda', flush=True)
    except Exception as e:
        print(f'cuda failed ({e}); falling back to cpu int8', flush=True)
        model = WhisperModel(args.model, device='cpu', compute_type='int8')

    cue_words = []
    cum = 0.0
    n = len(wavs)
    for i, wav in enumerate(wavs, 1):
        dur = get_duration(wav)
        segments, info = model.transcribe(
            str(wav), language=args.language, word_timestamps=True,
            vad_filter=False, beam_size=5,
        )
        words = []
        for seg in segments:
            for w in seg.words or []:
                words.append({
                    'w': w.word,
                    'start': round(w.start + cum, 3),
                    'end': round(min(w.end, dur) + cum, 3),
                })
        cue_words.append(words)
        cum += dur
        if i % 5 == 0 or i == n:
            print(f'  [{i}/{n}] {wav.name} (+{dur:.2f}s, cum {cum:.1f}s)', flush=True)

    output.write_text(
        json.dumps({'cum': cum, 'cues': cue_words}, ensure_ascii=False),
        encoding='utf-8',
    )
    print(f'wrote {output} ({n} cues, total {cum:.2f}s)', flush=True)


if __name__ == '__main__':
    main()
