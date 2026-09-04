# -*- coding: utf-8 -*-
"""Chinese TTS coverage check — catch dropped / truncated narration (SNC monologue).

Sibling of sne-easy-monologue/check_tts_coverage.py but for CHINESE: that one's
normaliser keeps only [a-z0-9] so it blanks out Chinese. This one re-runs Whisper
(zh) on each audio/NNN_*.wav to get the RAW transcription and compares it
char-by-char (CJK only) against script_sentences.txt. Flags sentences where the
audio is missing characters — classic Azure DragonHD silent truncation of a long
closing line (memory feedback_azure_truncates_closing_line).

NOTE: 全片_chars.json can't be used for this — its `text` is the *aligned script*
(the target), not what was actually heard, so by construction it always matches.

Usage:
  python check_tts_coverage_zh.py --episode-dir "g:/.../慢速独白/0623 我的房间"
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, r"g:/youtube workspace/skills/srt-from-segments/scripts")
from build_srt_v2 import setup_cuda_dll_paths  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CJK = re.compile(r"[一-鿿]")

try:
    import zhconv  # whisper often emits Traditional; normalise to Simplified before comparing
    _t2s = lambda t: zhconv.convert(t, "zh-cn")  # noqa: E731
except Exception:
    _t2s = lambda t: t  # noqa: E731


def cjk_only(t: str) -> str:
    return "".join(CJK.findall(_t2s(t)))


def strip_speaker(ln: str) -> str:
    return re.sub(r"^[^:：]{1,20}[:：]\s*", "", ln.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True)
    ap.add_argument("--model", default="large-v2")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--min-ratio", type=float, default=0.82,
                    help="flag if script↔heard CJK similarity below this")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    ep = Path(args.episode_dir)
    sents = [strip_speaker(l) for l in (ep / "script_sentences.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    wavs = sorted((ep / "audio").glob("[0-9]*.wav"))
    report = []

    def out(s=""):
        print(s, flush=True)
        report.append(s)

    if len(wavs) != len(sents):
        out(f"⚠⚠ COUNT MISMATCH: {len(wavs)} wavs vs {len(sents)} sentences")

    if args.device == "cuda":
        setup_cuda_dll_paths()
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(args.model, device=args.device, compute_type="float16")
    except Exception as e:
        out(f"  cuda failed ({e}); cpu int8")
        model = WhisperModel(args.model, device="cpu", compute_type="int8")

    out(f"[tts-check-zh] {len(wavs)} sentences, whisper {args.model}/{args.device}")
    flagged = []
    for i, (wav, s) in enumerate(zip(wavs, sents), 1):
        segs, _ = model.transcribe(str(wav), language="zh", beam_size=5)
        heard_raw = "".join(seg.text for seg in segs)
        a, b = cjk_only(s), cjk_only(heard_raw)
        sm = difflib.SequenceMatcher(None, a, b)
        ratio = sm.ratio()
        # trailing script chars with no match = truncated tail (dangerous)
        matched = set()
        for blk in sm.get_matching_blocks():
            for x in range(blk.a, blk.a + blk.size):
                matched.add(x)
        trailing = 0
        for k in range(len(a) - 1, -1, -1):
            if k in matched:
                break
            trailing += 1
        if ratio < args.min_ratio or trailing >= 2 or len(b) < len(a) - 2:
            flagged.append((i, ratio, trailing, len(a), len(b), s, heard_raw.strip()))

    if flagged:
        out("")
        out(f"⚠⚠ {len(flagged)} sentence(s) flagged — possible drop/truncation/misread:")
        for i, r, tm, la, lb, s, h in flagged:
            out(f"  [句{i:03d}] ratio={r:.2f} trailing_missing={tm} chars script={la}/heard={lb}")
            out(f"     script: {s}")
            out(f"     heard : {h}")
        out("")
        out("  → 复查这些句 audio/NNN_*.wav；要重合成：删该 WAV → build_video --skip 其它步骤重跑 TTS+narration+chars。")
    else:
        out(f"✅ TTS coverage OK — {len(sents)} sentences, no drops/truncation flagged.")

    (ep / "_tts_check_zh.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    if args.strict and flagged:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
