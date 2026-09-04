#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build karaoke ASS from script.txt (TEXT source of truth) + whisper words.json (TIMING).

For each dialogue line:
  - If script tokens == whisper words count: swap 1:1 (script text, whisper timings)
  - Otherwise: stretch line_start..line_end proportionally across script tokens

Why this matters: Whisper may mis-recognize text (e.g. "going to" vs "gonna",
quotes/punctuation), but the script is the canonical wording. Subtitles must
display script text, not whisper output.

Usage:
  python build_karaoke_ass.py --episode-dir "g:/.../episodes/0519 whats up"
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def body_duration(ep: Path):
    """正片(body)时长，用于把末句字幕延到正片末尾填满尾静音。
    优先 timeline.json 的 total（独白）；否则 ffprobe final.mp4（播客）。"""
    tj = ep / 'timeline.json'
    if tj.exists():
        try:
            return float(json.loads(tj.read_text(encoding='utf-8'))['total'])
        except Exception:
            pass
    final = ep / 'final.mp4'
    if final.exists():
        try:
            out = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(final)],
                capture_output=True, text=True, check=True)
            return float(out.stdout.strip())
        except Exception:
            pass
    return None

# Final canvas (matches SNE template 1920x1080)
W, H = 1920, 1080
# Karaoke text position (center of subtitle bar)
# SUB_CY raised 800 → 730 (2026-06-07): user found 800 sat too low in the
# subtitle band; 730 centers it better. Applies to all SNE long-form episodes.
SUB_CX, SUB_CY = 960, 730


