#streams build instructions from the OpenAI API.
#reply format (replaces lab 3's JSON): line 1 = expression name, remaining text = speech.
#the gesture callback fires as soon as line 1 arrives, and speech is emitted sentence by sentence
import hashlib
import re
import time

import config

_SENTENCE_END = re.compile(r"(.+?[.!?]+[\"')\]]*)\s+", re.S)
_EXPRESSION_PREFIX = re.compile(r"^(expression|gesture)\s*[:=-]\s*", re.I)
_MAX_EXPRESSION_LINE = 30   #a first line longer than this without a newline is treated as speech


#reads system_prompt.txt and fills in the target description and expression list.
#takes no condition argument on purpose: the prompt is identical in both conditions
def build_system_prompt(prompt_path=config.SYSTEM_PROMPT_PATH, target_path=config.TARGET_DESCRIPTION_PATH,
                        expressions=config.EXPRESSIONS):
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read().strip()
    with open(target_path, "r", encoding="utf-8") as f:
        target = f.read().strip()
    prompt = template.replace("{TARGET_DESCRIPTION}", target).replace("{EXPRESSIONS}", ", ".join(expressions))
    return prompt, hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def normalize_expression(line):
    name = _EXPRESSION_PREFIX.sub("", line.strip()).strip(" .,:;!*'\"`").lower()
    return name


#incremental parser for the streamed reply. feed() returns a list of ("expression", name) and
#("sentence", text) events in order; finish() flushes what is left
class ReplyStreamParser:
    def __init__(self, allowed=config.EXPRESSIONS):
        self.allowed = set(allowed)
        self.header_done = False
        self.header = ""
        self.buffer = ""
        self.expression = None
        self.violations = []

    def _resolve_header(self, line):
        self.header_done = True
        name = normalize_expression(line)
        if name in self.allowed:
            self.expression = name
            return [("expression", name)], ""
        if name and " " not in name and len(name) <= 12:
            #looks like an expression name, just not an allowed one: drop it, no gesture
            self.violations.append(f"unknown_expression:{name}")
            return [], ""
        #no expression line at all: the first line is speech
        self.violations.append("missing_expression_line")
        return [], line

    def feed(self, chunk):
        out = []
        if not self.header_done:
            self.header += chunk
            stripped = self.header.lstrip()
            if "\n" in stripped:
                line, rest = stripped.split("\n", 1)
                events, speech = self._resolve_header(line)
                out.extend(events)
                self.buffer += (speech + " " if speech else "") + rest
            elif len(stripped) > _MAX_EXPRESSION_LINE:
                events, speech = self._resolve_header(stripped)
                out.extend(events)
                self.buffer += speech
            else:
                return out
        else:
            self.buffer += chunk
        out.extend(self._pop_sentences())
        return out

    def _pop_sentences(self):
        out = []
        while True:
            m = _SENTENCE_END.match(self.buffer)
            if not m:
                break
            sentence = " ".join(m.group(1).split())
            self.buffer = self.buffer[m.end():]
            if sentence:
                out.append(("sentence", sentence))
        return out

    def finish(self):
        out = []
        if not self.header_done:
            line = self.header.strip()
            events, speech = self._resolve_header(line)
            out.extend(events)
            self.buffer += speech
        out.extend(self._pop_sentences())
        tail = " ".join(self.buffer.split())
        self.buffer = ""
        if tail:
            out.append(("sentence", tail))
        return out


class DialogueModel:
    def __init__(self, client, system_prompt, model=config.LLM_MODEL, reasoning_effort=config.LLM_REASONING_EFFORT,
                 max_completion_tokens=config.LLM_MAX_COMPLETION_TOKENS):
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_completion_tokens = max_completion_tokens
        self.history = [{"role": "system", "content": system_prompt}]

    def _request_kwargs(self):
        kwargs = {"model": self.model, "messages": self.history, "stream": True}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
            #reasoning tokens count against the completion budget
            kwargs["max_completion_tokens"] = self.max_completion_tokens + 1000
        else:
            kwargs["max_completion_tokens"] = self.max_completion_tokens
        return kwargs

    #streams one reply. on_expression(name) and on_sentence(text) are called as soon as each is available.
    #should_stop() lets a barge-in abandon the rest of the stream. returns a summary dict for the log
    def stream_reply(self, user_content, on_expression, on_sentence, timer=None, should_stop=None):
        self.history.append({"role": "user", "content": user_content})
        parser = ReplyStreamParser()
        raw = ""
        sentences = []
        stopped = False
        t_request = time.perf_counter()

        def handle(events):
            for kind, value in events:
                if kind == "expression":
                    on_expression(value)
                else:
                    sentences.append(value)
                    on_sentence(value)

        stream = self.client.chat.completions.create(**self._request_kwargs())
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if not delta:
                    continue
                if timer:
                    timer.mark("llm_first_token")
                raw += delta
                handle(parser.feed(delta))
                if should_stop and should_stop():
                    stopped = True
                    break
        finally:
            try:
                stream.close()
            except Exception:
                pass
        if not stopped:
            handle(parser.finish())
        if timer:
            timer.mark("llm_done")

        self.history.append({"role": "assistant", "content": raw})
        return {
            "raw": raw,
            "expression": parser.expression,
            "speech": " ".join(sentences),
            "sentences": sentences,
            "format_violations": parser.violations,
            "stopped_early": stopped,
            "llm_total_s": round(time.perf_counter() - t_request, 4),
        }
