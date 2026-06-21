import asyncio
import ctypes
import queue
import re
import threading
import time
import uuid
from pathlib import Path

from jarvis_ai import load_config


def _clean_text(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:900]


class EdgeTTSPlayer:
    def __init__(self, on_play=None):
        self.config = load_config()
        self.voice = self.config.get("edge_tts_voice", "ru-RU-DmitryNeural")
        self.enabled = bool(self.config.get("tts_enabled", True))
        self.cache_dir = Path(self.config.get("tts_cache_dir") or Path(__file__).with_name("tts_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.on_play = on_play or (lambda seconds: None)
        self.winmm = ctypes.windll.winmm
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.current_alias = ""
        self.active_aliases = set()
        self.stop_version = 0
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def speak(self, text):
        text = _clean_text(text)
        if not text:
            return False
        self.queue.put(text)
        return True

    def stop(self):
        with self.lock:
            self.stop_version += 1
            aliases = set(self.active_aliases)
            if self.current_alias:
                aliases.add(self.current_alias)
            self.current_alias = ""
            self.active_aliases.clear()
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                break
        for alias in aliases:
            self.winmm.mciSendStringW(f"stop {alias}", None, 0, None)
            self.winmm.mciSendStringW(f"close {alias}", None, 0, None)
        return True

    def _worker(self):
        while True:
            text = self.queue.get()
            try:
                with self.lock:
                    version = self.stop_version
                self._speak_now(text, version)
            finally:
                self.queue.task_done()

    def _speak_now(self, text, version):
        if not self.enabled:
            return False
        try:
            import edge_tts
        except Exception:
            return False
        path = self.cache_dir / f"tts_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.mp3"
        try:
            asyncio.run(edge_tts.Communicate(text, self.voice).save(str(path)))
            with self.lock:
                if version != self.stop_version:
                    return False
            return self._play_mp3(path, version)
        except Exception:
            return False

    def _play_mp3(self, path, version):
        alias = "jarvis_tts_" + uuid.uuid4().hex[:10]
        safe = str(path).replace('"', "")
        opened = self.winmm.mciSendStringW(f'open "{safe}" type mpegvideo alias {alias}', None, 0, None)
        if opened != 0:
            return False
        with self.lock:
            if version != self.stop_version:
                self.winmm.mciSendStringW(f"close {alias}", None, 0, None)
                return False
            self.current_alias = alias
            self.active_aliases.add(alias)
        duration = self._duration(alias)
        self.on_play(duration + 1.6)
        with self.lock:
            if version != self.stop_version or alias not in self.active_aliases:
                self.winmm.mciSendStringW(f"close {alias}", None, 0, None)
                self.active_aliases.discard(alias)
                return False
        self.winmm.mciSendStringW(f"play {alias} from 0", None, 0, None)
        threading.Timer(max(2.0, duration + 2.0), lambda: self._close_alias(alias)).start()
        return True

    def _close_alias(self, alias):
        with self.lock:
            if self.current_alias == alias:
                self.current_alias = ""
            self.active_aliases.discard(alias)
        self.winmm.mciSendStringW(f"close {alias}", None, 0, None)

    def _duration(self, alias):
        buf = ctypes.create_unicode_buffer(64)
        err = self.winmm.mciSendStringW(f"status {alias} length", buf, 64, None)
        if err == 0 and buf.value.isdigit():
            return max(0.5, int(buf.value) / 1000)
        return 2.8
