#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕 QA 检查：验证英文/拼音 SRT 与三语脚本的段落对齐。

两层检查：
  1. 段落边界对齐 — 每段对话的英文是否溢出到下一段的 cue
  2. 抽样对照 — 随机抽 N 条 cue 并排输出中/拼/英，方便目视快扫

有 BOUNDARY_OVERFLOW 时 exit code = 1。

用法：
  python check_srt.py \
    --zh-srt 示例.srt \
    --py-srt 示例_拼音.srt \
    --en-srt 示例_英文.srt \
    --script 示例_三语.txt \
    --sample 20
"""

import argparse
import io
import random
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

PUNC = re.compile(r'[，。？！、""''《》「」\s\'\",.:;!?…—～\-()（）]')


def parse_srt(path):
    content = Path(path).read_text(encoding='utf-8-sig')
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\n+', content.strip())
    out = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            out.append({
                'num': lines[0].strip(),
                'timing': lines[1].strip(),
                'text': ' '.join(lines[2:]).strip()
            })
    return out


def parse_script(path):
    content = Path(path).read_text(encoding='utf-8-sig')
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = re.split(r'\n\n+', content.strip())
    segs = []
    for para in paragraphs:
        lines = [l.strip() for l in para.strip().split('\n') if l.strip()]
        if len(lines) >= 3:
            segs.append({
                'chinese': lines[0],
                'pinyin': lines[1],
                'english': lines[2],
            })
    return segs


def clean_chinese(t):
    t = re.sub(r'^[^：:]*[：:]', '', t)
    return PUNC.sub('', t)


def clean_english(t):
    t = re.sub(r'^[A-Za-z\-]+:\s*', '', t).strip()
    return t


def normalize(s):
    return PUNC.sub('', s).lower().strip()


def map_cues_to_paragraphs(zh_cues, script_segs):
    """Map each SRT cue to its source paragraph index by forward-matching Chinese chars."""
    full_script_chars = []
    para_boundaries = []
    for seg in script_segs:
        cleaned = clean_chinese(seg['chinese'])
        start = len(full_script_chars)
        full_script_chars.extend(list(cleaned))
        para_boundaries.append((start, len(full_script_chars)))

    cue_para = []
    consumed = 0

    for cue in zh_cues:
        cue_clean = clean_chinese(cue['text'])
        if not cue_clean:
            cue_para.append(-1)
            continue

        best_pos = consumed
        for i in range(len(cue_clean)):
            ch = cue_clean[i]
            search_start = best_pos + i
            found = False
            for j in range(search_start, min(search_start + 20, len(full_script_chars))):
                if j < len(full_script_chars) and full_script_chars[j] == ch:
                    if i == 0:
                        best_pos = j
                    found = True
                    break
            if not found:
                break

        para_idx = -1
        mid = best_pos + len(cue_clean) // 2
        for pi, (ps, pe) in enumerate(para_boundaries):
            if ps <= mid < pe:
                para_idx = pi
                break

        if para_idx == -1 and best_pos < len(full_script_chars):
            for pi, (ps, pe) in enumerate(para_boundaries):
                if ps <= best_pos < pe:
                    para_idx = pi
                    break

        cue_para.append(para_idx)
        consumed = best_pos + len(cue_clean)

    return cue_para


def check_boundary_alignment(zh_cues, en_cues, script_segs, cue_para):
    """Check that English text in each paragraph's cues matches the paragraph's English."""
    issues = []

    para_cue_groups = {}
    for ci, pi in enumerate(cue_para):
        if pi < 0:
            continue
        para_cue_groups.setdefault(pi, []).append(ci)

    for pi, cue_indices in sorted(para_cue_groups.items()):
        if pi >= len(script_segs):
            continue

        script_en = normalize(clean_english(script_segs[pi]['english']))
        if not script_en:
            continue

        combined_en = ' '.join(en_cues[ci]['text'] for ci in cue_indices if ci < len(en_cues))
        combined_norm = normalize(combined_en)

        if not combined_norm:
            continue

        is_prefix = script_en.startswith(combined_norm[:min(len(combined_norm), 20)])
        combined_is_prefix = combined_norm.startswith(script_en[:min(len(script_en), 20)])

        if is_prefix or combined_is_prefix:
            continue

        last_cue_idx = cue_indices[-1]
        next_cue_idx = last_cue_idx + 1
        if next_cue_idx < len(en_cues):
            next_en = normalize(en_cues[next_cue_idx]['text'])
            spillover = combined_norm + ' ' + next_en
            if script_en.startswith(spillover[:min(len(spillover), 30)]) or \
               spillover.startswith(script_en[:min(len(script_en), 30)]):
                issues.append({
                    'type': 'BOUNDARY_OVERFLOW',
                    'para_idx': pi,
                    'cue_range': f"{cue_indices[0]+1}-{cue_indices[-1]+1}",
                    'script_zh': script_segs[pi]['chinese'],
                    'script_en': script_segs[pi]['english'],
                    'cue_en': combined_en,
                    'overflow_cue': next_cue_idx + 1,
                    'overflow_text': en_cues[next_cue_idx]['text'],
                })
                continue

        first_word_combined = combined_norm.split()[0] if combined_norm.split() else ''
        first_word_script = script_en.split()[0] if script_en.split() else ''
        if first_word_combined and first_word_script and first_word_combined != first_word_script:
            issues.append({
                'type': 'MISMATCH',
                'para_idx': pi,
                'cue_range': f"{cue_indices[0]+1}-{cue_indices[-1]+1}",
                'script_zh': script_segs[pi]['chinese'],
                'script_en': script_segs[pi]['english'],
                'cue_en': combined_en,
            })

    return issues


def check_suspicious_cues(en_cues):
    """Flag cues with potential issues."""
    flags = []
    for i, cue in enumerate(en_cues):
        text = cue['text'].strip()
        if not text:
            flags.append((i, 'EMPTY', text))
            continue
        words = text.split()
        if len(words) < 3 and not re.match(r'^(Yes|No|Yeah|Yep|Nope|Right|Exactly|Haha|Wow|Huh|Mm|Oh|Really|Sure|Got it|Like what|What|Why)', text):
            flags.append((i, 'SHORT', text))
        if text[0].islower():
            flags.append((i, 'LOWERCASE_START', text))
    return flags


def sample_cues(zh_cues, py_cues, en_cues, n=20):
    """Random sample of cues for visual inspection."""
    total = min(len(zh_cues), len(py_cues), len(en_cues))
    if total == 0:
        return []
    indices = sorted(random.sample(range(total), min(n, total)))
    samples = []
    for i in indices:
        samples.append({
            'cue': i + 1,
            'zh': zh_cues[i]['text'],
            'py': py_cues[i]['text'] if i < len(py_cues) else '???',
            'en': en_cues[i]['text'] if i < len(en_cues) else '???',
        })
    return samples


def main():
    ap = argparse.ArgumentParser(description='字幕 QA 检查')
    ap.add_argument('--zh-srt', required=True)
    ap.add_argument('--py-srt', required=True)
    ap.add_argument('--en-srt', required=True)
    ap.add_argument('--script', required=True)
    ap.add_argument('--sample', type=int, default=20)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    zh_cues = parse_srt(args.zh_srt)
    py_cues = parse_srt(args.py_srt)
    en_cues = parse_srt(args.en_srt)
    script_segs = parse_script(args.script)

    print(f'输入: {len(zh_cues)} 中文 cue, {len(py_cues)} 拼音 cue, '
          f'{len(en_cues)} 英文 cue, {len(script_segs)} 三语段落\n', flush=True)

    if len(zh_cues) != len(en_cues):
        print(f'  ⚠ 中文 cue ({len(zh_cues)}) != 英文 cue ({len(en_cues)})\n')
    if len(zh_cues) != len(py_cues):
        print(f'  ⚠ 中文 cue ({len(zh_cues)}) != 拼音 cue ({len(py_cues)})\n')

    cue_para = map_cues_to_paragraphs(zh_cues, script_segs)

    print('=== 段落边界检查 ===', flush=True)
    issues = check_boundary_alignment(zh_cues, en_cues, script_segs, cue_para)

    if not issues:
        print(f'  ✓ {len(script_segs)}/{len(script_segs)} 段落英文对齐正确\n')
    else:
        ok = len(script_segs) - len(issues)
        print(f'  ✓ {ok}/{len(script_segs)} 段落英文对齐正确')
        for iss in issues:
            if iss['type'] == 'BOUNDARY_OVERFLOW':
                print(f'  ✗ 段落 {iss["para_idx"]+1} (cue {iss["cue_range"]}): 英文溢出到 cue {iss["overflow_cue"]}')
                print(f'    中文: {iss["script_zh"]}')
                print(f'    英文 cue: {iss["cue_en"]}')
                print(f'    溢出 cue {iss["overflow_cue"]}: {iss["overflow_text"]}')
            elif iss['type'] == 'MISMATCH':
                print(f'  ✗ 段落 {iss["para_idx"]+1} (cue {iss["cue_range"]}): 英文可能不匹配')
                print(f'    中文: {iss["script_zh"]}')
                print(f'    脚本英文: {iss["script_en"]}')
                print(f'    SRT 英文: {iss["cue_en"]}')
            print()

    suspicious = check_suspicious_cues(en_cues)
    if suspicious:
        print(f'=== 可疑英文 cue ({len(suspicious)} 条) ===', flush=True)
        for ci, flag, text in suspicious[:15]:
            print(f'  [cue {ci+1}] {flag}: "{text}"')
            if ci < len(zh_cues):
                print(f'           中文: {zh_cues[ci]["text"]}')
        if len(suspicious) > 15:
            print(f'  ... 还有 {len(suspicious)-15} 条')
        print()

    print(f'=== 抽样对照 ({args.sample} 条) ===', flush=True)
    samples = sample_cues(zh_cues, py_cues, en_cues, args.sample)
    for s in samples:
        print(f'  [cue {s["cue"]}] 中: {s["zh"]}')
        print(f'           拼: {s["py"]}')
        print(f'           英: {s["en"]}')
        print()

    if issues:
        print(f'❌ 发现 {len(issues)} 个段落边界问题，建议修复后再上传', flush=True)
        sys.exit(1)
    else:
        print('✅ 字幕检查通过', flush=True)


if __name__ == '__main__':
    main()