ASS_HEADER_TPL = """[Script Info]
Title: SNE karaoke
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{font},{size},{primary},{secondary},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,3,2,5,160,160,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def fmt_ass_ts(seconds: float) -> str:
    cs_total = int(round(seconds * 100))
    h, rem = divmod(cs_total, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f'{h:d}:{m:02d}:{s:02d}.{cs:02d}'


def normalize_dashes(text):
    """把破折号类分隔符归一化成空格，让脚本切词与 Whisper 词数对齐。

    破折号在语音里不发音：TTS 不读它，Whisper 把它两侧的词当成独立的两个词输出。
    但脚本里破折号常常黏在词上没空格（如 `"SHOTGUN!"—relax`），按 \\S+ 切词会被当成
    一个 token，比 Whisper 少一个词 → align_words 走到等分兜底 → 整句卡拉OK漂移。
    这里把 em/en dash、ASCII 双连字符 `--`、以及两侧带空格的单 `-` 都归成空格；
    词内连字符（half-frame / fuddy-duddy，无空格包围）保留不动，交给 _merge_hyphen_splits 处理。
    """
    text = re.sub(r'\s*[—–]\s*', ' ', text)   # em / en dash
    text = re.sub(r'\s*--+\s*', ' ', text)     # ASCII 双连字符 "--"
    text = re.sub(r'\s+-\s+', ' ', text)        # 两侧带空格的单连字符 " - "
    return text


def parse_script(script_path: Path):
    out = []
    for line in script_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        if ':' in line:
            _, text = line.split(':', 1)
        elif '：' in line:
            _, text = line.split('：', 1)
        else:
            continue
        out.append(text.strip())
    return out


def split_into_screen_chunks(words, target=16, hard_cap=40, min_words=4):
    """Split a list of aligned word dicts into chunks for separate ASS cues.

    Strategy (greedy sentence-first):
      - Walk words. As soon as a word ends in . ! ? AND chunk has at least
        min_words, CUT there — regardless of whether we've hit target yet.
        This means short sentences become their own cue, long sentences only
        get cut at their natural endings (allowed to exceed target).
      - If we reach hard_cap without any sentence-end, fall back: cut at last
        comma/semicolon in the chunk; else hard cut at hard_cap.
      - Tiny "Yes.", "Right." sentences (< min_words) are absorbed into the
        next chunk so they don't become 1-word flashes.
    """
    if not words:
        return []
    chunks = []
    cur = []
    SENT_END = ('.', '!', '?')
    SOFT_END = (',', ';', ':')

    def last_char(w):
        s = w['w'].rstrip()
        return s[-1] if s else ''

    for w in words:
        cur.append(w)
        end_char = last_char(cur[-1])
        if end_char in SENT_END and len(cur) >= min_words:
            chunks.append(cur)
            cur = []
            continue
        if len(cur) >= hard_cap:
            # Fall back: find last soft-end inside cur
            cut = None
            for i in range(len(cur) - 1, -1, -1):
                if last_char(cur[i]) in SOFT_END or last_char(cur[i]) in SENT_END:
                    cut = i + 1
                    break
            if cut is None or cut < min_words:
                cut = len(cur)
            chunks.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        chunks.append(cur)
    return chunks


CONTRACTIONS = {
    "i'm": ["i", "am"], "i've": ["i", "have"], "i'll": ["i", "will"],
    "i'd": ["i", "would"], "it's": ["it", "is"], "he's": ["he", "is"],
    "she's": ["she", "is"], "that's": ["that", "is"], "what's": ["what", "is"],
    "there's": ["there", "is"], "here's": ["here", "is"], "who's": ["who", "is"],
    "we're": ["we", "are"], "they're": ["they", "are"], "you're": ["you", "are"],
    "we've": ["we", "have"], "they've": ["they", "have"], "you've": ["you", "have"],
    "we'll": ["we", "will"], "they'll": ["they", "will"], "you'll": ["you", "will"],
    "we'd": ["we", "would"], "they'd": ["they", "would"], "you'd": ["you", "would"],
    "won't": ["will", "not"], "don't": ["do", "not"], "doesn't": ["does", "not"],
    "didn't": ["did", "not"], "isn't": ["is", "not"], "aren't": ["are", "not"],
    "wasn't": ["was", "not"], "weren't": ["were", "not"], "hasn't": ["has", "not"],
    "haven't": ["have", "not"], "hadn't": ["had", "not"], "can't": ["can", "not"],
    "couldn't": ["could", "not"], "wouldn't": ["would", "not"],
    "shouldn't": ["should", "not"], "let's": ["let", "us"],
}


def _merge_hyphen_splits(tokens, whisper_words):
    """Merge Whisper tokens that were split on hyphens (e.g. 'F' + '-O' + '-M' + '-O' → 'F-O-M-O').
    Greedy: keeps consuming consecutive tokens starting with '-'.
    Returns (merged_tokens, merged_words) with timing spans combined."""
    merged_t = []
    merged_w = []
    i = 0
    while i < len(tokens):
        combined = tokens[i]
        end_idx = i
        while end_idx + 1 < len(tokens) and tokens[end_idx + 1].startswith('-'):
            end_idx += 1
            combined += tokens[end_idx]
        merged_t.append(combined)
        merged_w.append({'w': combined, 'start': whisper_words[i]['start'],
                         'end': whisper_words[end_idx]['end']})
        i = end_idx + 1
    return merged_t, merged_w


def _expand_contractions(tokens):
    """Expand contractions to match script's full forms. Returns (expanded, mapping).
    mapping[i] = list of original token indices that produced expanded[i]."""
    expanded = []
    mapping = []
    for idx, tok in enumerate(tokens):
        key = re.sub(r'[.,!?;:\'"]+$', '', tok).lower()
        trail = tok[len(key):]
        if key in CONTRACTIONS:
            parts = CONTRACTIONS[key]
            for j, p in enumerate(parts):
                expanded.append(p + (trail if j == len(parts) - 1 else ''))
                mapping.append(idx)
        else:
            expanded.append(tok)
            mapping.append(idx)
    return expanded, mapping


def align_words(script_tokens, whisper_words):
    """Return list of dicts {w, start, end} using script tokens with whisper timings.

    Handles contraction mismatches (e.g. Whisper "I'm" vs script "I am") by
    expanding contractions in Whisper words before alignment, then mapping
    timings back to script tokens."""
    n_s, n_w = len(script_tokens), len(whisper_words)
    if n_s == 0 or n_w == 0:
        return []
    if n_s == n_w:
        return [{'w': s, 'start': w['start'], 'end': w['end']}
                for s, w in zip(script_tokens, whisper_words)]

    whisper_tokens = [w['w'].strip() for w in whisper_words]

    merged_tokens, merged_words = _merge_hyphen_splits(whisper_tokens, whisper_words)
    if len(merged_tokens) == n_s:
        return [{'w': s, 'start': mw['start'], 'end': mw['end']}
                for s, mw in zip(script_tokens, merged_words)]

    expanded, orig_idx = _expand_contractions(merged_tokens)

    if len(expanded) == n_s:
        out = []
        for i, tok in enumerate(script_tokens):
            wi = orig_idx[i]
            mw = merged_words[wi]
            if i > 0 and orig_idx[i] == orig_idx[i - 1]:
                out.append({'w': tok, 'start': out[-1]['end'], 'end': mw['end']})
            else:
                siblings = [j for j in range(len(expanded)) if orig_idx[j] == wi]
                my_pos = siblings.index(i)
                span = mw['end'] - mw['start']
                frac = span / len(siblings)
                out.append({'w': tok, 'start': mw['start'] + frac * my_pos,
                            'end': mw['start'] + frac * (my_pos + 1)})
        return out

    line_start = whisper_words[0]['start']
    line_end = whisper_words[-1]['end']
    span = max(line_end - line_start, 0.001)
    out = []
    for i, tok in enumerate(script_tokens):
        a = line_start + span * (i / n_s)
        b = line_start + span * ((i + 1) / n_s)
        out.append({'w': tok, 'start': a, 'end': b})
    return out


def build_cue(words, sub_cx, sub_cy):
    """Return (line_start, line_end, ass_body) where ass_body is the karaoke
    text including position tag. Caller assembles Dialogue line with possibly
    extended end time to glue to next cue."""
    if not words:
        return None
    line_start = words[0]['start']
    line_end = words[-1]['end']
    parts = []
    prev_end = line_start
    for w in words:
        gap_cs = max(0, int(round((w['start'] - prev_end) * 100)))
        if gap_cs > 0:
            parts.append(f'{{\\k{gap_cs}}}')
        dur_cs = max(1, int(round((w['end'] - w['start']) * 100)))
        text = w['w'].lstrip()
        parts.append(f'{{\\kf{dur_cs}}}{text} ')
        prev_end = w['end']
    line = ''.join(parts).rstrip()
    pos = f'{{\\pos({sub_cx},{sub_cy})}}'
    return (line_start, line_end, f'{pos}{line}')


def format_dialogue(line_start, line_end, body):
    return f'Dialogue: 0,{fmt_ass_ts(line_start)},{fmt_ass_ts(line_end)},Karaoke,,0,0,0,,{body}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode-dir', required=True)
    ap.add_argument('--script', help='Override script path (default: <ep>/script.txt)')
    ap.add_argument('--words', help='Override words JSON path (default: <ep>/全片_words.json)')
    ap.add_argument('--output', help='Output ASS path (default: <ep>/全片.ass)')
    ap.add_argument('--font', default='Arial')
    ap.add_argument('--size', type=int, default=78)
    ap.add_argument('--primary', default='&H000060F0',
                    help='Highlighted color (BGR hex, default orange &H000060F0 = #F06000)')
    ap.add_argument('--secondary', default='&H00404040',
                    help='Un-highlighted color (default dark grey)')
    ap.add_argument('--outline', default='&H00FFFFFF', help='Outline color (default white)')
    ap.add_argument('--sub-cx', type=int, default=SUB_CX)
    ap.add_argument('--sub-cy', type=int, default=SUB_CY)
    ap.add_argument('--max-words', type=int, default=16,
                    help='Soft target words per on-screen cue; chunks cut at sentence-end '
                         'once this is reached (default 16).')
    ap.add_argument('--extend-last-to-end', action=argparse.BooleanOptionalAction, default=True,
                    help='把末句字幕延到正片末尾，填满尾静音（默认开）；--no-extend-last-to-end 关闭')
    ap.add_argument('--hard-cap', type=int, default=40,
                    help='Hard maximum words per cue (default 40).')
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    script = Path(args.script) if args.script else ep / 'script.txt'
    words_json = Path(args.words) if args.words else ep / '全片_words.json'
    output = Path(args.output) if args.output else ep / '全片.ass'

    texts = parse_script(script)
    whisper_cues = json.loads(words_json.read_text(encoding='utf-8'))['cues']
    if len(texts) != len(whisper_cues):
        raise SystemExit(f'line count mismatch: script={len(texts)} whisper={len(whisper_cues)}')

    raw_cues = []  # list of (start, end, body)
    one_to_one = contraction_fixed = hyphen_fixed = mismatch = 0
    split_count = 0
    for idx, (text, ww) in enumerate(zip(texts, whisper_cues)):
        tokens = re.findall(r'\S+', normalize_dashes(text))
        if len(tokens) == len(ww):
            one_to_one += 1
        else:
            wtoks = [w['w'].strip() for w in ww]
            mt, mw = _merge_hyphen_splits(wtoks, ww)
            if len(mt) == len(tokens):
                hyphen_fixed += 1
            else:
                exp, _ = _expand_contractions(mt)
                if len(exp) == len(tokens):
                    contraction_fixed += 1
                else:
                    mismatch += 1
                    print(f'  ⚠ line {idx+1}: script={len(tokens)} vs whisper={len(wtoks)} '
                          f'(merge→{len(mt)}, expand→{len(exp)})', flush=True)
                    for j in range(max(len(tokens), len(exp))):
                        s = tokens[j] if j < len(tokens) else ''
                        w = exp[j] if j < len(exp) else ''
                        flag = ' ✗' if s.lower().rstrip('.,!?\"\';:') != w.lower().rstrip('.,!?\"\';:') else ''
                        if flag:
                            print(f'      {j:3d}: "{s}" vs "{w}"{flag}', flush=True)
        aligned = align_words(tokens, ww)
        chunks = split_into_screen_chunks(aligned, target=args.max_words, hard_cap=args.hard_cap)
        if len(chunks) > 1:
            split_count += 1
        for chunk in chunks:
            c = build_cue(chunk, args.sub_cx, args.sub_cy)
            if c:
                raw_cues.append(c)

    # 末句停留：把最后一个 cue 延到正片末尾，填满尾静音（不动 \k，libass 烧满后保持满亮）。
    last_end = None
    if args.extend_last_to_end:
        last_end = body_duration(ep)
        if last_end is None:
            print('[WARN] 找不到 timeline.json/final.mp4，末句停留跳过（不延伸）', flush=True)

    # Glue each cue's end to next cue's start so subtitles never blink off
    # mid-pause.
    cues = []
    for i, (s, e, body) in enumerate(raw_cues):
        if i + 1 < len(raw_cues):
            next_s = raw_cues[i + 1][0]
            cues.append(format_dialogue(s, max(next_s, e), body))
        else:
            end = e
            if last_end and last_end > end:
                end = last_end
            cues.append(format_dialogue(s, end, body))

    header = ASS_HEADER_TPL.format(
        W=W, H=H, font=args.font, size=args.size,
        primary=args.primary, secondary=args.secondary, outline=args.outline,
    )
    output.write_text(header + '\n'.join(cues) + '\n', encoding='utf-8')
    print(f'wrote {output} ({len(cues)} cues from {len(texts)} turns; '
          f'1:1={one_to_one}, hyphen-merged={hyphen_fixed}, contraction-expanded={contraction_fixed}, '
          f'proportional={mismatch}, split-turns={split_count}, '
          f'max-words={args.max_words}, hard-cap={args.hard_cap})', flush=True)


if __name__ == '__main__':
    main()
