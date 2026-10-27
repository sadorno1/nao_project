# Lego build guidance experiment (NAO)

The NAO describes a target Lego structure step by step. The participant holds the **front head sensor** to talk and presses a **foot bumper** to request a build check. The robot photographs the build, a vision model turns the photo into structured JSON, code compares it to the target, and the robot phrases the result. A full match ends the session.

The condition (`ai` / `human`) is written **only** to the log. The prompt, voice, gestures and behavior are identical in both conditions, and each log records a SHA-256 of the system prompt so you can confirm this (`summarize_log.py` warns if the hashes differ).

## Setup

```
pip install -r ../requirements.txt
pip install -r requirements-local-stt.txt     # only for TRANSCRIBE_BACKEND = "faster-whisper"
```

As in lab 3, the `.env` with `OPENAI_API_KEY=...` goes in the **parent** folder of `experiment/`.

## Files

| File | What it is |
|---|---|
| `run_session.py` | entry point |
| `config.py` | **every** setting: sensor keys, models, debounce, posture, volume, head pose, flags |
| `prompts/system_prompt.txt` | dialogue prompt (`{TARGET_DESCRIPTION}` and `{EXPRESSIONS}` get filled in) |
| `prompts/target_description.txt` | **edit**: the target in words, from the participant's view |
| `prompts/target_structure.json` | **edit**: the target as blocks, in the camera's frame |
| `prompts/structure_schema.json` | the JSON schema the vision model must follow (colors and block types live here) |
| `prompts/vision_prompt.txt` | vision instructions (coordinate conventions) |
| `prompts/fixed_lines.json` | **edit**: greeting, 3 "take a look" lines (rotated in fixed order), goodbye |
| `tools/sensor_probe.py` | prints which sensor keys fire when you touch the robot |
| `tools/camera_probe.py` | tests ALPhotoCapture vs ALVideoDevice and checks framing |
| `tools/gesture_probe.py` | lists or plays the Sit/Stand animations for each expression |
| `tools/bench_models.py` | verifies the models and benchmarks latency on your network |
| `tools/eval_vision.py` | accuracy and confusion of the build check on labeled photos |
| `tools/pregenerate_audio.py` | caches the fixed lines as audio |
| `tools/summarize_log.py` | turns logs into counts (works on one log or a whole folder; `--csv`) |

## One-time preparation before the pilot

1. **Sensors**: `python tools/sensor_probe.py <ip>`. Hold and release the front head sensor, then press each bumper. Make sure the printed names match `TALK_SENSOR_KEY` / `CHECK_SENSOR_KEYS` in `config.py`. Also watch for flicker: extra 0/1 events while you hold steadily.
2. **Camera**: put the build on the marked spot, then run `python tools/camera_probe.py <ip> --set-head`. Adjust `HEAD_PITCH` / `HEAD_YAW` / `CAMERA_INDEX` until the build fills the frame, and set `CAPTURE_METHOD` to whichever method worked.
3. **Gestures**: `python tools/gesture_probe.py <ip> --list-all`. Fix `SIT_ANIMATIONS` in `config.py` (the current Sit paths are unverified guesses). Then use `--play nod hi listen happy thinking excited surprised` to see each one seated. A missing animation means no gesture; Stand animations are never played while seated.
4. **Models**: `python tools/bench_models.py`. It checks that every candidate exists, streams, and follows the "line 1 = expression" format (LLM), and that the vision candidates accept image input with a JSON schema. It also times TTS and transcription. Copy its picks into `config.py`.
5. **Vision accuracy**: put photos taken **with the robot camera at the session head pose** into `test_photos/correct/`, `test_photos/near_miss/` and `test_photos/wrong/`, then run
   `python tools/eval_vision.py test_photos --repeat 2`, and again with `--no-reference` if you use a reference photo.
   The number that matters most is **false matches**: those would end a session early.
6. **Edit** the three prompt files marked TODO, then run `python tools/pregenerate_audio.py`. A real session refuses to start while any `TODO` remains.

## Running a session

```
python run_session.py --ip 192.168.1.100 --pid P07 --condition ai
```

- The script refuses to start if `data/P07/` already exists. Add `--force-new` to create `data/P07/<timestamp>/` instead.
- Startup order: the robot goes to the configured posture → sets the volume and head pose once → uploads the cached fixed lines → greets → gives the first step (`FIRST_STEP_AFTER_GREETING`). After that it waits for speech or a bumper press. There are no silence prompts.
- **To end early**, press `q` in the terminal window. It's logged as `end_reason = experimenter`. Ctrl+C is logged as `keyboard_interrupt`.
- There is no time limit. `HARD_CAP_MINUTES` in `config.py` is off by default.

### Dry run (no robot)

```
python run_session.py --dry-run --pid test01 --condition ai --image test_photos/correct/a.jpg [--no-tts]
```

