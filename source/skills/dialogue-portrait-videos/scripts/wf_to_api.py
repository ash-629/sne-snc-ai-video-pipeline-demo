"""Convert ComfyUI editor-format workflow JSON to API-format JSON.

Two ways to use it:
  - As a library:  from wf_to_api import editor_to_api;  api = editor_to_api(editor_dict, obj_info_dict)
  - As a CLI:      python wf_to_api.py <editor.json> <object_info.json> <out.json>

Handles:
- Mode 0 (active): kept as-is.
- Mode 2 (muted): node dropped entirely, any link to it is dropped (downstream input becomes missing).
- Mode 4 (bypassed): node dropped, but for each output we find an input on the same node
  with the matching type and forward the link to that input's source. If no matching input,
  the link is dropped.
- Reroute / PrimitiveNode / Note nodes: skipped (transparent in execution).

Widget value extraction: walks required+optional input spec in declaration order,
consuming widgets_values for non-link inputs. Combos are declared either as a list of
options (older ComfyUI) OR the string "COMBO" (newer ComfyUI) -- both are widgets.
Any scalar-ish custom string type that is NOT a known link type is also treated as a
widget (covers nodes like `Int.Number`). LINK_TYPES below is the allow-list of types that
travel over links (never consume a widgets_values slot).
"""
import json
import sys

# Types that flow over links (NOT widgets). Anything else scalar-ish is a widget value.
LINK_TYPES = {
    "MODEL", "CLIP", "VAE", "CONDITIONING", "LATENT", "IMAGE", "MASK",
    "CLIP_VISION", "CLIP_VISION_OUTPUT", "CONTROL_NET", "STYLE_MODEL", "UPSCALE_MODEL",
    "NOISE", "SAMPLER", "SIGMAS", "GUIDER", "AUDIO", "GEMMA",
    "WANVIDEOMODEL", "WANVAE",
}

TRANSPARENT_TYPES = {"Reroute", "PrimitiveNode", "Note", "MarkdownNote", "easy showAnything"}


def editor_to_api(editor, obj_info):
    """Convert an editor-format workflow dict to an API-format prompt dict.

    Bypass (mode=4) nodes must already be marked in `editor` if you want them skipped;
    this function honors mode 2/4 the same as ComfyUI's graphToPrompt.
    Returns {node_id_str: {"class_type", "inputs", "_meta"}}.
    """
    links_tbl = {}
    for l in editor.get("links", []):
        # [id, src_node, src_slot, dst_node, dst_slot, type]
        links_tbl[l[0]] = (l[1], l[2], l[5])

    nodes_by_id = {n["id"]: n for n in editor["nodes"]}

    def is_kept(node):
        if node["type"] in TRANSPARENT_TYPES:
            return False
        if node.get("mode", 0) in (2, 4):
            return False
        if node["type"] not in obj_info:
            return False
        return True

    def resolve_link(src_node_id, src_slot, type_):
        """Follow re-route/bypass chain to a kept source. Returns (node_id, slot) or None."""
        visited = set()
        cur_node_id, cur_slot = src_node_id, src_slot
        while True:
            if cur_node_id in visited:
                return None
            visited.add(cur_node_id)
            node = nodes_by_id.get(cur_node_id)
            if node is None:
                return None
            if is_kept(node):
                return (cur_node_id, cur_slot)
            if node["type"] == "Reroute":
                inp = (node.get("inputs") or [None])[0]
                if inp is None or inp.get("link") is None:
                    return None
                l = links_tbl[inp["link"]]
                cur_node_id, cur_slot = l[0], l[1]
                continue
            if node["type"] == "PrimitiveNode":
                return None  # downstream falls back to widget default
            if node.get("mode") == 4:
                outs = node.get("outputs") or []
                inps = node.get("inputs") or []
                if cur_slot >= len(outs):
                    return None
                target_type = outs[cur_slot].get("type")
                matched_input = None
                for inp in inps:
                    if inp.get("type") == target_type:
                        matched_input = inp
                        break
                if matched_input is None or matched_input.get("link") is None:
                    return None
                l = links_tbl[matched_input["link"]]
                cur_node_id, cur_slot = l[0], l[1]
                continue
            return None  # mode 2 (muted) or unknown -> dead-end

    def widget_input_names(node_type):
        info = obj_info.get(node_type)
        if not info:
            return []
        out = []
        for group in ("required", "optional"):
            for name, spec in (info.get("input", {}).get(group, {}) or {}).items():
                if not spec:
                    continue
                type_def = spec[0]
                if isinstance(type_def, list) or type_def == "COMBO":
                    out.append(name)
                elif type_def in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                    out.append(name)
                    if name in ("seed", "noise_seed"):
                        out.append("__control_after_generate__")
                elif isinstance(type_def, str) and type_def not in LINK_TYPES:
                    # custom scalar-ish widget type (e.g. some nodes' string-typed combos)
                    out.append(name)
        return out

    api_prompt = {}
    for node in editor["nodes"]:
        if not is_kept(node):
            continue
        node_type = node["type"]
        node_id = str(node["id"])

        linked_inputs = {}
        for inp in node.get("inputs") or []:
            lid = inp.get("link")
            if lid is None or lid not in links_tbl:
                continue
            src_node, src_slot, link_type = links_tbl[lid]
            resolved = resolve_link(src_node, src_slot, link_type)
            if resolved is not None:
                linked_inputs[inp["name"]] = resolved

        widgets_values = node.get("widgets_values") or []
        widget_dict = widgets_values if isinstance(widgets_values, dict) else None

        api_inputs = {}
        spec_widget_names = widget_input_names(node_type)
        wi = 0
        for wname in spec_widget_names:
            if wname == "__control_after_generate__":
                wi += 1
                continue
            if wname in linked_inputs:
                src_node, src_slot = linked_inputs[wname]
                api_inputs[wname] = [str(src_node), src_slot]
                # linked widget still occupies a slot in array-form widgets_values
                if widget_dict is None and wi < len(widgets_values):
                    wi += 1
                continue
            if widget_dict is not None:
                if wname in widget_dict:
                    api_inputs[wname] = widget_dict[wname]
            else:
                if wi < len(widgets_values):
                    api_inputs[wname] = widgets_values[wi]
                    wi += 1

        # Add purely-link inputs (MODEL/CLIP/IMAGE/CONDITIONING/etc.)
        for name, (src_node, src_slot) in linked_inputs.items():
            if name not in api_inputs:
                api_inputs[name] = [str(src_node), src_slot]

        api_prompt[node_id] = {
            "class_type": node_type,
            "inputs": api_inputs,
            "_meta": {"title": node.get("title") or node_type},
        }

    # Drop any input referencing a node that's not in the final prompt
    kept_ids = set(api_prompt.keys())
    for nid, ndata in api_prompt.items():
        for iname, ival in list(ndata["inputs"].items()):
            if isinstance(ival, list) and len(ival) == 2 and isinstance(ival[0], str):
                if ival[0] not in kept_ids:
                    print(f"  drop input {iname} of #{nid} {ndata['class_type']} "
                          f"(refs missing node {ival[0]})", file=sys.stderr)
                    del ndata["inputs"][iname]

    return api_prompt


def main():
    editor = json.load(open(sys.argv[1], encoding="utf-8"))
    obj_info = json.load(open(sys.argv[2], encoding="utf-8"))
    api = editor_to_api(editor, obj_info)
    json.dump(api, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {sys.argv[3]}: {len(api)} nodes")


if __name__ == "__main__":
    main()
