#verifies the candidate models against the API and benchmarks latency on THIS network
#usage: python tools/bench_models.py [--trials 10] [--skip-tts] [--skip-vision] [--skip-stt]
#  LLM:    streaming, time to first token, and compliance with "line 1 = expression, rest = speech"
#  vision: image input + json_schema structured output work (accuracy is tools/eval_vision.py's job)
#  TTS:    time to first audio byte, tts-1 vs gpt-4o-mini-tts (voice from config)
#  STT:    the transcription models exist and their latency on a short clip
import argparse
import io
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config
from dialogue import ReplyStreamParser, build_system_prompt

#a short scripted exchange so every trial sends a realistic history
SCRIPT = [
    "[SESSION START] The greeting has already been said. Give the first build step.",
    "Okay, done. What's next?",
    "Wait, which way should the long block point?",
    "Are you a robot or is somebody controlling you?",
    "I put it on. Next one?",
]


def median(values):
    return statistics.median(values) if values else None


def p90(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def check_exists(client, model):
    try:
        client.models.retrieve(model)
        return True, ""
    except Exception as e:
        return False, str(e)[:160]


def bench_llm(client, model, effort, trials, system_prompt):
    ttft, first_sentence, compliant, problems = [], [], 0, []
    for trial in range(trials):
        history = [{"role": "system", "content": system_prompt}]
        #alternate which point of the script is measured, with the earlier turns as fake history
        upto = trial % len(SCRIPT)
        for i in range(upto):
            history += [{"role": "user", "content": SCRIPT[i]},
                        {"role": "assistant", "content": "nod\nGreat, keep going with the next block."}]
        history.append({"role": "user", "content": SCRIPT[upto]})
        kwargs = {"model": model, "messages": history, "stream": True}
        if effort:
            kwargs["reasoning_effort"] = effort
            kwargs["max_completion_tokens"] = config.LLM_MAX_COMPLETION_TOKENS + 1000
        else:
            kwargs["max_completion_tokens"] = config.LLM_MAX_COMPLETION_TOKENS
        parser = ReplyStreamParser()
        sentences = []
        raw = ""
        t0 = time.perf_counter()
        t_first = t_sentence = None
        try:
            for chunk in client.chat.completions.create(**kwargs):
                if not chunk.choices or not chunk.choices[0].delta.content:
                    continue
                delta = chunk.choices[0].delta.content
                raw += delta
                if t_first is None:
                    t_first = time.perf_counter() - t0
                for kind, value in parser.feed(delta):
                    if kind == "sentence":
                        sentences.append(value)
                        if t_sentence is None:
                            t_sentence = time.perf_counter() - t0
            for kind, value in parser.finish():
                if kind == "sentence":
                    sentences.append(value)
                    if t_sentence is None:
                        t_sentence = time.perf_counter() - t0
        except Exception as e:
            problems.append(f"trial {trial}: API error {e}")
            continue
        ok = parser.expression is not None and not parser.violations and 1 <= len(sentences) <= 3
        if ok:
            compliant += 1
        else:
            problems.append(f"trial {trial}: violations={parser.violations} sentences={len(sentences)} raw={raw[:80]!r}")
        if t_first is not None:
            ttft.append(t_first)
        if t_sentence is not None:
            first_sentence.append(t_sentence)
    return {"model": model, "reasoning_effort": effort, "trials": trials,
            "median_ttft_s": median(ttft), "p90_ttft_s": p90(ttft),
            "median_first_sentence_s": median(first_sentence),
            "compliance": compliant / trials if trials else 0.0, "problems": problems}


def test_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (640, 480), (230, 230, 230))
    draw = ImageDraw.Draw(image)
    draw.rectangle([200, 300, 440, 380], fill=(200, 20, 20))
    draw.rectangle([260, 220, 380, 300], fill=(240, 210, 20))
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    return buf.getvalue()


def bench_vision(client, model, effort):
    import vision
    t0 = time.perf_counter()
    try:
        obs, info = vision.extract_build(client, vision.preprocess_image(test_image()), model=model,
                                         reasoning_effort=effort, retries=0)
        return {"model": model, "reasoning_effort": effort, "image_input_and_json_schema": "ok",
                "latency_s": round(time.perf_counter() - t0, 3), "blocks_seen": len(obs["blocks"])}
    except Exception as e:
        return {"model": model, "reasoning_effort": effort, "image_input_and_json_schema": f"FAILED: {e}"}


def bench_tts(client, model, voice, trials, text):
    first, total, errors = [], [], []
    for _ in range(trials):
        t0 = time.perf_counter()
        t_first = None
        try:
            with client.audio.speech.with_streaming_response.create(
                    model=model, voice=voice, input=text, response_format=config.TTS_FORMAT) as response:
                for data in response.iter_bytes(4096):
                    if t_first is None and data:
                        t_first = time.perf_counter() - t0
        except Exception as e:
            errors.append(str(e)[:160])
            continue
        first.append(t_first)
        total.append(time.perf_counter() - t0)
    return {"model": model, "voice": voice, "median_first_audio_s": median(first), "p90_first_audio_s": p90(first),
            "median_total_s": median(total), "errors": errors}


