# -*- coding: utf-8 -*-
"""Generate 拼音.srt + 英文.srt aligned 1:1 (by time) to 全片_chars.json cues.

The three-layer renderer (subtitle-burn/build_ass.py) matches the pinyin and English
SRTs to the Chinese cues BY START TIME, so both SRTs just need the same cue order and
the cue's start/end.

  拼音.srt — generated programmatically with pypinyin (Style.TONE, one syllable per
             Chinese character, punctuation/space dropped). Same convention as
             dialogue-trilingual.
  英文.srt — read from <ep>/en_sentences.txt, ONE English line per cue, authored by
             Claude (口语化, no quotes — see project script rules). Must have exactly
             as many non-empty lines as there are cues, in the same order.

Reads  <ep>/全片_chars.json
       <ep>/en_sentences.txt
Writes <ep>/拼音.srt
       <ep>/英文.srt

Usage:
  python build_py_en_srt.py --episode-dir "g:/.../长视频/0606 我的早晨"
"""
import argparse
import json
import re
import sys
from pathlib import Path

from pypinyin import pinyin, Style

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def is_hanzi(c):
    return '一' <= c <= '鿿'


def fmt_time(sec):
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')


def py_for_text(text):
    """One toned syllable per Chinese character; latin/digit runs kept as a token.
    Punctuation and spaces dropped (build_ass positions syllables over hanzi)."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if is_hanzi(c):
            syl = pinyin(c, style=Style.TONE, errors='ignore')
            tokens.append(syl[0][0] if syl and syl[0] else c)
            i += 1
        elif c.isalnum():
            j = i
            while j < n and text[j].isalnum() and not is_hanzi(text[j]):
                j += 1
            tokens.append(text[i:j])
            i = j
        else:
            i += 1
    return ' '.join(tokens)


def write_srt(path, entries):
    with open(path, 'w', encoding='utf-8') as f:
        for i, (start, end, text) in enumerate(entries, 1):
            f.write(f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True)
    args = ap.parse_args()
    ep = Path(args.episode_dir)

    cues = json.loads((ep / "全片_chars.json").read_text(encoding="utf-8"))["cues"]

    # pinyin SRT
    py_entries = [(c["start"], c["end"], py_for_text(c["text"])) for c in cues]
    write_srt(ep / "拼音.srt", py_entries)
    print(f"wrote 拼音.srt ({len(py_entries)} cues)", flush=True)

    # english SRT
    en_path = ep / "en_sentences.txt"
    if not en_path.exists():
        raise SystemExit(
            f"missing {en_path.name} — author one English line per cue ({len(cues)} cues) "
            "first (run prep_sentences, then write en_sentences.txt against script_sentences.txt)")
    en_lines = [l.strip() for l in en_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(en_lines) != len(cues):
        raise SystemExit(
            f"en_sentences.txt has {len(en_lines)} lines but there are {len(cues)} cues — "
            "they must be 1:1 in the same order")
    en_entries = [(c["start"], c["end"], en) for c, en in zip(cues, en_lines)]
    write_srt(ep / "英文.srt", en_entries)
    print(f"wrote 英文.srt ({len(en_entries)} cues)", flush=True)


if __name__ == "__main__":
    main()
