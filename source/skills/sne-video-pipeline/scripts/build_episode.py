#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end SNE video pipeline orchestrator.

Runs steps 2-6 (assembly + karaoke + composite + wrap). Step 1 (TTS) is handled
by sne-tts skill and is a prerequisite — we just check that audio/*.wav exists.

Order:
  1. (skip if final.mp4 exists) assemble final.mp4 from 对话视频/ library
     → calls video-merge skill's three scripts
  2. transcribe whisper word timings → 全片_words.json   [cached]
  3. build karaoke ASS from script.txt + words           → 全片.ass
  4. composite bg + dialogue video + karaoke             → final_with_bg_karaoke.mp4
  5. also generate English SRT (one cue per dialogue turn) → 英文.srt
  (then: wrap_cover_outro.py — 1-frame cover + main + outro. Animated intro disabled, see SKILL.md.)

Usage:
  python build_episode.py \
    --episode-dir "g:/.../episodes/0519 whats up" \
    --speakers "Maya,Ethan" \
    --library "g:/.../SImply Natural English/对话视频" \
    --outro "g:/.../SImply Natural English/上传素材/片尾_A.mp4" \
    --title "What's Up"
"""
import argparse
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCRIPTS_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPTS_DIR.parents[2]  # skills/sne-video-pipeline/scripts → 工作区根
VIDEO_MERGE_DIR = WORKSPACE / 'skills' / 'video-merge' / 'scripts'
PY = sys.executable


def run(cmd, **kw):
    print(f'\n$ {" ".join(str(c) for c in cmd)}', flush=True)
    subprocess.run(cmd, check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode-dir', required=True)
    ap.add_argument('--speakers', required=True,
                    help='Comma-separated speakers, first one = left side (e.g. "Maya,Ethan")')
    ap.add_argument('--library', required=True, help='对话视频 material library root')
    ap.add_argument('--outro', required=True, help='Outro mp4 path')
    ap.add_argument('--title', required=True, help='Filename stem for final upload mp4')
    ap.add_argument('--scene', help='Force a specific scene (default: auto-pick shared)')
    ap.add_argument('--outfits', help='JSON dict specifying outfit per speaker (e.g. \'{"Maya":"sage丝衫","Ethan":"卡其西装"}\')')
    ap.add_argument('--skip-assemble', action='store_true',
                    help='Skip video-merge if final.mp4 already exists')
    ap.add_argument('--skip-srt', action='store_true', help='Skip English SRT generation')
    ap.add_argument('--force-whisper', action='store_true', help='Re-run whisper (ignore cache)')
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    audio = ep / 'audio'
    if not audio.exists() or not list(audio.glob('*.wav')):
        raise SystemExit(f'no audio in {audio} — run sne-tts first')

    final_mp4 = ep / 'final.mp4'

    # Step 1: assemble final.mp4 (skipped if already exists or --skip-assemble)
    if final_mp4.exists() or args.skip_assemble:
        print(f'[1/6] assemble: skip (final.mp4 {"exists" if final_mp4.exists() else "skip requested"})', flush=True)
    else:
        print('[1/6] assemble: gen_videos → merge_audio_video → concat_videos', flush=True)
        gen_cmd = [
            PY, str(VIDEO_MERGE_DIR / 'gen_videos.py'),
            '--audio-dir', str(audio),
            '--library', args.library,
            '--speakers', args.speakers,
        ]
        if args.scene:
            gen_cmd += ['--scene', args.scene]
        if args.outfits:
            gen_cmd += ['--outfits', args.outfits]
        run(gen_cmd)
        run([PY, str(VIDEO_MERGE_DIR / 'merge_audio_video.py'),
             '--audio-dir', str(audio), '--video-dir', str(ep / 'video')])
        run([PY, str(VIDEO_MERGE_DIR / 'concat_videos.py'),
             '--input-dir', str(ep / 'merge')])

    # Step 2: whisper word timings
    print('\n[2/6] transcribe whisper words', flush=True)
    cmd = [PY, str(SCRIPTS_DIR / 'transcribe_words.py'), '--episode-dir', str(ep)]
    if args.force_whisper:
        cmd.append('--force')
    run(cmd)

    # Step 3: build karaoke ASS from script.txt + words
    print('\n[3/6] build karaoke ASS', flush=True)
    run([PY, str(SCRIPTS_DIR / 'build_karaoke_ass.py'), '--episode-dir', str(ep)])

    # Step 4: composite bg + dialogue video + karaoke
    print('\n[4/6] composite bg + video + karaoke', flush=True)
    run([PY, str(SCRIPTS_DIR / 'composite_burn.py'), '--episode-dir', str(ep)])

    # Step 5: English SRT
    if args.skip_srt:
        print('\n[5/5] English SRT: skipped', flush=True)
    else:
        print('\n[5/5] English SRT', flush=True)
        run([PY, str(SCRIPTS_DIR / 'gen_en_srt.py'), '--episode-dir', str(ep)])

    # Final wrap (1-frame cover + main + outro) is a separate step, so we stop here
    # with the main video ready and print the next command.
    # Echo the wrap command. If --outro is a 片尾_*.mp4 file, echo its PARENT
    # directory instead so the manual wrap step randomly picks one of the 3
    # outros (instead of always reusing the same fixed file).
    outro_path = Path(args.outro)
    wrap_outro = outro_path.parent if outro_path.is_file() and outro_path.name.startswith('片尾_') else outro_path
    print(f'\n=== main video ready: {ep / "final_with_bg_karaoke.mp4"} ===', flush=True)
    print('Next — wrap (1-frame cover + main + outro) → final upload mp4:', flush=True)
    print(f'  {PY} {SCRIPTS_DIR / "wrap_cover_outro.py"} --episode-dir "{ep}" '
          f'--outro "{wrap_outro}" --title "{args.title}"', flush=True)
    print('  (animated intro disabled — it raised early-seconds drop-off; '
          'see SKILL.md to re-enable via gen_cover_intro.py + wrap_intro_outro.py)', flush=True)


if __name__ == '__main__':
    main()
