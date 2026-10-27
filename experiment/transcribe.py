#configurable speech-to-text: OpenAI (gpt-4o-mini-transcribe, whisper-1) or local faster-whisper
import config


class Transcriber:
    def __init__(self, client, backend=config.TRANSCRIBE_BACKEND, language=config.TRANSCRIBE_LANGUAGE):
        self.client = client
        self.backend = backend
        self.language = language
        self._local_model = None
        if backend == "faster-whisper":
            #loaded once at startup: the first load is slow and should not land in a participant turn
            from faster_whisper import WhisperModel
            self._local_model = WhisperModel(config.FASTER_WHISPER_MODEL, device=config.FASTER_WHISPER_DEVICE,
                                             compute_type=config.FASTER_WHISPER_COMPUTE_TYPE)

    def transcribe(self, wav_path):
        if self._local_model is not None:
            segments, _ = self._local_model.transcribe(wav_path, language=self.language, beam_size=1)
            return " ".join(s.text.strip() for s in segments).strip()
        with open(wav_path, "rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                model=self.backend,
                file=audio_file,
                language=self.language,
            )
        return (result.text or "").strip()
