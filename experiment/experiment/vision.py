#build check: preprocess the camera image, have a vision model describe the build as structured JSON,
#compare that to the target JSON in code, and turn the diff into text the dialogue model can phrase.
#the vision model is never asked "does this match"
import base64
import io
import json
import time

import config

COLORS_UNKNOWN = "unknown"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_schema(path=config.STRUCTURE_SCHEMA_PATH):
    return load_json(path)


#raises ValueError with a readable message if the target file is malformed
def load_target(path=config.TARGET_STRUCTURE_PATH, schema=None):
    schema = schema or load_schema()
    data = load_json(path)
    item = schema["schema"]["properties"]["blocks"]["items"]["properties"]
    colors = set(item["color"]["enum"]) - {COLORS_UNKNOWN}
    types = set(item["type"]["enum"]) - {COLORS_UNKNOWN}
    seen = set()
    for i, b in enumerate(data.get("blocks", [])):
        where = f"target block {i} ({b.get('id')})"
        for field in ("id", "color", "type", "orientation", "x", "y", "layer", "front_visible"):
            if b.get(field) is None:
                raise ValueError(f"{where}: missing {field}")
        if b["id"] in seen:
            raise ValueError(f"{where}: duplicate id")
        seen.add(b["id"])
        if b["color"] not in colors:
            raise ValueError(f"{where}: color {b['color']!r} not in schema enum {sorted(colors)}")
        if b["type"] not in types:
            raise ValueError(f"{where}: type {b['type']!r} not in schema enum {sorted(types)}")
        if b["orientation"] not in (0, 90):
            raise ValueError(f"{where}: orientation must be 0 or 90")
        if b["type"] == "2x2" and b["orientation"] != 0:
            raise ValueError(f"{where}: 2x2 blocks always use orientation 0")
    if not data.get("blocks"):
        raise ValueError("target has no blocks")
    return data


#checks the vision model's output against the schema rules the API cannot enforce; returns a list of problems
def validate_observation(obs, schema=None):
    schema = schema or load_schema()
    item = schema["schema"]["properties"]["blocks"]["items"]["properties"]
    problems = []
    if not isinstance(obs, dict) or not isinstance(obs.get("blocks"), list):
        return ["output has no blocks list"]
    for i, b in enumerate(obs["blocks"]):
        if b.get("color") not in item["color"]["enum"]:
            problems.append(f"block {i}: bad color {b.get('color')!r}")
        if b.get("type") not in item["type"]["enum"]:
            problems.append(f"block {i}: bad type {b.get('type')!r}")
        if b.get("orientation") not in (0, 90, None):
            problems.append(f"block {i}: bad orientation {b.get('orientation')!r}")
        if not isinstance(b.get("layer"), int) or b["layer"] < 0:
            problems.append(f"block {i}: bad layer {b.get('layer')!r}")
        if b.get("visibility") not in item["visibility"]["enum"]:
            problems.append(f"block {i}: bad visibility {b.get('visibility')!r}")
    return problems


#resizes so the longest side is about IMAGE_MAX_SIDE px and re-encodes as JPEG. accepts a path, bytes or PIL image
def preprocess_image(source, max_side=config.IMAGE_MAX_SIDE, quality=config.IMAGE_JPEG_QUALITY):
    from PIL import Image, ImageOps
    if isinstance(source, Image.Image):
        image = source
    elif isinstance(source, (bytes, bytearray)):
        image = Image.open(io.BytesIO(source))
    else:
        image = Image.open(source)
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _data_url(jpeg_bytes):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")


