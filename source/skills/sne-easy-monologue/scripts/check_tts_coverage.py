# -*- coding: utf-8 -*-
"""TTS coverage check — catch dropped / truncated narration.

Compares the per-sentence Whisper transcription (全片_words.json, produced by
transcribe_sentences.py) against the intended script (script_sentences.txt),
sentence by sentence. Flags any sentence whose audio is missing words — the
classic failure is a TTS engine silently truncating a long closing line
(see memory feedback_azure_truncates_closing_line).

Normalises away the harmless noise (punctuation, case, contraction tokenisation
like "do n't" / "tea bag"→"teabag") so only REAL content drops get flagged.

Wired into build_video.py right after the whisper step. By design it NEVER
aborts the build (exit 0 even on flags) — a build that completes lets you eyeball
the result; the warning is printed loudly AND written to <ep>/_tts_check.txt.
Pass --strict to exit non-zero when something is flagged (hard gate).

Usage:
  python check_tts_coverage.py --episode-dir "g:/.../0622 a cozy rainy day"
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

# Windows consoles default to GBK, which can't encode ✅/⚠/Chinese — force UTF-8
# (errors="replace" so this can never crash the build regardless of console).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# common English contractions, both directions, so "do not"/"don't"/"do n't" all match
CONTRACT = {
    "do not": "dont", "does not": "doesnt", "did not": "didnt", "is not": "isnt",
    "are not": "arent", "was not": "wasnt", "were not": "werent", "can not": "cannot",
    "cant": "cannot", "will not": "wont", "i am": "im", "it is": "its",
    "that is": "thats", "there is": "theres", "i will": "ill", "i have": "ive",
    "i would": "id", "you are": "youre", "we are": "were", "they are": "theyre",
}


def norm(t: str) -> str:
    t = t.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9'\s]", " ", t)        # drop punctuation, keep apostrophes
    t = re.sub(r"\s+", " ", t).strip()
    for a, b in CONTRACT.items():
        t = re.sub(r"\b" + a + r"\b", b, t)
    t = t.replace("'", "")                      # collapse remaining apostrophes
    return t


def words(t: str):
    return norm(t).split()


def load_sentences(p: Path):
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ln = re.sub(r"^[^:：]{1,20}[:：]\s*", "", ln)   # strip any "Speaker: " prefix
        out.append(ln)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True)
    ap.add_argument("--sentences", help="default: <ep>/script_sentences.txt")
    ap.add_argument("--words", help="default: <ep>/全片_words.json")
    ap.add_argument("--min-ratio", type=float, default=0.82,
                    help="flag a sentence if script↔whisper similarity is below this")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when any sentence is flagged (default: warn only)")
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    sp = Path(args.sentences) if args.sentences else ep / "script_sentences.txt"
    wp = Path(args.words) if args.words else ep / "全片_words.json"

    report = []

    def out(line=""):
        print(line, flush=True)
        report.append(line)

    if not sp.exists() or not wp.exists():
        out(f"[tts-check] SKIP — missing {sp.name if not sp.exists() else wp.name}")
        return 0

    sents = load_sentences(sp)
    cues = json.loads(wp.read_text(encoding="utf-8"))["cues"]

    out(f"[tts-check] script sentences: {len(sents)} | whisper cues: {len(cues)}")
    count_mismatch = len(sents) != len(cues)
    if count_mismatch:
        out("⚠⚠ COUNT MISMATCH — sentence/cue alignment is broken (this itself signals a problem).")

    flagged = []
    para_of = None
    pj = ep / "sentence_paragraph.json"
    if pj.exists():
        para_of = json.loads(pj.read_text(encoding="utf-8")).get("para_of")

    for i, (s, cue) in enumerate(zip(sents, cues)):
        wt = "".join(w["w"] for w in cue)
        sw, ww = words(s), words(wt)
        sm = difflib.SequenceMatcher(None, sw, ww)
        ratio = sm.ratio()
        matched = set()
        for b in sm.get_matching_blocks():
            for x in range(b.a, b.a + b.size):
                matched.add(x)
        # trailing script words with no match = truncated tail (the dangerous case)
        trailing_missing = 0
        for k in range(len(sw) - 1, -1, -1):
            if k in matched:
                break
            trailing_missing += 1
        missing = [w for idx, w in enumerate(sw) if idx not in matched]
        if ratio < args.min_ratio or trailing_missing >= 2 or len(ww) < len(sw) - 2:
            flagged.append((i, ratio, trailing_missing, missing, s, wt.strip()))

    tot_s = sum(len(words(s)) for s in sents)
    tot_w = sum(len(words("".join(w["w"] for w in c))) for c in cues)

    if flagged:
        out("")
        out(f"⚠⚠ TTS COVERAGE: {len(flagged)} sentence(s) flagged — possible drop/truncation:")
        for i, ratio, tm, missing, s, wt in flagged:
            pinfo = f" 段{para_of[i]}" if para_of and i < len(para_of) else ""
            out(f"  [句{i:03d}{pinfo}] ratio={ratio:.2f} trailing_missing={tm} missing={missing}")
            out(f"     script : {s}")
            out(f"     heard  : {wt}")
        out("")
        out(f"  → 复查上面这些句的 audio/，必要时重合成该句（删对应 WAV 后 --skip 其它步骤重跑）。")
    else:
        out(f"✅ TTS coverage OK — {len(sents)}/{len(cues)} sentences, "
            f"no drops/truncation (words script={tot_s} heard={tot_w}).")

    (ep / "_tts_check.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    if args.strict and (flagged or count_mismatch):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
