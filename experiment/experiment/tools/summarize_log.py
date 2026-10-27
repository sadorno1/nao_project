#summarizes session logs into robot-side counts
#usage: python tools/summarize_log.py <events.jsonl or participant folder> [...] [--csv out.csv]
import argparse
import csv
import glob
import os
import re
import statistics
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config
from session_log import read_events

LATENCY_STAGES = ["wav_transfer", "transcription", "llm_first_token", "tts_first_audio", "playback_start"]


def normalize(text):
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split())


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def summarize(path):
    events = read_events(path)
    start = next((e for e in events if e["event"] == "session_start"), {})
    end = next((e for e in events if e["event"] == "session_end"), {})
    s = {
        "log": path,
        "participant_id": start.get("participant_id"),
        "condition": start.get("condition"),
        "dry_run": start.get("dry_run"),
        "system_prompt_sha256": (start.get("system_prompt_sha256") or "")[:12],
        "end_reason": end.get("end_reason", "no_session_end_event"),
        "task_completion_time_s": end.get("task_completion_time_s"),
        "session_duration_s": end.get("session_duration_s"),
    }

    bumper_presses = [e for e in events if e["event"] == "bumper" and e.get("action") == "press"]
    s["bumper_presses_total"] = len(bumper_presses)
    s["bumper_presses_accepted"] = sum(1 for e in bumper_presses if e.get("accepted"))
    s["bumper_presses_ignored"] = s["bumper_presses_total"] - s["bumper_presses_accepted"]
    s["bumper_presses_during_robot_speech"] = sum(1 for e in bumper_presses if e.get("robot_state") == "speaking")

    talk = [e for e in events if e["event"] == "talk_sensor" and e.get("action") == "touch"]
    s["talk_touches_total"] = len(talk)
    s["talk_touches_ignored"] = sum(1 for e in talk if not e.get("accepted"))
    s["talk_touches_during_robot_speech"] = sum(1 for e in talk if e.get("robot_state") == "speaking")
    s["recordings_discarded_short"] = sum(1 for e in events if e["event"] == "recording_discarded")

    results = [e for e in events if e["event"] == "check_result"]
    s["checks"] = sum(1 for e in events if e["event"] == "check_start")
    s["check_matches"] = sum(1 for e in results if e.get("match"))
    s["check_errors"] = sum(1 for e in events if e["event"] == "check_error")

    s["participant_utterances"] = sum(1 for e in events if e["event"] == "participant_utterance")
    s["identity_questions"] = sum(1 for e in events if e["event"] == "identity_question")

    robot = [e for e in events if e["event"] == "robot_utterance"]
    llm = [e for e in robot if e.get("kind") == "llm"]
    s["robot_instructions"] = len(llm)
    s["robot_fixed_lines"] = len(robot) - len(llm)

    #repeated = an LLM utterance >= REPEAT_SIMILARITY similar to ANY earlier robot utterance (LLM or fixed)
    repeated = 0
    earlier = []
    for e in robot:
        text = normalize(e.get("text"))
        if e.get("kind") == "llm" and text and any(similarity(text, p) >= config.REPEAT_SIMILARITY for p in earlier):
            repeated += 1
        if text:
            earlier.append(text)
    s["repeated_instructions"] = repeated
    s["format_violations"] = sum(1 for e in llm if e.get("format_violations"))
    s["errors"] = sum(1 for e in events if e["event"] in ("error", "llm_error", "fatal_error"))

    turns = [e for e in events if e["event"] == "latency" and e.get("kind") == "turn"]
    for stage in LATENCY_STAGES:
        values = [t["stages_s"][stage] for t in turns if stage in t.get("stages_s", {})]
        s[f"median_{stage}_s"] = round(statistics.median(values), 3) if values else None
    return s


def find_logs(paths):
    found = []
    for p in paths:
        if os.path.isdir(p):
            found.extend(sorted(glob.glob(os.path.join(p, "**", "events_*.jsonl"), recursive=True)))
        else:
            found.append(p)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--csv", help="write one row per log to this CSV file")
    args = parser.parse_args()

    summaries = [summarize(p) for p in find_logs(args.paths)]
    if not summaries:
        print("No logs found.")
        return 1
    for s in summaries:
        print(f"\n=== {s['log']}")
        for k, v in s.items():
            if k != "log":
                print(f"  {k:<36} {v}")
    hashes = {s["system_prompt_sha256"] for s in summaries}
    if len(hashes) > 1:
        print(f"\nWARNING: system prompt differs between these logs: {sorted(hashes)}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
            writer.writeheader()
            writer.writerows(summaries)
        print(f"\nWrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