#asks the vision model for the structured description. returns (observation dict, info dict for the log)
def extract_build(client, jpeg_bytes, model=config.VISION_MODEL, reasoning_effort=config.VISION_REASONING_EFFORT,
                  reference_jpeg=None, schema=None, prompt_path=config.VISION_PROMPT_PATH,
                  retries=config.VISION_RETRIES):
    schema = schema or load_schema()
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_text = f.read().strip()

    content = []
    if reference_jpeg is not None:
        content.append({"type": "text", "text": (
            "Reference photo of the finished target structure, from the same camera. Use it only to learn "
            "what the blocks and colors look like in this lighting. The current build may be incomplete or "
            "different. Describe only the second photo.")})
        content.append({"type": "image_url", "image_url": {"url": _data_url(reference_jpeg), "detail": "high"}})
    content.append({"type": "text", "text": "Photo of the current build:"})
    content.append({"type": "image_url", "image_url": {"url": _data_url(jpeg_bytes), "detail": "high"}})

    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system_text}, {"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    errors = []
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            response = client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content
            obs = json.loads(raw)
            problems = validate_observation(obs, schema)
            if problems:
                raise ValueError("; ".join(problems))
            return obs, {"model": model, "attempts": attempt + 1, "latency_s": round(time.perf_counter() - t0, 4),
                         "raw": raw, "errors": errors, "with_reference": reference_jpeg is not None}
        except Exception as e:
            errors.append(f"attempt {attempt + 1}: {e}")
    raise RuntimeError("vision extraction failed: " + " | ".join(errors))


def _key(b):
    return (b["color"], b["type"], b["orientation"], b["layer"])


def _positioned(b):
    return (b.get("visibility") != "not_visible" and b.get("x") is not None and b.get("y") is not None
            and b.get("color") != COLORS_UNKNOWN and b.get("type") != COLORS_UNKNOWN
            and b.get("orientation") is not None)


def _match_with_shift(observed, targets, dx, dy):
    used = set()
    pairs = []
    for oi, o in enumerate(observed):
        for t in targets:
            if t["id"] in used or _key(t) != _key(o):
                continue
            if t["x"] == o["x"] + dx and t["y"] == o["y"] + dy:
                used.add(t["id"])
                pairs.append((oi, t["id"]))
                break
    return pairs


#compares an observation to the target. exact on color, type, orientation and layer; x/y exact after the
#single whole-structure shift that matches the most blocks (ties -> smallest shift, flagged as ambiguous)
def compare_build(observation, target):
    targets = target["blocks"]
    by_id = {t["id"]: t for t in targets}
    observed = [b for b in observation["blocks"] if _positioned(b)]
    unverifiable = [b for b in observation["blocks"] if not _positioned(b)]

    shifts = {(0, 0)}
    for o in observed:
        for t in targets:
            if _key(t) == _key(o):
                shifts.add((t["x"] - o["x"], t["y"] - o["y"]))
    scored = []
    for dx, dy in shifts:
        pairs = _match_with_shift(observed, targets, dx, dy)
        scored.append((len(pairs), -(abs(dx) + abs(dy)), (dx, dy), pairs))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    best_count, _, shift, pairs = scored[0]
    ambiguous = best_count > 0 and sum(1 for s in scored if s[0] == best_count) > 1

    matched_obs = {oi for oi, _ in pairs}
    matched_ids = {tid for _, tid in pairs}
    dx, dy = shift

    #pair each unmatched observed block with the nearest unmatched target block of the same color and type
    wrong = []
    claimed = set()
    for oi, o in enumerate(observed):
        if oi in matched_obs:
            continue
        candidates = [t for t in targets if t["id"] not in matched_ids and t["id"] not in claimed
                      and t["color"] == o["color"] and t["type"] == o["type"]]
        if candidates:
            t = min(candidates, key=lambda t: (abs(t["layer"] - o["layer"]),
                                               abs(t["x"] - o["x"] - dx) + abs(t["y"] - o["y"] - dy)))
            claimed.add(t["id"])
            issues = {}
            if t["layer"] != o["layer"]:
                issues["layer"] = t["layer"] - o["layer"]
            if t["orientation"] != o["orientation"]:
                issues["rotate"] = True
            if best_count > 0:
                move = (t["x"] - o["x"] - dx, t["y"] - o["y"] - dy)
                if move != (0, 0):
                    issues["move"] = move
            wrong.append({"observed": o, "target_id": t["id"], "issues": issues})
        else:
            wrong.append({"observed": o, "target_id": None, "issues": {"extra": True}})

    unmatched = [t for t in targets if t["id"] not in matched_ids and t["id"] not in claimed]
    missing = [t["id"] for t in unmatched if t["front_visible"]]
    hidden_unconfirmed = [t["id"] for t in unmatched if not t["front_visible"]]
    required = [t["id"] for t in targets if t["front_visible"]]
    match = not wrong and all(tid in matched_ids for tid in required)

    return {
        "match": match,
        "shift": [dx, dy],
        "alignment_ambiguous": ambiguous,
        "no_anchor": best_count == 0 and bool(observed),
        "correct": sorted(matched_ids),
        "wrong": wrong,
        "missing": missing,
        "hidden_unconfirmed": hidden_unconfirmed,
        "unverifiable_count": len(unverifiable),
        "counts": {"target": len(targets), "correct": len(matched_ids), "wrong": len(wrong),
                   "missing": len(missing), "hidden_unconfirmed": len(hidden_unconfirmed),
                   "unverifiable": len(unverifiable)},
        "_target_by_id": by_id,
    }


def _layer_name(layer):
    return "the bottom layer" if layer == 0 else f"layer {layer + 1}"


def _block_name(b):
    return f"{b['color']} {b['type']} block on {_layer_name(b['layer'])}"


#turns a camera-frame stud offset into words from the participant's point of view
def _direction_words(move, participant_side=config.PARTICIPANT_SIDE):
    mx, my = move
    facing = participant_side == "facing"
    parts = []
    if mx:
        right = (mx > 0) != facing
        parts.append(f"{abs(mx)} stud{'s' if abs(mx) != 1 else ''} to the participant's {'right' if right else 'left'}")
    if my:
        away = (my > 0) != facing
        parts.append(f"{abs(my)} stud{'s' if abs(my) != 1 else ''} {'away from' if away else 'toward'} the participant")
    return " and ".join(parts)


#text sent to the dialogue model; it may only phrase what is in here
def describe_diff(diff, participant_side=config.PARTICIPANT_SIDE):
    by_id = diff["_target_by_id"]
    lines = ["[BUILD CHECK RESULT]"]
    lines.append("The build is complete and correct." if diff["match"] else "The build is not complete yet.")
    if diff["correct"]:
        lines.append("Correct so far: " + "; ".join(_block_name(by_id[t]) for t in diff["correct"]) + ".")
    else:
        lines.append("Correct so far: none.")
    for w in diff["wrong"]:
        o, issues = w["observed"], w["issues"]
        if issues.get("extra"):
            lines.append(f"Not part of the design, should be removed: the {_block_name(o)}.")
            continue
        fixes = []
        if "layer" in issues:
            fixes.append(f"it belongs on {_layer_name(o['layer'] + issues['layer'])}")
        if issues.get("rotate"):
            fixes.append("it should be turned a quarter turn")
        if "move" in issues:
            fixes.append("it should move " + _direction_words(issues["move"], participant_side))
        if diff["no_anchor"] and not fixes:
            fixes.append("its position does not fit the design")
        lines.append(f"Needs fixing: the {_block_name(o)}: " + ", and ".join(fixes) + ".")
    if diff["missing"]:
        lines.append("Not placed yet (not mistakes): " + "; ".join(_block_name(by_id[t]) for t in diff["missing"]) + ".")
    if diff["hidden_unconfirmed"]:
        lines.append(f"{len(diff['hidden_unconfirmed'])} block(s) of the design cannot be seen from the camera.")
    if diff["unverifiable_count"]:
        lines.append(f"{diff['unverifiable_count']} block(s) could not be seen clearly.")
    if diff["alignment_ambiguous"]:
        lines.append("The position check was uncertain this time.")
    return "\n".join(lines)


#log-friendly copy of a diff (drops the internal lookup table)
def diff_for_log(diff):
    return {k: v for k, v in diff.items() if not k.startswith("_")}