Type what the participant says. `/check [image]` simulates a bumper press, and `/end` ends the session. Robot actions print as `[Mock ...]`. The OpenAI API is still used. `--no-tts` skips speech synthesis.

## How a turn works and what gets timed

Hold the head sensor and the eyes turn green and recording starts. Release it and the eyes go back to neutral. Then:
1. The wav is fetched over the single session SFTP connection.
2. It's transcribed, and the wav is deleted on the laptop and on the robot.
3. The LLM reply streams in. When line 1 arrives the gesture starts, and each finished sentence goes through TTS, upload and playback while the rest is still generating.

Each turn logs a `latency` event with seconds since release for `wav_transfer`, `transcription`, `llm_first_token`, `tts_first_audio`, `playback_start` and more. Checks log `bumper_press`, `look_line_done`, `capture_done` and `vision_done`.

The robot may leave a short gap between sentences, because each sentence is a separate file.

While the robot is processing or speaking, the talk sensor and bumpers are ignored but **logged** with `robot_state` and `ignored_reason`. `ALLOW_BARGE_IN = True` lets a head touch stop the robot's speech.

### Transcription options (`TRANSCRIBE_BACKEND`)

- **`gpt-4o-mini-transcribe`** (default): fast and cheap, with good accuracy.
- **`whisper-1`**: robust, but usually slower.
- **`faster-whisper`** (local): no network round trip and the audio never leaves the laptop. Speed depends on your CPU/GPU and the model size, small models make more mistakes on noisy NAO mic audio, and it loads once at startup.

Compare them with the `transcription` latency in your pilot logs.

## Build check and its limits

- The target and observations use stud coordinates in the **camera's** frame: x is left to right as the robot sees it, y is front to back, and layer 0 sits on the table. `(x, y)` is the block's front-left stud. Orientation 0 means the long side runs along x.
- **Matching rules:** color, type, orientation and layer must match exactly. x/y must match exactly after one shift of the whole structure, so the build zone can move. If two shifts tie, the result is logged as `alignment_ambiguous`.
- A check reports correct / wrong (move, rotate, other layer, or extra) / not placed yet. Only a full match ends the session.
- **Occlusion:**
  - A single front camera can't see blocks behind or under others, and depth (y) is its weakest estimate.
  - The vision model is told to mark blocks it can't see as `not_visible` instead of guessing. Those blocks are counted as unverifiable, never as right or wrong.
  - In `target_structure.json`, set `"front_visible": false` for blocks the camera can't see in the finished build. A full match doesn't require them, so **a missing hidden block can't be detected**.
- **Lone blocks:** because of the shift tolerance, a single placed block is always "in the right place". Positions only become meaningful once two or more blocks are down.
- `PARTICIPANT_SIDE` turns camera offsets into the participant's left/right. The default `"facing"` means the participant sits across from the robot.
- Every check saves `images/check_NNN.jpg` (raw) and `check_NNN_sent.jpg` (exactly what the model saw). The log has the vision JSON and the diff.

## Data

`data/<pid>/events_<timestamp>.jsonl` holds one JSON object per line. The main event types are: `session_start` (condition, config, prompt hash), `task_start`, `talk_sensor`, `bumper`, `recording_*`, `audio_deleted`, `participant_utterance`, `identity_question`, `robot_utterance`, `gesture`, `latency`, `check_start`, `check_result`, `check_error`, `session_end` (end_reason, task_completion_time_s).

Raw audio is never kept. `data/`, `audio_cache/` and `tmp/` are gitignored.

```
python tools/summarize_log.py data --csv summary.csv
```

The summary reports bumper presses (total, accepted, ignored), robot instructions, repeated instructions (≥ 0.9 normalized similarity to any earlier robot utterance), identity questions, completion time and median stage latencies.

Identity questions are found by keyword matching (`IDENTITY_QUESTION_PATTERNS`), which misses paraphrases. Every transcript is in the log for manual coding.

## Pre-session checklist

- [ ] Robot on, charged, connected; `ping <ip>` works; **same network setup (Wi-Fi vs. cable, router) as the pilot**
- [ ] Robot on the floor with free space around it (it moves to the configured posture at startup)
- [ ] `tools/sensor_probe.py` passed today: front head = `TALK_SENSOR_KEY`, both bumpers fire
- [ ] Build area on the marked spot, lighting as in the test photos; `camera_probe.py --set-head` framing checked
- [ ] Volume (`VOLUME`) checked at the participant's seat
- [ ] `target_description.txt`, `target_structure.json` and `fixed_lines.json` are the final versions (no TODO); `pregenerate_audio.py` run after the last edit
- [ ] Models in `config.py` are the benchmarked ones
- [ ] Participant ID is new, and the condition matches the script the experimenter just read to the participant
- [ ] Blocks reset; video recording started
- [ ] Start: `python run_session.py --ip <ip> --pid <pid> --condition <ai|human>`; terminal window focused so `q` works