def bench_stt(client, model, audio_path, trials):
    times, text, errors = [], None, []
    for _ in range(trials):
        t0 = time.perf_counter()
        try:
            with open(audio_path, "rb") as f:
                text = client.audio.transcriptions.create(model=model, file=f, language=config.TRANSCRIBE_LANGUAGE).text
            times.append(time.perf_counter() - t0)
        except Exception as e:
            errors.append(str(e)[:160])
    return {"model": model, "median_s": median(times), "text": text, "errors": errors}


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trials", type=int, default=10)
    arg_parser.add_argument("--skip-tts", action="store_true")
    arg_parser.add_argument("--skip-vision", action="store_true")
    arg_parser.add_argument("--skip-stt", action="store_true")
    arg_parser.add_argument("--out", default=os.path.join(config.TMP_DIR, "bench_models.json"))
    args = arg_parser.parse_args()

    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(config.DOTENV_PATH)
    client = OpenAI()
    results = {}

    print("== Model availability")
    names = ([m for m, _ in config.LLM_CANDIDATES] + [m for m, _ in config.VISION_CANDIDATES]
             + config.TTS_CANDIDATES + ["gpt-4o-mini-transcribe", "whisper-1"])
    results["available"] = {}
    for name in dict.fromkeys(names):
        ok, err = check_exists(client, name)
        results["available"][name] = ok or err
        print(f"  {name:<24} {'available' if ok else 'NOT AVAILABLE: ' + err}")

    print(f"\n== LLM streaming + format ({args.trials} trials each)")
    system_prompt, _ = build_system_prompt()
    llm = []
    for model, effort in config.LLM_CANDIDATES:
        r = bench_llm(client, model, effort, args.trials, system_prompt)
        llm.append(r)
        print(f"  {model:<14} effort={effort!s:<8} median TTFT {r['median_ttft_s']}s  p90 {r['p90_ttft_s']}s  "
              f"first sentence {r['median_first_sentence_s']}s  format compliance {r['compliance']:.0%}")
        for p in r["problems"][:5]:
            print(f"      {p}")
    results["llm"] = llm
    reliable = [r for r in llm if r["compliance"] >= 0.95 and r["median_ttft_s"] is not None]
    if reliable:
        reliable.sort(key=lambda r: r["median_ttft_s"])
        best = reliable[0]
        #tie (within 10%) goes to the non-reasoning model
        ties = [r for r in reliable if r["median_ttft_s"] <= best["median_ttft_s"] * 1.10]
        non_reasoning = [r for r in ties if not r["reasoning_effort"]]
        pick = non_reasoning[0] if non_reasoning else best
        results["llm_pick"] = pick["model"]
        print(f"  -> pick LLM_MODEL = {pick['model']!r}, LLM_REASONING_EFFORT = {pick['reasoning_effort']!r}")
    else:
        print("  -> no candidate followed the format reliably (>= 95%); look at the problems above")

    if not args.skip_vision:
        print("\n== Vision: image input + structured JSON output")
        results["vision"] = []
        for model, effort in config.VISION_CANDIDATES:
            r = bench_vision(client, model, effort)
            results["vision"].append(r)
            print(f"  {model:<14} effort={effort!s:<6} {r['image_input_and_json_schema']}  "
                  f"{r.get('latency_s', '')}")
        print("  (compare accuracy with tools/eval_vision.py on your labeled photos)")

    sample_audio = None
    if not args.skip_tts:
        text = "Great, now take the long blue block and lay it right next to the red one."
        print(f"\n== TTS time to first audio ({args.trials} trials each, voice {config.TTS_VOICE})")
        results["tts"] = []
        for model in config.TTS_CANDIDATES:
            r = bench_tts(client, model, config.TTS_VOICE, args.trials, text)
            results["tts"].append(r)
            print(f"  {model:<18} median first audio {r['median_first_audio_s']}s  p90 {r['p90_first_audio_s']}s  "
                  f"median total {r['median_total_s']}s  errors {len(r['errors'])}")
        base, alt = results["tts"][0], results["tts"][1] if len(results["tts"]) > 1 else None
        if alt and alt["median_first_audio_s"] is not None and base["median_first_audio_s"] is not None:
            keep = alt["median_first_audio_s"] > base["median_first_audio_s"]
            print(f"  -> {'keep ' + base['model'] if keep else 'switch to ' + alt['model'] + ' (not slower)'}")
        os.makedirs(config.TMP_DIR, exist_ok=True)
        sample_audio = os.path.join(config.TMP_DIR, "bench_sample.mp3")
        from speech import TTS
        TTS(client).synthesize(text, sample_audio)

    if not args.skip_stt and sample_audio:
        print("\n== Transcription latency (synthetic clip; real NAO mic audio will be noisier)")
        results["stt"] = []
        for model in ("gpt-4o-mini-transcribe", "whisper-1"):
            r = bench_stt(client, model, sample_audio, max(3, args.trials // 2))
            results["stt"].append(r)
            print(f"  {model:<24} median {r['median_s']}s  text {r['text']!r}  errors {len(r['errors'])}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"\nFull results: {args.out}")
    print("Update LLM_MODEL / LLM_REASONING_EFFORT / VISION_MODEL / TTS_MODEL in config.py with the picks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
