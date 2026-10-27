#single place for every tunable setting of the Lego build-guidance experiment
#nothing in here may depend on the study condition: the condition is only ever written to the log
import os

EXPERIMENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(EXPERIMENT_DIR)

#same convention as lab 3: the .env with OPENAI_API_KEY lives in the parent directory of this folder
DOTENV_PATH = os.path.join(REPO_DIR, ".env")

# ---------------------------------------------------------------- robot connection
ROBOT_PORT = 9559
ROBOT_USER = "nao"
ROBOT_PASS = "nao"

#robot-side scratch paths (overwritten every turn, removed at session end)
ROBOT_WORK_DIR = "/home/nao/experiment_tmp"
ROBOT_RECORDING_PATH = ROBOT_WORK_DIR + "/recording.wav"
ROBOT_PHOTO_DIR = ROBOT_WORK_DIR
ROBOT_PHOTO_NAME = "check"

# ---------------------------------------------------------------- sensors
#ALL sensor key names live here, because they differ between NAO versions.
#verify them on your robot with tools/sensor_probe.py before the pilot
TALK_SENSOR_KEY = "FrontTactilTouched"
CHECK_SENSOR_KEYS = ["LeftBumperPressed", "RightBumperPressed"]

#keys sensor_probe.py listens to, in addition to whatever ALMemory reports on this robot
PROBE_SENSOR_KEYS = [
    "FrontTactilTouched", "MiddleTactilTouched", "RearTactilTouched",
    "LeftBumperPressed", "RightBumperPressed", "ChestButtonPressed",
    "HandLeftBackTouched", "HandLeftLeftTouched", "HandLeftRightTouched",
    "HandRightBackTouched", "HandRightLeftTouched", "HandRightRightTouched",
]
#NAOqi 2.x also raises this event with a list of [sensor_name, state] pairs on any touch
PROBE_TOUCH_CHANGED_EVENT = "TouchChanged"

DEBOUNCE_S = 0.5            #presses within this window after the previous accepted press/release are ignored
MIN_HOLD_S = 0.3            #shorter holds are treated as accidental taps (logged, recording discarded)

#False = talk sensor is ignored (and logged) while the robot is busy speaking/processing
#True  = barge-in: touching the talk sensor stops the robot's speech and starts recording
ALLOW_BARGE_IN = False

# ---------------------------------------------------------------- body
POSTURE = "Sit"             #"Sit" or "Stand"
VOLUME = 70                 #set once at startup, never changed during the session
HEAD_YAW = 0.0              #radians, set once at startup
HEAD_PITCH = 0.35           #radians (positive = look down). frame the marked build spot with tools/camera_probe.py
#animations move the head; True re-applies the fixed head pose after a gesture finishes, before a photo
REASSERT_HEAD_POSE_BEFORE_PHOTO = True

EYES_IDLE_RGB = (1.0, 1.0, 1.0)       #neutral white
EYES_RECORDING_RGB = (0.0, 1.0, 0.0)  #green while the talk sensor is held

#expression names the model may use (lab 3 names minus sad and shy)
EXPRESSIONS = ["nod", "hi", "listen", "happy", "thinking", "excited", "surprised"]

#lab 3 animation paths, only used when POSTURE == "Stand"
STAND_ANIMATIONS = {
    "nod": "animations/Stand/Gestures/Yes_1",
    "hi": "animations/Stand/Gestures/Hey_1",
    "listen": "animations/Stand/BodyTalk/Listening/Listening_2",
    "happy": "animations/Stand/Gestures/Enthusiastic_1",
    "thinking": "animations/Stand/BodyTalk/Thinking/Remember_1",
    "excited": "animations/Stand/Emotions/Positive/Excited_1",
    "surprised": "animations/Stand/Emotions/Negative/Surprise_1",
}
#seated equivalents. UNVERIFIED candidate paths: run tools/gesture_probe.py on the robot,
#which lists the animations/Sit/* behaviors actually installed, and fix this map.
#Stand animations are never played while seated; a missing Sit animation means no gesture (logged).
SIT_ANIMATIONS = {
    "nod": "animations/Sit/Gestures/Yes_1",
    "hi": "animations/Sit/Gestures/Hey_1",
    "listen": "animations/Sit/BodyTalk/Listening/Listening_1",
    "happy": "animations/Sit/Emotions/Positive/Happy_1",
    "thinking": "animations/Sit/BodyTalk/Thinking/Remember_1",
    "excited": "animations/Sit/Emotions/Positive/Excited_1",
    "surprised": "animations/Sit/Emotions/Neutral/Surprise_1",
}
GESTURE_WAIT_TIMEOUT_S = 6.0          #max wait for a gesture to finish before taking a photo
LOOK_GESTURE = "thinking"             #gesture played with the fixed "take a look" line
GREETING_GESTURE = None               #None = no gesture with the fixed greeting
GOODBYE_GESTURE = None                #None = no gesture with the fixed goodbye

