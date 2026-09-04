# -*- coding: utf-8 -*-
"""Build 全片_chars.json (per-char karaoke timing) for an SNC easy-monologue episode.

This is the SNC trilingual analog of the SNE single-color karaoke step. Where SNE uses
build_karaoke_ass.py (English words), SNC needs the per-CHARACTER timing that the
subtitle-burn build_ass.py three-layer renderer consumes (中文逐字 + 拼音 + 英文).

Approach — ONE sentence = ONE short WAV = ONE cue (zero drift):
  for each sentence i:
    whisper_chars = transcribe_segment(wav_i, zh)        # per-char whisper timing
    target        = clean_chars(sentence text)           # canonical chars (no punct)
    local_times   = align_segment(target, whisper_chars) # align script chars → whisper
    global_times  = local_times offset by timeline.json starts[i]   # gap-aware clock
  then build a cue over the FULL sentence text (punctuation inherits its neighbour's
  time, exactly like build_srt_v2), and glue each cue's end to the next cue's start.

Reuses build_srt_v2's transcribe_segment / align_segment / clean_chars / is_clean_char
(imported, not reimplemented) so the char-timing logic stays identical to the long-video
pipeline. Whisper offsets come from timeline.json (which includes the inter-sentence
gaps build_narration.py inserts), NOT from naive duration accumulation.

Reads  <ep>/script_sentences.txt   (小悦：<sentence> per line)
       <ep>/timeline.json          (starts[] / durs[] — gap-aware clock)
       <ep>/audio/*.wav            (one short WAV per sentence)
Writes <ep>/全片_chars.json        ({cues:[{idx,speaker,text,start,end,chars:[...]}]})

Usage:
  python build_trilingual_chars.py --episode-dir "g:/.../长视频/0606 我的早晨"
"""
import argparse
import json
import sys
from pathlib import Path

# Reuse the long-video char-alignment logic verbatim.
sys.path.insert(0, r"g:/youtube workspace/skills/srt-from-segments/scripts")
from build_srt_v2 import (  # noqa: E402
    setup_cuda_dll_paths, transcribe_segment, align_segment,
    clean_chars, is_clean_char, split_speaker,
)


def build(ep: Path, model_name: str, device: str, force: bool):
    out = ep / "全片_chars.json"
    if out.exists() and not force:
        print(f"cache exists: {out.name} — pass --force to redo", flush=True)
        return

    timeline = json.loads((ep / "timeline.json").read_text(encoding="utf-8"))
    starts = timeline["starts"]
    durs = timeline["durs"]

    lines = [l.strip() for l in (ep / "script_sentences.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    wavs = sorted((ep / "audio").glob("*.wav"))
    assert len(wavs) == len(lines) == len(starts), \
        f"{len(wavs)} wavs vs {len(lines)} lines vs {len(starts)} timeline starts"

    print(f"[1/3] load whisper ({model_name}, {device})", flush=True)
    if device == "cuda":
        setup_cuda_dll_paths()
    from faster_whisper import WhisperModel
    compute = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute)
    except Exception as e:
        print(f"  {device} failed ({e}); falling back to cpu int8", flush=True)
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    print(f"[2/3] transcribe + align {len(wavs)} sentences", flush=True)
    cues = []
    for i, (wav, line, off) in enumerate(zip(wavs, lines, starts)):
        speaker, text = split_speaker(line)
        target = clean_chars(text)                    # canonical chars (no punct/space)
        whisper_chars = transcribe_segment(model, str(wav))
        local = align_segment(target, whisper_chars)  # [(s,e)] per clean char
        # offset onto the gap-aware global clock
        gtimes = [(s + off, e + off) for s, e in local]
        if not gtimes:
            # silence / no recognizable chars — pin to the sentence's audio span
            gtimes = [(off, off + durs[i])]

        # Build per-char records over the FULL text; clean chars consume gtimes in order,
        # punctuation inherits the previous clean char's end time.
        char_recs = []
        ci = 0
        last = None
        first = None
        for c in text:
            if is_clean_char(c):
                t_s, t_e = gtimes[min(ci, len(gtimes) - 1)]
                ci += 1
                char_recs.append({"c": c, "start": t_s, "end": t_e, "kind": "char"})
                last = (t_s, t_e)
                if first is None:
                    first = (t_s, t_e)
            else:
                t = last[1] if last else 0.0
                char_recs.append({"c": c, "start": t, "end": t, "kind": "punct"})
        # backfill leading punctuation with the first clean char's start
        if first is not None:
            for rec in char_recs:
                if rec["kind"] == "punct" and rec["start"] == 0.0:
                    rec["start"] = rec["end"] = first[0]
                else:
                    break

        cue_start = first[0] if first else off
        cue_end = last[1] if last else off + durs[i]
        if cue_end <= cue_start:
            cue_end = cue_start + 0.5
        cues.append({"speaker": speaker, "text": text, "start": cue_start,
                     "end": cue_end, "chars": char_recs})
        if (i + 1) % 20 == 0 or i + 1 == len(wavs):
            print(f"  [{i+1}/{len(wavs)}]", flush=True)

    # glue each cue's end to the next cue's start (no subtitle black gap across the
    # inter-sentence silence) — same post-process as build_srt_v2
    for i in range(len(cues) - 1):
        cues[i]["end"] = max(cues[i + 1]["start"], cues[i]["start"] + 0.1)

    payload = {"cues": [
        {"idx": i + 1, "speaker": c["speaker"], "text": c["text"],
         "start": round(c["start"], 3), "end": round(c["end"], 3),
         "chars": [{"c": r["c"], "start": round(r["start"], 3),
                    "end": round(r["end"], 3), "kind": r["kind"]} for r in c["chars"]]}
        for i, c in enumerate(cues)]}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[3/3] wrote {out.name} ({len(cues)} cues, total {timeline['total']:.1f}s)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True)
    ap.add_argument("--model", default="large-v2")
    ap.add_argument("--device", default="cuda", choices=["cpu", "cuda"])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    build(Path(args.episode_dir), args.model, args.device, args.force)


if __name__ == "__main__":
    main()
