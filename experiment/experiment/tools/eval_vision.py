#runs the build check over labeled test photos and prints accuracy and a confusion summary per model
#folder layout: <folder>/correct/*.jpg  <folder>/near_miss/*.jpg  <folder>/wrong/*.jpg
#usage: python tools/eval_vision.py test_photos [--models gpt-4.1 gpt-5:low] [--reference ref.jpg | --no-reference]
#                                   [--repeat 2] [--out results.json]
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config
import vision

LABELS = ["correct", "near_miss", "wrong"]
IMAGE_EXT = (".jpg", ".jpeg", ".png")


def parse_model(spec):
    name, _, effort = spec.partition(":")
    return name, (effort or None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--models", nargs="+",
                        default=[m if not e else f"{m}:{e}" for m, e in config.VISION_CANDIDATES],
                        help="model or model:reasoning_effort")
    ref = parser.add_mutually_exclusive_group()
    ref.add_argument("--reference", default=config.REFERENCE_PHOTO_PATH)
    ref.add_argument("--no-reference", action="store_true")
    parser.add_argument("--repeat", type=int, default=1, help="runs per image, to see how consistent a model is")
    parser.add_argument("--out", default=os.path.join(config.TMP_DIR, "eval_vision_results.json"))
    args = parser.parse_args()

    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(config.DOTENV_PATH)
    client = OpenAI()

    schema = vision.load_schema()
    target = vision.load_target(schema=schema)
    reference = None if args.no_reference or not args.reference else vision.preprocess_image(args.reference)

    images = []
    for label in LABELS:
        folder = os.path.join(args.folder, label)
        if os.path.isdir(folder):
            images += [(label, os.path.join(folder, f)) for f in sorted(os.listdir(folder))
                       if f.lower().endswith(IMAGE_EXT)]
    if not images:
        print(f"No images found under {args.folder}/{{{','.join(LABELS)}}}/")
        return 1
    print(f"{len(images)} images, reference photo: {'yes' if reference else 'no'}, repeat: {args.repeat}")

    all_results = []
    summaries = []
    for spec in args.models:
        model, effort = parse_model(spec)
        print(f"\n===== {spec} =====")
        confusion = {label: {"match": 0, "no_match": 0, "error": 0} for label in LABELS}
        latencies = []
        flips = 0
        for label, path in images:
            preds = []
            for r in range(args.repeat):
                jpeg = vision.preprocess_image(path)
                t0 = time.perf_counter()
                try:
                    obs, info = vision.extract_build(client, jpeg, model=model, reasoning_effort=effort,
                                                     reference_jpeg=reference, schema=schema)
                    diff = vision.compare_build(obs, target)
                    pred = "match" if diff["match"] else "no_match"
                    detail = diff["counts"]
                    record = {"observation": obs, "diff": vision.diff_for_log(diff)}
                except Exception as e:
                    pred, detail, record = "error", str(e)[:120], {"error": repr(e)}
                latencies.append(time.perf_counter() - t0)
                confusion[label][pred] += 1
                preds.append(pred)
                ok = (pred == "match") == (label == "correct") and pred != "error"
                print(f"  [{'ok ' if ok else 'BAD'}] {label:<9} {os.path.basename(path):<28} -> {pred:<8} {detail}")
                all_results.append({"model": spec, "label": label, "image": path, "run": r, "pred": pred, **record})
            if len(set(preds)) > 1:
                flips += 1

        total = sum(sum(row.values()) for row in confusion.values())
        right = confusion["correct"]["match"] + confusion["near_miss"]["no_match"] + confusion["wrong"]["no_match"]
        false_match = confusion["near_miss"]["match"] + confusion["wrong"]["match"]
        print(f"\n  confusion (rows = true label):")
        print(f"  {'':<10} {'match':>7} {'no_match':>9} {'error':>6}")
        for label in LABELS:
            row = confusion[label]
            print(f"  {label:<10} {row['match']:>7} {row['no_match']:>9} {row['error']:>6}")
        accuracy = right / total if total else 0.0
        print(f"  accuracy {accuracy:.1%} ({right}/{total}), false 'match' (would end a session early): {false_match}, "
              f"missed correct builds: {confusion['correct']['no_match']}")
        if args.repeat > 1:
            print(f"  images with inconsistent predictions across repeats: {flips}/{len(images)}")
        if latencies:
            print(f"  mean latency {sum(latencies) / len(latencies):.2f}s, max {max(latencies):.2f}s")
        summaries.append((spec, accuracy, false_match, confusion["correct"]["no_match"]))

    print("\n===== summary =====")
    for spec, acc, fm, missed in sorted(summaries, key=lambda s: (-s[1], s[2])):
        print(f"  {spec:<20} accuracy {acc:.1%}  false matches {fm}  missed correct {missed}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=1)
    print(f"\nPer-image outputs written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