# ---------------------------------------------------------------- session
HARD_CAP_MINUTES = None               #None = off (default). a number ends the session after that many minutes
SAY_GOODBYE_ON_HARD_CAP = True
SAY_GOODBYE_ON_EXPERIMENTER_END = False
EXPERIMENTER_END_KEY = "q"
#after the fixed greeting, have the model give the first build step immediately
FIRST_STEP_AFTER_GREETING = True
#text sent to the model when a recording transcribes to nothing; set to None to stay silent instead
EMPTY_TRANSCRIPT_MESSAGE = "[The participant's speech could not be understood.]"

# ---------------------------------------------------------------- models
#UNVERIFIED until tools/bench_models.py has been run on the lab network. see README.
LLM_MODEL = "gpt-4.1-mini"
LLM_REASONING_EFFORT = None           #e.g. "minimal" for gpt-5-mini, None for non-reasoning models
LLM_MAX_COMPLETION_TOKENS = 200
LLM_CANDIDATES = [("gpt-4.1-mini", None), ("gpt-5-mini", "minimal")]

VISION_MODEL = "gpt-4.1"
VISION_REASONING_EFFORT = None
VISION_CANDIDATES = [("gpt-4.1", None), ("gpt-5", "low")]
VISION_RETRIES = 1

TTS_MODEL = "tts-1"
TTS_VOICE = "sage"
TTS_FORMAT = "mp3"
TTS_CANDIDATES = ["tts-1", "gpt-4o-mini-tts"]

#"gpt-4o-mini-transcribe", "whisper-1", or "faster-whisper" (local, needs requirements-local-stt.txt)
TRANSCRIBE_BACKEND = "gpt-4o-mini-transcribe"
TRANSCRIBE_LANGUAGE = "en"
FASTER_WHISPER_MODEL = "small"        #tiny / base / small / medium
FASTER_WHISPER_DEVICE = "cpu"
FASTER_WHISPER_COMPUTE_TYPE = "int8"

# ---------------------------------------------------------------- camera / vision
CAPTURE_METHOD = "auto"               #"auto" (photo, then video fallback), "photo", or "video"
CAMERA_INDEX = 0                      #0 = top camera, 1 = bottom camera
PHOTO_RESOLUTION = 3                  #ALPhotoCapture: 2 = 640x480, 3 = 1280x960
VIDEO_RESOLUTION = 2                  #ALVideoDevice: 2 = 640x480
IMAGE_MAX_SIDE = 768
IMAGE_JPEG_QUALITY = 85
REFERENCE_PHOTO_PATH = None           #optional photo of the correct build, shown to the vision model
#which side of the build the participant sits on, used to turn stud offsets into left/right words
#"facing" = across from the robot (left/right mirrored), "same_side" = next to the robot
PARTICIPANT_SIDE = "facing"

# ---------------------------------------------------------------- files
PROMPTS_DIR = os.path.join(EXPERIMENT_DIR, "prompts")
SYSTEM_PROMPT_PATH = os.path.join(PROMPTS_DIR, "system_prompt.txt")
TARGET_DESCRIPTION_PATH = os.path.join(PROMPTS_DIR, "target_description.txt")
TARGET_STRUCTURE_PATH = os.path.join(PROMPTS_DIR, "target_structure.json")
STRUCTURE_SCHEMA_PATH = os.path.join(PROMPTS_DIR, "structure_schema.json")
VISION_PROMPT_PATH = os.path.join(PROMPTS_DIR, "vision_prompt.txt")
FIXED_LINES_PATH = os.path.join(PROMPTS_DIR, "fixed_lines.json")
DATA_DIR = os.path.join(EXPERIMENT_DIR, "data")
AUDIO_CACHE_DIR = os.path.join(EXPERIMENT_DIR, "audio_cache")
TMP_DIR = os.path.join(EXPERIMENT_DIR, "tmp")

#placeholder marker: run_session.py refuses a real (non dry-run) session while any prompt file still contains it
PLACEHOLDER_MARKER = "TODO"

# ---------------------------------------------------------------- analysis
REPEAT_SIMILARITY = 0.9
#transcripts matching any of these (case-insensitive regex) are logged as identity_question events.
#keyword matching misses paraphrases; all transcripts are logged for manual coding anyway
IDENTITY_QUESTION_PATTERNS = [
    r"\bare you (an? )?(ai|a\.i\.|robot|computer|machine|program|person|human|real)\b",
    r"\b(artificial intelligence|chat ?gpt|language model)\b",
    r"\b(who|what|someone|somebody|anyone|a person)\b.*\b(control|controlling|operating|typing|talking through|behind)\b",
    r"\bis (this|there) (a )?(person|human|someone|somebody)\b",
    r"\b(remote|remotely) (controlled|operated)\b",
]
