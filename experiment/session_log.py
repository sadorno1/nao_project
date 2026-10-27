#per-participant JSON-lines event log. one folder per participant ID, one line per event
import datetime
import json
import os
import threading
import time


class ParticipantFolderExists(Exception):
    pass


#creates data/<participant_id>/ (or a timestamped subfolder with force_new) and appends events to events.jsonl
class SessionLog:
    def __init__(self, data_dir, participant_id, force_new=False):
        if not participant_id or any(c in participant_id for c in '\\/:*?"<>|') or participant_id.startswith("."):
            raise ValueError(f"Invalid participant ID: {participant_id!r}")

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        participant_dir = os.path.join(data_dir, participant_id)
        if os.path.exists(participant_dir):
            if not force_new:
                raise ParticipantFolderExists(
                    f"{participant_dir} already exists. Use a new participant ID, or pass --force-new "
                    f"to create a timestamped subfolder.")
            self.folder = os.path.join(participant_dir, stamp)
        else:
            self.folder = participant_dir
        os.makedirs(self.folder)
        self.images_dir = os.path.join(self.folder, "images")
        os.makedirs(self.images_dir)

        self.path = os.path.join(self.folder, f"events_{stamp}.jsonl")
        self._file = open(self.path, "a", encoding="utf-8")
        self._lock = threading.Lock()
        self.t0 = time.perf_counter()

    #seconds since the log was opened, on the perf_counter clock (all latencies use this clock)
    def rel(self, t_perf=None):
        return (time.perf_counter() if t_perf is None else t_perf) - self.t0

    #writes one event; t_perf lets callers log the exact moment something happened (e.g. a sensor callback)
    def event(self, event_type, t_perf=None, **fields):
        record = {
            "t_wall": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "t_rel": round(self.rel(t_perf), 4),
            "event": event_type,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()
        return record

    def image_path(self, check_number, suffix=""):
        return os.path.join(self.images_dir, f"check_{check_number:03d}{suffix}.jpg")

    def close(self):
        with self._lock:
            if not self._file.closed:
                self._file.close()


#collects perf_counter marks for one turn and logs them relative to the first mark
class StageTimer:
    def __init__(self, log, kind, number, t_start=None):
        self.log = log
        self.kind = kind
        self.number = number
        self.marks = {}
        self.start = time.perf_counter() if t_start is None else t_start

    #only the first call for a stage counts (e.g. first LLM token)
    def mark(self, stage, t_perf=None):
        if stage not in self.marks:
            self.marks[stage] = time.perf_counter() if t_perf is None else t_perf

    def write(self, **extra):
        stages = {k: round(v - self.start, 4) for k, v in sorted(self.marks.items(), key=lambda kv: kv[1])}
        self.log.event("latency", kind=self.kind, number=self.number, stages_s=stages, **extra)
        return stages


def read_events(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
