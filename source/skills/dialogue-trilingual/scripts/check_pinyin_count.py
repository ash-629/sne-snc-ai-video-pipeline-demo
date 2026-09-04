# -*- coding: utf-8 -*-
"""校验 三语.txt 每段拼音音节数 == 汉字数 + 拉丁词数。

用途：Claude 按上下文修完多音字拼音后跑一遍，确认没有把某个字的拼音删掉/多加、
或把英文短语拆成多 token。任何 mismatch 都会列出来，说明拼音行和中文对不上，
下游卡拉OK/拼音SRT 会错位。

用法：
    python check_pinyin_count.py --script "长视频/XXXX/XXXX_三语.txt"

零 mismatch = 拼音对齐 OK（不保证读音对，读音靠 Claude 上下文审）。
"""
import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def is_cjk(c: str) -> bool:
    return "一" <= c <= "鿿"


def strip_speaker(t: str) -> str:
    return re.sub(r"^[^：:]{1,20}[：:]", "", t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="xxx_三语.txt 路径")
    args = ap.parse_args()

    paras = open(args.script, encoding="utf-8").read().strip().split("\n\n")
    bad = []
    n_ok = 0
    for pi, p in enumerate(paras, 1):
        lines = [l for l in p.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        ch = strip_speaker(lines[0])
        py = lines[1].split()
        n_cjk = sum(1 for c in ch if is_cjk(c))
        # 拉丁词按「单词」数：gen_skeleton 把英文短语按空格拆成多 token
        # （如 under the weather → 3 个音节 token），所以每个英文单词算 1。
        n_latin = len(re.findall(r"[A-Za-z]+", ch))
        expect = n_cjk + n_latin
        if len(py) != expect:
            bad.append((pi, n_cjk, n_latin, len(py), lines[0], lines[1]))
        else:
            n_ok += 1

    if bad:
        print(f"⚠⚠ {len(bad)} 段音节数对不上（拼音行和中文错位，必须修）：")
        for pi, c, l, s, zh, py in bad:
            print(f"  段{pi}: 汉字{c}+拉丁{l}={c+l} ≠ 音节{s}")
            print(f"     中: {zh}")
            print(f"     拼: {py}")
        sys.exit(1)
    print(f"✅ 拼音音节数全部对齐（{n_ok} 段，一字一音节）。读音是否正确仍需人工/LLM 审。")


if __name__ == "__main__":
    main()
