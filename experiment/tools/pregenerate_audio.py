#pre-generates the cached audio for the fixed lines (greeting, 3 "take a look" lines, goodbye)
#run it after editing prompts/fixed_lines.json, so the first session does not wait for TTS.
#run_session.py also generates any missing file at startup, before the participant is greeted
#usage: python tools/pregenerate_audio.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config
from run_session import load_fixed_lines


def main():
    from dotenv import load_dotenv
    from openai import OpenAI
    from speech import TTS
    load_dotenv(config.DOTENV_PATH)
    tts = TTS(OpenAI())
    lines = load_fixed_lines()
    for text in [lines["greeting"], *lines["look"], lines["goodbye"]]:
        existed = os.path.exists(tts.cache_path(text))
        path = tts.ensure_cached(text)
        print(f"{'cached ' if existed else 'created'} {os.path.basename(path)}  {text!r}")
    print(f"\nModel {tts.model}, voice {tts.voice}. Cache folder: {config.AUDIO_CACHE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
