"""Batch-generate Wan2.2 talking-head clips from dialogue portraits via ComfyUI.

For each portrait, submits N jobs to a local ComfyUI instance (default
127.0.0.1:8188) running a Wan2.2 First/Last-Frame-to-Video workflow with
identical first and last frame (= the portrait), so the model only animates
natural idle-speech motion. Each output mp4 is moved to a target folder named
after the portrait, numbered sequentially.

Channel-agnostic: portrait list, output naming and workflow config all come
from a JSON config. The Wan workflow itself is referenced by path so users
can swap in their own variant.

See SKILL.md for the config schema.
"""
import argparse
import io
import json
import os
import random
import shutil
import sys
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)


def submit(api_base, wf, retries=4):
    body = json.dumps({"prompt": wf, "client_id": str(uuid.uuid4())}).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{api_base}/prompt", data=body,
            headers={"Content-Type": "application/json"}
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            return json.loads(resp.read())["prompt_id"]
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace")[:1000]
            print(f"  HTTP {e.code}: {msg}", file=sys.stderr)
            return None  # node errors don't retry
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            last_err = e
            wait = 5 * (attempt + 1)
            print(f"  connection error (attempt {attempt+1}/{retries}): {e}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    print(f"  give up after {retries} attempts: {last_err}", file=sys.stderr)
    return None


def wait_for(api_base, prompt_id, timeout=1800, poll_interval=8):
    """Poll /history. Return (ok, file_info_dict_or_None)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{api_base}/history/{prompt_id}", timeout=10) as r:
                h = json.loads(r.read())
            if prompt_id in h:
                entry = h[prompt_id]
                ok = entry["status"]["status_str"] == "success"
                if ok:
                    for out in entry.get("outputs", {}).values():
                        for f in out.get("gifs", []) + out.get("images", []) + out.get("videos", []):
                            if str(f.get("filename", "")).endswith((".mp4", ".webm", ".mov")):
                                return True, f
                return ok, None
        except Exception as e:
            print(f"  poll error: {e}", file=sys.stderr)
        time.sleep(poll_interval)
    return False, None


def resolve_path(p, base):
    pp = Path(p)
    return pp if pp.is_absolute() else (base / pp).resolve()


def stage_image(src_path, comfy_input_dir, stage_prefix):
    """Copy portrait into ComfyUI input dir with a unique prefixed name. Returns name only."""
    name = f"{stage_prefix}{Path(src_path).name}"
    dst = comfy_input_dir / name
    if not dst.exists() or dst.stat().st_size != src_path.stat().st_size:
        shutil.copy2(str(src_path), str(dst))
    return name


def build_workflow(template, overrides):
    """Deep-copy template and apply overrides ({node_id: {input_name: value}})."""
    wf = json.loads(json.dumps(template))
    for nid, inputs in overrides.items():
        if nid not in wf:
            raise SystemExit(f"node id {nid!r} not found in workflow")
        for iname, ival in inputs.items():
            wf[nid]["inputs"][iname] = ival
    return wf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip clips whose target file already exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned jobs without submitting")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N clips (for testing)")
    parser.add_argument("--api-base", default=None, help="Override comfyui_api_base from config")
    args = parser.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = cfg_path.parent

    api_base = args.api_base or cfg.get("comfyui_api_base", "http://127.0.0.1:8188")
    comfy_input = Path(cfg.get("comfyui_input_dir", "I:/AI/ComfyUI/input"))
    comfy_output = Path(cfg.get("comfyui_output_dir", "I:/AI/ComfyUI/output"))
    stage_prefix = cfg.get("input_stage_prefix", "snc_") if "snc" in cfg_path.name.lower() else cfg.get("input_stage_prefix", "sne_")

    wf_path = resolve_path(cfg["api_workflow_path"], base)
    wf_template = json.loads(wf_path.read_text(encoding="utf-8"))

    image_node_ids = cfg["image_node_ids"]          # e.g. ["68", "62"] (first & last frame LoadImages)
    prompt_node_id = cfg["prompt_node_id"]          # e.g. "172"
    prompt_text = cfg["prompt_text"]
    seed_node_id = cfg["seed_node_id"]              # e.g. "57"
    seed_input = cfg.get("seed_input_name", "noise_seed")
    output_node_id = cfg["output_node_id"]          # e.g. "111"
    output_prefix_input = cfg.get("output_prefix_input_name", "filename_prefix")
    output_prefix_template = cfg.get(
        "output_filename_prefix_template",
        "dpv_batch/{folder}_{idx:03d}",
    )

    target_root = resolve_path(cfg["target_root"], base)
    portraits = cfg["portraits"]

    # Apply any static overrides (e.g., resolution sliders)
    static_overrides = cfg.get("static_overrides", {})

    # Flatten to per-clip jobs
    jobs = []
    for p in portraits:
        portrait_path = resolve_path(p["image_path"], base)
        if not portrait_path.exists():
            print(f"WARN: portrait not found: {portrait_path}", file=sys.stderr)
            continue
        folder_name = p["folder_name"]
        count = p.get("count", 10)
        start_idx = p.get("start_index", 1)
        target_dir = target_root / folder_name
        for i in range(count):
            idx = start_idx + i
            target_path = target_dir / f"{idx:03d}.mp4"
            if args.skip_existing and target_path.exists():
                continue
            jobs.append({
                "portrait_path": portrait_path,
                "folder_name": folder_name,
                "target_path": target_path,
                "idx": idx,
            })

    if args.limit:
        jobs = jobs[: args.limit]

    print(f"\n=== {len(jobs)} clip(s) to generate ===\n", flush=True)

    if args.dry_run:
        for j in jobs:
            print(f"  {j['portrait_path'].name} → {j['target_path']}")
        return

    if not jobs:
        return

    comfy_input.mkdir(parents=True, exist_ok=True)

    for i, j in enumerate(jobs, 1):
        j["target_path"].parent.mkdir(parents=True, exist_ok=True)
        image_name = stage_image(j["portrait_path"], comfy_input, stage_prefix)
        seed = random.randint(1, 2**31 - 1)
        out_prefix = output_prefix_template.format(folder=j["folder_name"], idx=j["idx"])

        overrides = dict(static_overrides)
        for nid in image_node_ids:
            overrides.setdefault(nid, {}).update({"image": image_name})
        overrides.setdefault(prompt_node_id, {}).update({"text": prompt_text})
        overrides.setdefault(seed_node_id, {}).update({seed_input: seed})
        overrides.setdefault(output_node_id, {}).update({output_prefix_input: out_prefix})

        wf = build_workflow(wf_template, overrides)

        print(f"[{i}/{len(jobs)}] submit {image_name} → {j['target_path'].parent.name}/{j['target_path'].name} (seed={seed})", flush=True)
        pid = submit(api_base, wf)
        if not pid:
            print(f"  ✗ submit failed", flush=True)
            continue
        print(f"  prompt_id={pid}, waiting...", flush=True)
        t0 = time.time()
        ok, file_info = wait_for(api_base, pid)
        elapsed = time.time() - t0
        if not ok or not file_info:
            print(f"  ✗ FAILED after {elapsed:.0f}s", flush=True)
            continue
        src = comfy_output / file_info.get("subfolder", "") / file_info["filename"]
        if not src.exists():
            print(f"  ✗ output not found at {src}", flush=True)
            continue
        shutil.move(str(src), str(j["target_path"]))
        size_kb = j["target_path"].stat().st_size // 1024
        print(f"  ✓ {elapsed:.0f}s → {j['target_path'].name} ({size_kb} KB)", flush=True)


if __name__ == "__main__":
    main()
