#OpenAI TTS -> SFTP -> ALAudioPlayer, one sentence at a time, so playback of sentence 1 starts
#while later sentences are still being generated. fixed lines are cached as audio files
import hashlib
import os
import queue
import threading
import time

import config


class TTS:
    def __init__(self, client, model=config.TTS_MODEL, voice=config.TTS_VOICE, fmt=config.TTS_FORMAT):
        self.client = client
        self.model = model
        self.voice = voice
        self.format = fmt

    #streams speech to a local file; on_first_audio() fires when the first audio bytes arrive
    def synthesize(self, text, local_path, on_first_audio=None):
        with self.client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format=self.format,
        ) as response:
            with open(local_path, "wb") as f:
                first = True
                for data in response.iter_bytes(4096):
                    if first and data:
                        first = False
                        if on_first_audio:
                            on_first_audio()
                    f.write(data)

    #cache file name depends on everything that changes the audio
    def cache_path(self, text, cache_dir=config.AUDIO_CACHE_DIR):
        key = hashlib.sha256(f"{self.model}|{self.voice}|{self.format}|{text}".encode("utf-8")).hexdigest()[:20]
        return os.path.join(cache_dir, f"{key}.{self.format}")

    def ensure_cached(self, text, cache_dir=config.AUDIO_CACHE_DIR):
        os.makedirs(cache_dir, exist_ok=True)
        path = self.cache_path(text, cache_dir)
        if not os.path.exists(path):
            tmp = path + ".part"
            self.synthesize(text, tmp)
            os.replace(tmp, path)
        return path


#one robot reply: sentences go in with add(), close() marks the end, wait() blocks until all are played
class Utterance:
    def __init__(self, pipeline, tag, timer=None, on_playback_start=None):
        self.pipeline = pipeline
        self.tag = tag
        self.timer = timer
        self.on_playback_start = on_playback_start
        self.cancelled = threading.Event()
        self.played = []
        self.errors = []
        self._tts_q = queue.Queue()
        self._play_q = queue.Queue()
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self._play_thread = threading.Thread(target=self._play_worker, daemon=True)
        self._tts_thread.start()
        self._play_thread.start()

    def add(self, sentence):
        self._tts_q.put(sentence)

    def close(self):
        self._tts_q.put(None)

    def cancel(self):
        self.cancelled.set()
        self.pipeline.nao.stop_audio()

    def wait(self):
        self._tts_thread.join()
        self._play_thread.join()
        return {"played": self.played, "cancelled": self.cancelled.is_set(), "errors": self.errors}

    def _tts_worker(self):
        p = self.pipeline
        index = 0
        while True:
            sentence = self._tts_q.get()
            if sentence is None or self.cancelled.is_set():
                if sentence is not None:
                    continue  #drain until close()
                self._play_q.put(None)
                return
            local = os.path.join(p.tmp_dir, f"{self.tag}_{index}.{p.tts.format}")
            remote = f"{config.ROBOT_WORK_DIR}/{self.tag}_{index}.{p.tts.format}"
            index += 1
            try:
                if p.synthesize:
                    p.tts.synthesize(sentence, local,
                                     on_first_audio=(lambda: self.timer.mark("tts_first_audio")) if self.timer else None)
                    if self.timer:
                        self.timer.mark("tts_first_file_ready")
                    p.link.put(local, remote)
                    if self.timer:
                        self.timer.mark("tts_first_upload_done")
                self._play_q.put((sentence, local, remote))
            except Exception as e:
                self.errors.append(f"tts: {e}")
                print(f"TTS failed for sentence {sentence!r}: {e}")

    def _play_worker(self):
        p = self.pipeline
        while True:
            item = self._play_q.get()
            if item is None:
                return
            sentence, local, remote = item
            if not self.cancelled.is_set():
                if self.timer:
                    self.timer.mark("playback_start")
                if self.on_playback_start:
                    self.on_playback_start()
                    self.on_playback_start = None
                try:
                    if p.dry_run:
                        print(f"[Robot says]: {sentence}")
                    else:
                        p.nao.play_file(remote)
                    if not self.cancelled.is_set():
                        self.played.append(sentence)
                except Exception as e:
                    self.errors.append(f"play: {e}")
                    print(f"Playback failed: {e}")
            for cleanup in (lambda: os.remove(local), lambda: p.link.remove(remote)):
                try:
                    cleanup()
                except Exception:
                    pass


class SpeechPipeline:
    def __init__(self, nao, link, tts, dry_run=False, synthesize=True, tmp_dir=config.TMP_DIR):
        self.nao = nao
        self.link = link
        self.tts = tts
        self.dry_run = dry_run
        self.synthesize = synthesize   #False in dry-run --no-tts: print text only
        self.tmp_dir = tmp_dir
        self.fixed_remote = {}
        os.makedirs(tmp_dir, exist_ok=True)

    def start_utterance(self, tag, timer=None, on_playback_start=None):
        return Utterance(self, tag, timer, on_playback_start)

    #generates (or reuses) cached audio for the fixed lines and uploads them to the robot once
    def prepare_fixed(self, texts):
        for text in texts:
            if self.synthesize:
                local = self.tts.ensure_cached(text)
                remote = f"{config.ROBOT_WORK_DIR}/fixed_{os.path.basename(local)}"
                self.link.put(local, remote)
            else:
                remote = None
            self.fixed_remote[text] = remote

    #plays a cached fixed line (blocking); returns the playback start time
    def play_fixed(self, text):
        if text not in self.fixed_remote:
            self.prepare_fixed([text])
        t = time.perf_counter()
        if self.dry_run or not self.synthesize:
            print(f"[Robot says]: {text}")
        else:
            self.nao.play_file(self.fixed_remote[text])
        return t
