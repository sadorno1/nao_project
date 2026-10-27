#turns raw sensor callbacks into debounced session events, and logs every raw touch/release/bumper event
import queue
import threading
import time

import config

IDLE, RECORDING, PROCESSING, SPEAKING, CHECKING, ENDED = "idle", "recording", "processing", "speaking", "checking", "ended"


class InputManager:
    def __init__(self, log, talk_key=config.TALK_SENSOR_KEY, check_keys=config.CHECK_SENSOR_KEYS,
                 debounce_s=config.DEBOUNCE_S, allow_barge_in=config.ALLOW_BARGE_IN):
        self.log = log
        self.talk_key = talk_key
        self.check_keys = list(check_keys)
        self.debounce_s = debounce_s
        self.allow_barge_in = allow_barge_in
        self.events = queue.Queue()
        self.on_barge_in = None       #set by the session: called from the sensor thread to stop speech

        self._lock = threading.Lock()
        self._state = IDLE
        self._talk_down = False
        self._last_talk_change = -1e9
        self._last_check = -1e9

    @property
    def state(self):
        with self._lock:
            return self._state

    #the session sets the state when it starts speaking or returns to idle; sensor callbacks
    #set it themselves on accepted events so there is no window where a second input slips in
    def set_state(self, state):
        with self._lock:
            self._state = state

    #called when robot audio starts playing
    def mark_speaking(self):
        with self._lock:
            if self._state in (PROCESSING, CHECKING):
                self._state = SPEAKING

    #back to idle after a turn or check, unless a barge-in already moved the state to recording
    def finish_busy(self):
        with self._lock:
            if self._state in (PROCESSING, SPEAKING, CHECKING):
                self._state = IDLE

    #registers callbacks on the robot; returns the keys that could be subscribed
    def attach(self, nao):
        ok = []
        if nao.subscribe(self.talk_key, lambda v: self.on_talk(v, time.perf_counter())):
            ok.append(self.talk_key)
        for key in self.check_keys:
            if nao.subscribe(key, lambda v, k=key: self.on_check(k, v, time.perf_counter())):
                ok.append(key)
        return ok

    def on_talk(self, value, t):
        pressed = value is not None and float(value) > 0.5
        barge_in = False
        with self._lock:
            state = self._state
            if pressed:
                if self._talk_down:
                    accepted, reason = False, "already_held"
                elif state == SPEAKING and self.allow_barge_in:
                    accepted, reason, barge_in = True, "barge_in", True
                elif state != IDLE:
                    accepted, reason = False, f"robot_{state}"
                elif t - self._last_talk_change < self.debounce_s:
                    accepted, reason = False, "debounce"
                else:
                    accepted, reason = True, None
                if accepted:
                    self._talk_down = True
                    self._last_talk_change = t
                    self._state = RECORDING
            else:
                if self._talk_down:
                    accepted, reason = True, None
                    self._talk_down = False
                    self._last_talk_change = t
                    self._state = PROCESSING
                else:
                    accepted, reason = False, "no_accepted_press"
        self.log.event("talk_sensor", t_perf=t, key=self.talk_key, action="touch" if pressed else "release",
                       value=value, robot_state=state, accepted=accepted, ignored_reason=reason)
        if barge_in and self.on_barge_in:
            self.on_barge_in()
        if accepted:
            self.events.put(("talk_press" if pressed else "talk_release", t, None))

    def on_check(self, key, value, t):
        pressed = value is not None and float(value) > 0.5
        with self._lock:
            state = self._state
            if not pressed:
                accepted, reason = False, None
            elif state != IDLE:
                accepted, reason = False, f"robot_{state}"
            elif t - self._last_check < self.debounce_s:
                accepted, reason = False, "debounce"
            else:
                accepted, reason = True, None
                self._last_check = t
                self._state = CHECKING
        self.log.event("bumper", t_perf=t, key=key, action="press" if pressed else "release", value=value,
                       robot_state=state, accepted=accepted if pressed else None, ignored_reason=reason)
        if accepted:
            self.events.put(("check", t, key))

    #dry-run: typed participant speech, treated like a completed hold-to-talk turn
    def on_typed(self, text, t):
        with self._lock:
            state = self._state
            accepted = state == IDLE
            if accepted:
                self._state = PROCESSING
        self.log.event("typed_input", t_perf=t, text=text, robot_state=state, accepted=accepted,
                       ignored_reason=None if accepted else f"robot_{state}")
        if accepted:
            self.events.put(("typed", t, text))

    def request_end(self, reason, t=None):
        self.events.put(("end", time.perf_counter() if t is None else t, reason))
