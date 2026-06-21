import ctypes
import difflib
import html
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from jarvis_ai import GroqJarvisAI
from jarvis_data import APPS, BROWSER_PATHS, SITES, SOUNDS, VOICE_DIR, VOSK_MODEL, VOSK_MODELS
from jarvis_tts import EdgeTTSPlayer
from jarvis_wiki import find_wikipedia, parse_wiki_query

CUSTOM_COMMANDS_PATH = Path(__file__).with_name("custom_commands.json")
MEMORY_PATH = Path(__file__).with_name("jarvis_memory.json")
STATE_PATH = Path(__file__).with_name("jarvis_state.json")

TTS_FALLBACKS = {
    "welcome": "Добро пожаловать, сэр.",
    "status_ok": "Я функционирую нормально и готов к работе, сэр.",
    "yes": "Да, сэр.",
    "doing": "Уже выполняю, сэр.",
    "thanks": "Всегда к вашим услугам, сэр.",
    "site": "Открываю сайт, сэр.",
    "plan": "Отличный план, сэр.",
    "ask_plan": "Что на сегодня планируете, сэр?",
    "ask_timer": "На сколько времени поставить таймер, сэр?",
    "timer_set": "Таймер поставлен, сэр.",
    "timer_done": "Напоминаю, сэр, время таймера истекло.",
    "evening": "Хорошего вечера, сэр.",
    "day": "Хорошего дня, сэр.",
    "confused": "Я сам вахуйе, сэр.",
    "start": "Включаю, сэр.",
    "ok": "Есть, сэр.",
    "good": "Хорошо, сэр.",
    "unknown": "Этот запрос мне не понятен, сэр.",
    "help": "Чем могу помочь, сэр?",
    "remembered": "Запомнил, сэр.",
    "remember_show": "Вот что вы просили запомнить, сэр.",
    "reminder_set": "Хорошо, я напомню вам, сэр.",
    "reminder_due": "Вы просили напомнить, сэр.",
    "rest_choice": "Как вы хотите отдохнуть, сэр?",
    "work_choice": "Какой вариант выбираете, сэр?",
    "rest_done": "Приятного отдыха, сэр.",
    "work_done": "Хорошо поработать, сэр.",
    "will_do": "Будет сделано, сэр.",
}

VK_LWIN = 0x5B
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_F4 = 0x73
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_SPACE = 0x20
VK_RETURN = 0x0D
VK_V = 0x56
VK_W = 0x57
VK_VOLUME_UP = 0xAF
VK_VOLUME_DOWN = 0xAE
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
SW_MINIMIZE = 6
SW_RESTORE = 9
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def normalize(text):
    text = (text or "").lower().replace("ё", "е")
    text = text.replace("сэр", "сер")
    text = re.sub(r"[^a-zа-яәғқңөұүіһ0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ratio(a, b):
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    aw, bw = set(a.split()), set(b.split())
    overlap = len(aw & bw) / max(1, len(aw | bw))
    compact = difflib.SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()
    return max(seq, compact, overlap)


def best_match(query, items, threshold=0.80):
    best = (0.0, None, "")
    for item in items:
        key, title, value, aliases = item
        for alias in [title, key, *aliases]:
            score = ratio(query, alias)
            if score > best[0]:
                best = (score, item, alias)
    return best if best[0] >= threshold else (best[0], None, best[2])


def best_phrase(query, candidates, threshold=0.80):
    best = (0.0, None, "")
    for phrase, payload in candidates:
        score = ratio(query, phrase)
        if score > best[0]:
            best = (score, payload, phrase)
    return best if best[0] >= threshold else (best[0], None, best[2])


def strip_words(text, words):
    result = normalize(text)
    for word in words:
        result = re.sub(rf"\b{re.escape(word)}\b", " ", result)
    return normalize(result)


def find_sound(token):
    token = normalize(token)
    best = (0.0, None)
    for path in Path(VOICE_DIR).glob("*.mp3"):
        stem = normalize(path.stem)
        clean_stem = re.sub(r"^jarvis\s+\d{4}\s+\d{2}\s+\d{2}\s+\d{2}\s+\d{2}\s+", "", stem)
        for candidate in (clean_stem, stem):
            score = ratio(token, candidate)
            if token and token in candidate:
                score = max(score, 0.80 + min(0.19, len(token) / max(1, len(candidate)) * 0.19))
            if candidate == token:
                score = 1.0
            if score > best[0]:
                best = (score, path)
    return str(best[1]) if best[0] >= 0.70 else None


def voice_asset_phrases():
    phrases = set()
    for path in Path(VOICE_DIR).glob("*.mp3"):
        stem = normalize(path.stem)
        stem = re.sub(r"^jarvis\s+\d{4}\s+\d{2}\s+\d{2}\s+\d{2}\s+\d{2}\s+", "", stem)
        if stem:
            phrases.add(stem)
            phrases.add(stem.replace(" сер", ""))
    for token in SOUNDS.values():
        phrase = normalize(token.replace("-", " "))
        if phrase:
            phrases.add(phrase)
    return sorted(phrases, key=len, reverse=True)


def load_custom_commands():
    if not CUSTOM_COMMANDS_PATH.exists():
        return []
    try:
        data = json.loads(CUSTOM_COMMANDS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def load_memory():
    if not MEMORY_PATH.exists():
        return {}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_memory(data):
    try:
        MEMORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data):
    try:
        STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


KZ_SITE_ALIASES = {
    "youtube": ["ютуб", "youtube", "ю туб"],
    "telegram": ["телеграм", "telegram"],
    "chatgpt": ["чат гпт", "чат жпт", "chatgpt"],
    "claude": ["клауд", "клод", "claude"],
    "gmail": ["gmail", "джимейл", "пошта"],
    "google": ["гугл", "google"],
    "yandex": ["яндекс", "yandex"],
    "yandex_music": ["яндекс музыка", "музыка"],
    "kinopoisk": ["кинопоиск", "кино поиск"],
    "lichess": ["личесс", "lichess"],
    "weather": ["ауа райы", "погода"],
    "tenge": ["теңге", "теңге бағамы"],
    "dollar": ["доллар", "доллар бағамы"],
    "tengrinews": ["тенгриньюс", "қазақстан жаңалықтары"],
    "informburo": ["информбюро"],
    "github": ["гитхаб", "github"],
    "wikipedia": ["википедия", "wiki"],
    "translate": ["аудармашы", "переводчик"],
    "maps": ["карта", "карталар"],
    "drive": ["гугл диск", "drive"],
    "discord": ["дискорд", "discord"],
    "instagram": ["инстаграм"],
    "tiktok": ["тик ток", "tiktok"],
    "whatsapp_web": ["ватсап веб", "whatsapp web"],
    "spotify": ["spotify", "спотифай"],
    "twitch": ["твич", "twitch"],
    "canva_web": ["канва сайт", "canva"],
    "openai": ["openai", "опен аи"],
}


KZ_APP_ALIASES = {
    "chrome": ["хром", "chrome"],
    "edge": ["edge", "эдж"],
    "utorrent": ["торрент", "utorrent"],
    "whatsapp": ["ватсап", "whatsapp"],
    "canva": ["канва", "canva"],
    "steam": ["стим", "steam"],
    "windirstat": ["диск тексеру", "диск тексер"],
    "xenzy": ["xenzy", "зензи"],
    "vscode": ["vs code", "visual studio code", "код"],
    "zoom": ["зум", "zoom"],
    "codex": ["codex", "кодекс"],
    "claude": ["claude", "клауд", "клод"],
    "recycle": ["қоқыс", "корзина"],
    "notepad": ["блокнот", "дәптер"],
    "calculator": ["калькулятор"],
    "taskmgr": ["тапсырмалар диспетчері", "диспетчер"],
}


def model_path_for(language):
    if language == "kz":
        primary = VOSK_MODELS.get("kz", VOSK_MODEL)
        fallback = VOSK_MODELS.get("kz_fallback", primary)
        return primary if primary.exists() else fallback
    return VOSK_MODELS.get("ru", VOSK_MODEL)


class AudioPlayer:
    def __init__(self, on_play=None):
        self.winmm = ctypes.windll.winmm
        self._counter = 0
        self.on_play = on_play or (lambda seconds: None)

    def play(self, sound_key):
        token = SOUNDS.get(sound_key, sound_key)
        path = find_sound(token)
        if not path:
            return False
        self._counter += 1
        alias = f"jarvis_{self._counter}"
        safe = path.replace('"', "")
        self.winmm.mciSendStringW(f'open "{safe}" type mpegvideo alias {alias}', None, 0, None)
        duration = self._duration(alias)
        self.on_play(duration + 1.2)
        self.winmm.mciSendStringW(f"play {alias}", None, 0, None)
        threading.Timer(max(2.0, duration + 2.0), lambda: self.winmm.mciSendStringW(f"close {alias}", None, 0, None)).start()
        return True

    def _duration(self, alias):
        buf = ctypes.create_unicode_buffer(64)
        err = self.winmm.mciSendStringW(f"status {alias} length", buf, 64, None)
        if err == 0 and buf.value.isdigit():
            return max(0.5, int(buf.value) / 1000)
        return 2.5


class WindowsActions:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        self.kernel32.GlobalAlloc.restype = ctypes.c_void_p
        self.kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalLock.restype = ctypes.c_void_p
        self.kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        self.user32.SetClipboardData.restype = ctypes.c_void_p
        self.last_window = None

    def key(self, vk):
        self.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        self.user32.keybd_event(vk, 0, 2, 0)

    def combo(self, *keys):
        for key in keys:
            self.user32.keybd_event(key, 0, 0, 0)
            time.sleep(0.02)
        for key in reversed(keys):
            self.user32.keybd_event(key, 0, 2, 0)
            time.sleep(0.02)

    def minimize(self):
        hwnd = self.user32.GetForegroundWindow()
        if hwnd:
            self.last_window = hwnd
            self.user32.ShowWindow(hwnd, SW_MINIMIZE)

    def restore(self):
        hwnd = self.last_window or self.user32.GetForegroundWindow()
        if hwnd:
            self.user32.ShowWindow(hwnd, SW_RESTORE)
            self.user32.SetForegroundWindow(hwnd)

    def close_window(self):
        self.combo(VK_MENU, VK_F4)

    def close_tab(self):
        self.combo(VK_CONTROL, VK_W)

    def switch_tab(self, number):
        number = max(1, min(9, int(number)))
        self.combo(VK_CONTROL, ord(str(number)))

    def move_left(self):
        self.combo(VK_LWIN, VK_LEFT)

    def move_right(self):
        self.combo(VK_LWIN, VK_RIGHT)

    def split_screen(self):
        self.move_left()

    def make_topmost(self):
        hwnd = self.user32.GetForegroundWindow()
        if hwnd:
            self.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        for _ in range(50):
            self.key(VK_VOLUME_DOWN)
        for _ in range(round(percent / 2)):
            self.key(VK_VOLUME_UP)

    def volume_up(self):
        for _ in range(5):
            self.key(VK_VOLUME_UP)

    def volume_down(self):
        for _ in range(5):
            self.key(VK_VOLUME_DOWN)

    def media_toggle(self):
        self.key(VK_MEDIA_PLAY_PAUSE)

    def media_next(self):
        self.key(VK_MEDIA_NEXT_TRACK)

    def media_prev(self):
        self.key(VK_MEDIA_PREV_TRACK)

    def press_space(self):
        self.key(VK_SPACE)

    def press_enter(self):
        self.key(VK_RETURN)

    def focus_window_containing(self, title_parts):
        title_parts = [normalize(part) for part in title_parts if part]
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = normalize(buf.value)
            if any(part in title for part in title_parts):
                found.append(hwnd)
                return False
            return True

        self.user32.EnumWindows(enum_proc, 0)
        if not found:
            return False
        hwnd = found[0]
        self.user32.ShowWindow(hwnd, SW_RESTORE)
        self.user32.SetForegroundWindow(hwnd)
        return hwnd

    def click_window_relative(self, hwnd, rel_x, rel_y):
        rect = RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        width = max(1, rect.right - rect.left)
        height = max(1, rect.bottom - rect.top)
        x = rect.left + int(width * rel_x)
        y = rect.top + int(height * rel_y)
        self.user32.SetCursorPos(x, y)
        time.sleep(0.05)
        self.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        self.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True

    def set_clipboard(self, text):
        self.user32.OpenClipboard(0)
        self.user32.EmptyClipboard()
        data = text + "\0"
        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data) * 2)
        locked = self.kernel32.GlobalLock(handle)
        ctypes.memmove(locked, data.encode("utf-16-le"), len(data) * 2)
        self.kernel32.GlobalUnlock(handle)
        self.user32.SetClipboardData(CF_UNICODETEXT, handle)
        self.user32.CloseClipboard()

    def write_notepad(self, text):
        subprocess.Popen(["notepad.exe"])
        time.sleep(0.8)
        self.set_clipboard(text)
        self.combo(VK_CONTROL, VK_V)


class JarvisAssistant:
    def __init__(self, event_callback=None):
        self.ignore_voice_until = 0
        self.ai = GroqJarvisAI()
        self.audio = EdgeTTSPlayer(on_play=self._mute_voice_for)
        self.win = WindowsActions()
        self.event_callback = event_callback or (lambda event, value=None: None)
        self.active_until = 0
        self.pending_timer = False
        self.pending_plan = False
        self.pending_scenario = None
        self.state = load_state()
        self.language = "ru"
        self.state["language"] = "ru"
        save_state(self.state)
        self.silent_mode = False
        self.memory = load_memory()
        self.ai_history = []
        self.last_heard_text = ""
        self.reminder_timers = []
        self.listener_generation = 0
        self.last_search_query = ""
        self.last_search_results = []
        self.last_result = "Система готова"
        self.running = False
        self.voice_error = ""
        self.listener_thread = None
        self.site_commands = self._build_site_commands()
        self.app_commands = self._build_app_commands()
        self.system_commands = self._build_system_commands()
        self.music_commands = self._build_music_commands()
        self.custom_commands = self._build_custom_commands()
        self.self_voice_phrases = voice_asset_phrases() + [
            "добро пожаловать сэр",
            "я функционирую нормально и готов к работе сэр",
            "да сэр",
            "уже выполняю сэр",
            "всегда к вашим услугам сэр",
            "открываю сайт сэр",
            "отличный план сэр",
            "что на сегодня планируете сэр",
            "на сколько времени вам поставить таймер сэр",
            "хорошо сэр таймер поставлен",
            "отлично я поставил таймер сэр",
            "напоминаю сэр время таймера истекло",
            "хорошего вечера сэр",
            "хорошего дня сэр",
            "я сам вахуйе сэр",
            "включаю сэр",
            "есть",
            "этот запрос мне не понятен сэр",
            "какой вариант выбираете сэр",
            "какой вариант вы выбираете сэр",
            "какой вариант выбираете",
            "как вы хотите отдохнуть сэр",
            "как вы хотите отдохнуть",
            "первый или второй",
            "первый второй или третий вариант",
        ]

    def emit(self, event, value=None):
        self.event_callback(event, value)

    def set_language(self, language):
        self.language = "ru"
        self.state["language"] = "ru"
        save_state(self.state)
        self.silent_mode = False
        self.pending_timer = False
        self.pending_plan = False
        self.pending_scenario = None
        self.site_commands = self._build_site_commands()
        self.app_commands = self._build_app_commands()
        self.system_commands = self._build_system_commands()
        self.music_commands = self._build_music_commands()
        self.listener_generation += 1
        if self.running:
            self.listener_thread = threading.Thread(target=self._voice_loop, args=(self.listener_generation,), daemon=True)
            self.listener_thread.start()
        self.emit("language", "ru")
        self.emit("response", "Русский режим включен.")

    def toggle_language(self):
        self.set_language("ru")

    def play(self, sound_key, force=False):
        if self.silent_mode and not force:
            return False
        fallback = TTS_FALLBACKS.get(sound_key, TTS_FALLBACKS["ok"])
        threading.Thread(target=self._speak_dynamic_ack, args=(sound_key, fallback), daemon=True).start()
        return True

    def say(self, text, force=False):
        if self.silent_mode and not force:
            return False
        return self.audio.speak(text)

    def stop_speaking(self):
        self.audio.stop()
        self.ignore_voice_until = 0
        self.wake()
        self.emit("self_mute", "TTS остановлен. Слушаю команду.")
        self.emit("response", "Слушаю, сэр.")
        return True

    def _speak_dynamic_ack(self, sound_key, fallback):
        phrase = self.ai.command_ack(sound_key, fallback, self.last_heard_text)
        self.say(phrase)

    def _chat_ai(self, text):
        self.emit("response", "Думаю, сэр...")

        def worker():
            answer = self.ai.chat(text, self.ai_history)
            self.ai_history.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": answer},
            ])
            self.ai_history = self.ai_history[-8:]
            self.say(answer)
            self.emit("response", answer)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _mute_voice_for(self, seconds):
        now = time.time()
        self.ignore_voice_until = max(self.ignore_voice_until, now + seconds)
        self.active_until = max(self.active_until, now + seconds + 7)
        self.emit("active", True)
        self.emit("self_mute", f"Игнор микрофона {seconds:.1f} сек.")

    def _is_self_voice(self, text):
        text = normalize(text)
        if not text:
            return False
        has_wake, _ = self._extract_wake_command(text)
        if has_wake:
            return False
        if time.time() < self.ignore_voice_until:
            return True
        if re.search(r"\b(какой|какая|такой|такая)\b.*\b(вариант|выбира\w*|выбера\w*)\b", text):
            return True
        if re.search(r"\b(вариант|выбира\w*|выбера\w*)\b.*\b(сэр|сер|оса|а)\b", text):
            return True
        scenario_prompts = [
            "какой вариант выбираете сэр",
            "какой вариант вы выбираете сэр",
            "какой вариант выбираете",
            "какой вариант вы берете сэр",
            "какой вариант выберите сэр",
            "какой выбирается оса",
            "какой вариант выбирается сер",
            "такой вариант выбирается а",
            "как вы хотите отдохнуть сэр",
            "как вы хотите отдохнуть",
        ]
        if max((ratio(text, phrase) for phrase in scenario_prompts), default=0) >= 0.58:
            return True
        if self._looks_like_user_command(text):
            return False
        best = max((ratio(text, phrase) for phrase in self.self_voice_phrases), default=0)
        if best >= 0.62:
            return True
        return any(len(phrase) >= 6 and (phrase in text or text in phrase) for phrase in self.self_voice_phrases)

    def _looks_like_user_command(self, text):
        command_patterns = [
            r"\b(открой|открыть|запусти|запустить)\b",
            r"\b(закрой|закрыть)\s+(окно|вкладку)\b",
            r"\b(перейди|переключись)\s+на\b.*\bвклад",
            r"\b(ищи|найди|напиши)\b",
            r"\b(запомни|запомнить|запомнил|запомнил)\b",
            r"\b(что\s+я\s+просил\s+запомнить|что\s+ты\s+запомнил|покажи\s+что\s+запомнил)\b",
            r"\b(напомни|режим\s+отдыха|режим\s+работы|тихий\s+режим|отмени|отмена)\b",
            r"\b(как\s+дела|как\s+ты|ты\s+как)\b",
            r"\b(хороший\s+день|добрый\s+день|хорошего\s+дня)\b",
            r"\b(раздели\s+экран|перемести\s+окно|сделай\s+поверх\s+всех)\b",
            r"\b(первый|второй|третий|вариант|сайт|результат|ссылка)\b",
            r"\b(громче|тише|пауза|старт|продолжи|перезагрузка|музыка|музыку|трек|переключи|следующая|следующий|предыдущая|предыдущий|граф|нейроны)\b",
            r"\b(поставь|поставить|запусти|запустить)\b.*\bтаймер\b",
            r"^\s*таймер\b",
            r"\b(аш|қос|ізде|жаз|сақта|еске\s+сал|демалыс\s+режимі|жұмыс\s+режимі|болдырма|қой|тоқтат|жалғастыр)\b",
            r"\b(қойынды|терезе|дыбыс|дауысты|экран|нұсқа|бірінші|екінші|үшінші|музыка|трек|келесі|алдыңғы|граф|нейрон)\b",
        ]
        return any(re.search(pattern, text) for pattern in command_patterns)

    def start(self):
        self.running = True
        self.play("welcome")
        self.emit("language", "ru")
        self.emit("response", "Добро пожаловать, сэр.")
        self.listener_generation += 1
        self.listener_thread = threading.Thread(target=self._voice_loop, args=(self.listener_generation,), daemon=True)
        self.listener_thread.start()

    def stop(self):
        self.running = False

    def is_active(self):
        return time.time() < self.active_until

    def wake(self):
        self.active_until = time.time() + 7
        self.emit("active", True)

    def after_action(self):
        self.wake()

    def _extract_wake_command(self, text):
        text = normalize(text)
        if self.language == "kz":
            wake_words = (
                "алло", "ало", "але", "әй", "ей", "тыңда",
                "джарвис", "жарвис", "джервис", "джарвиз", "jarvis",
            )
        else:
            wake_words = (
                "але", "алле", "алло", "ало", "али", "алей", "алео",
                "джарвис", "жарвис", "джервис", "джарвиз", "жервис", "jarvis",
            )
        positions = []
        for word in wake_words:
            match = re.search(rf"\b{re.escape(word)}\b", text)
            if match:
                positions.append((match.start(), match.end(), word))
        if not positions:
            words = text.split()
            for index, word in enumerate(words[:2]):
                if len(word) < 2:
                    continue
                for wake_word in wake_words:
                    threshold = 0.86 if len(wake_word) <= 3 else 0.74
                    if ratio(word, wake_word) >= threshold:
                        return True, normalize(" ".join(words[index + 1:]))
            return False, text
        _, end, _ = min(positions, key=lambda item: item[0])
        return True, normalize(text[end:])

    def _build_site_commands(self):
        commands = []
        for site in SITES:
            key, title, url, aliases = site
            if self.language == "kz":
                names = [title, key, *KZ_SITE_ALIASES.get(key, [])]
                for name in names:
                    commands.extend([
                        (f"{name} аш", site),
                        (f"{name} сайтын аш", site),
                        (f"браузерде {name} аш", site),
                        (f"{name} қос", site),
                    ])
            else:
                names = [key, title, *aliases]
                for name in names:
                    commands.extend([
                        (f"открой в браузере {name}", site),
                        (f"открой сайт {name}", site),
                        (f"запусти в браузере {name}", site),
                        (f"браузер {name}", site),
                    ])
        return commands

    def _build_app_commands(self):
        commands = []
        for app in APPS:
            key, title, target, aliases = app
            if self.language == "kz":
                names = [title, key, *KZ_APP_ALIASES.get(key, [])]
                for name in names:
                    commands.extend([
                        (f"{name} аш", app),
                        (f"{name} қос", app),
                        (f"{name} қолданбасын аш", app),
                        (f"{name} іске қос", app),
                    ])
            else:
                names = [key, title, *aliases]
                for name in names:
                    commands.extend([
                        (f"открой {name}", app),
                        (f"запусти {name}", app),
                        (f"открой приложение {name}", app),
                        (f"запусти приложение {name}", app),
                    ])
        return commands

    def _build_system_commands(self):
        if self.language == "kz":
            return [
                ("терезені кішірейт", self.win.minimize, "Терезе кішірейтілді.", "good"),
                ("терезені жина", self.win.minimize, "Терезе кішірейтілді.", "good"),
                ("терезені үлкейт", self.win.restore, "Терезе қалпына келтірілді.", "good"),
                ("соңғы терезені аш", self.win.restore, "Терезе қалпына келтірілді.", "good"),
                ("экранды бөл", self.win.split_screen, "Экран бөлінді.", "good"),
                ("терезені солға жылжыт", self.win.move_left, "Терезе солға жылжыды.", "good"),
                ("терезені оңға жылжыт", self.win.move_right, "Терезе оңға жылжыды.", "good"),
                ("бәрінің үстіне қой", self.win.make_topmost, "Терезе үстіне бекітілді.", "good"),
                ("дыбысты көтер", self.win.volume_up, "Дыбыс +10.", "ok"),
                ("дауысты көтер", self.win.volume_up, "Дыбыс +10.", "ok"),
                ("дыбысты азайт", self.win.volume_down, "Дыбыс -10.", "ok"),
                ("дауысты азайт", self.win.volume_down, "Дыбыс -10.", "ok"),
                ("пауза", self.win.media_toggle, "Пауза.", "ok"),
                ("музыканы тоқтат", self.win.media_toggle, "Пауза.", "ok"),
                ("баста", self.win.media_toggle, "Қосылды.", "start"),
                ("жалғастыр", self.win.media_toggle, "Қосылды.", "start"),
                ("қойындыны жап", self.win.close_tab, "Қойынды жабылды.", "good"),
                ("ағымдағы қойындыны жап", self.win.close_tab, "Қойынды жабылды.", "good"),
                ("терезені жап", self.win.close_window, "Терезе жабылды.", "good"),
                ("шағын ойындар", self.open_games, "Шағын ойындар ашылды.", "doing"),
                ("шағын ойындарды аш", self.open_games, "Шағын ойындар ашылды.", "doing"),
                ("ойындарды аш", self.open_games, "Шағын ойындар ашылды.", "doing"),
                ("граф аш", self.open_graph, "Граф ашылды.", "good"),
                ("нейрон граф аш", self.open_graph, "Граф ашылды.", "good"),
                ("нейрондарды көрсет", self.open_graph, "Граф ашылды.", "good"),
                ("қайта жүкте", lambda: subprocess.Popen("shutdown /r /t 5", shell=True), "Қайта жүктеу 5 секундтан кейін.", "ok"),
            ]
        return [
            ("сверни окно", self.win.minimize, "Окно свернуто.", "good"),
            ("сверни текущее окно", self.win.minimize, "Окно свернуто.", "good"),
            ("разверни окно", self.win.restore, "Окно восстановлено.", "good"),
            ("разверни последнее окно", self.win.restore, "Окно восстановлено.", "good"),
            ("раздели экран", self.win.split_screen, "Экран разделен.", "good"),
            ("перемести окно влево", self.win.move_left, "Окно перемещено влево.", "good"),
            ("перемести окно вправо", self.win.move_right, "Окно перемещено вправо.", "good"),
            ("сделай поверх всех", self.win.make_topmost, "Окно закреплено поверх остальных.", "good"),
            ("громче", self.win.volume_up, "Громкость +10.", "ok"),
            ("увеличь громкость", self.win.volume_up, "Громкость +10.", "ok"),
            ("тише", self.win.volume_down, "Громкость -10.", "ok"),
            ("уменьши громкость", self.win.volume_down, "Громкость -10.", "ok"),
            ("пауза", self.win.media_toggle, "Пауза.", "ok"),
            ("останови музыку", self.win.media_toggle, "Пауза.", "ok"),
            ("старт", self.win.media_toggle, "Включаю.", "start"),
            ("продолжи", self.win.media_toggle, "Включаю.", "start"),
            ("закрой вкладку", self.win.close_tab, "Вкладка закрыта.", "good"),
            ("закрыть вкладку", self.win.close_tab, "Вкладка закрыта.", "good"),
            ("закрой текущую вкладку", self.win.close_tab, "Вкладка закрыта.", "good"),
            ("закрой окно", self.win.close_window, "Окно закрыто.", "good"),
            ("закрыть окно", self.win.close_window, "Окно закрыто.", "good"),
            ("мини игры", self.open_games, "Мини игры открыты.", "doing"),
            ("мини игра", self.open_games, "Мини игры открыты.", "doing"),
            ("открой мини игры", self.open_games, "Мини игры открыты.", "doing"),
            ("покажи мини игры", self.open_games, "Мини игры открыты.", "doing"),
            ("открой граф", self.open_graph, "Граф открыт.", "good"),
            ("покажи граф", self.open_graph, "Граф открыт.", "good"),
            ("открой нейро граф", self.open_graph, "Граф открыт.", "good"),
            ("покажи нейроны", self.open_graph, "Граф открыт.", "good"),
            ("перезагрузка", lambda: subprocess.Popen("shutdown /r /t 5", shell=True), "Перезагрузка через 5 секунд.", "ok"),
        ]

    def _build_music_commands(self):
        if self.language == "kz":
            return [
                ("музыка қой", (self.play_yandex_music, "Музыка қосылды.", "good")),
                ("музыка қос", (self.play_yandex_music, "Музыка қосылды.", "good")),
                ("яндекс музыка қос", (self.play_yandex_music, "Музыка қосылды.", "good")),
                ("ән қой", (self.play_yandex_music, "Музыка қосылды.", "good")),
                ("ән қос", (self.play_yandex_music, "Музыка қосылды.", "good")),
                ("келесі музыка", (self.yandex_music_next, "Келесі трек.", "ok")),
                ("келесі трек", (self.yandex_music_next, "Келесі трек.", "ok")),
                ("музыканы ауыстыр", (self.yandex_music_next, "Келесі трек.", "ok")),
                ("әнді ауыстыр", (self.yandex_music_next, "Келесі трек.", "ok")),
                ("алдыңғы музыка", (self.yandex_music_prev, "Алдыңғы трек.", "ok")),
                ("алдыңғы трек", (self.yandex_music_prev, "Алдыңғы трек.", "ok")),
                ("музыканы тоқтат", (self.yandex_music_toggle, "Пауза.", "ok")),
                ("музыканы жалғастыр", (self.yandex_music_toggle, "Қосылды.", "start")),
            ]
        return [
            ("поставь музыку", (self.play_yandex_music, "Музыка включена.", "good")),
            ("включи музыку", (self.play_yandex_music, "Музыка включена.", "good")),
            ("запусти музыку", (self.play_yandex_music, "Музыка включена.", "good")),
            ("поставь яндекс музыку", (self.play_yandex_music, "Музыка включена.", "good")),
            ("включи яндекс музыку", (self.play_yandex_music, "Музыка включена.", "good")),
            ("переключи музыку", (self.yandex_music_next, "Следующий трек.", "ok")),
            ("следующая музыка", (self.yandex_music_next, "Следующий трек.", "ok")),
            ("следующий трек", (self.yandex_music_next, "Следующий трек.", "ok")),
            ("дальше музыка", (self.yandex_music_next, "Следующий трек.", "ok")),
            ("предыдущая музыка", (self.yandex_music_prev, "Предыдущий трек.", "ok")),
            ("предыдущий трек", (self.yandex_music_prev, "Предыдущий трек.", "ok")),
            ("верни музыку", (self.yandex_music_prev, "Предыдущий трек.", "ok")),
            ("пауза музыка", (self.yandex_music_toggle, "Пауза.", "ok")),
            ("останови музыку", (self.yandex_music_toggle, "Пауза.", "ok")),
            ("продолжи музыку", (self.yandex_music_toggle, "Включаю.", "start")),
        ]

    def _music_command(self, text):
        threshold = 0.74 if self.language == "kz" else 0.78
        score, command, phrase = best_phrase(text, self.music_commands, threshold=threshold)
        if not command:
            return False
        fn, message, sound = command
        self.play(sound)
        ok = fn()
        if ok is False:
            self.emit("response", "Яндекс Музыка не найдена. Сначала скажите: поставь музыку." if self.language == "ru" else "Яндекс Музыка табылмады. Алдымен: музыка қой.")
        else:
            self.emit("response", f"{message} ({score:.0%}, {phrase})")
        return True

    def _build_custom_commands(self):
        commands = []
        for item in load_custom_commands():
            name = item.get("name", "")
            aliases = item.get("aliases", [])
            for phrase in [name, *aliases]:
                if phrase:
                    commands.append((phrase, item))
        return commands

    def handle_text(self, raw_text, force=False, source="manual"):
        text = normalize(raw_text)
        if not text:
            return
        if source == "voice" and self._is_self_voice(text):
            self.emit("ignored", text)
            return
        self.last_heard_text = text
        self.emit("heard", text)

        if self.pending_timer:
            if self._set_timer_from_text(text):
                return

        has_wake, wake_command = self._extract_wake_command(text)

        if source == "voice" and not has_wake and not self.is_active() and not self.pending_timer and not self.pending_plan and not self.pending_scenario:
            self.emit("ignored", text)
            return

        if force:
            self.wake()
        elif has_wake:
            self.wake()
            text = wake_command
            if not text:
                self.play("help")
                self.emit("response", "Чем могу помочь, сэр?")
                return
        elif source != "voice":
            self.wake()

        handled = self._dispatch(text)
        if handled:
            self.after_action()
        else:
            self._chat_ai(text)
            self.after_action()

    def _dispatch(self, text):
        if self._language_command_ru(text):
            return True

        if self._cancel_command(text):
            return True

        if self._silent_command(text):
            return True

        if self.pending_scenario:
            return self._handle_scenario_choice(text)

        if self.pending_plan:
            self.pending_plan = False
            self.play("plan")
            self.emit("response", "Отличный план, сэр.")
            return True

        response = self._response_command(text)
        if response:
            return True

        if self._remember_command(text):
            return True

        if self._show_memory_command(text):
            return True

        if self._reminder_command(text):
            return True

        if self._scenario_command(text):
            return True

        if self._wiki_command(text):
            return True

        if ratio(text, "поставь таймер") >= 0.80 or text.startswith("таймер") or ("таймер" in text and ("постав" in text or "запусти" in text)):
            if self._set_timer_from_text(text):
                return True
            self.pending_timer = True
            self.play("ask_timer")
            self.emit("response", "На сколько времени поставить таймер, сэр?")
            return True

        if self._music_command(text):
            return True

        if text.startswith("ищи ") or text.startswith("найди "):
            query = re.sub(r"^(ищи|найди)\s+", "", text).strip()
            if query:
                self.last_search_query = query
                self.last_search_results = []
                threading.Thread(target=self._cache_search_results, args=(query,), daemon=True).start()
                self.play("doing")
                self.open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
                self.emit("response", f"Ищу: {query}")
                return True

        result_number = parse_search_result_number(text)
        if result_number:
            self.play("good")
            ok = self.open_search_result(result_number)
            if ok:
                self.emit("response", f"Открываю результат поиска номер {result_number}.")
            else:
                self.emit("response", "Не нашел сохраненный поиск, сэр. Сначала скажите: ищи ...")
            return True

        if text.startswith("напиши "):
            phrase = text.replace("напиши", "", 1).strip()
            if phrase:
                self.play("yes")
                self.win.write_notepad(phrase)
                self.emit("response", f"Написал: {phrase}")
                return True

        self.custom_commands = self._build_custom_commands()
        score, custom, phrase = best_phrase(text, self.custom_commands, threshold=0.80)
        if custom:
            sound = custom.get("sound", "ok")
            self.play(sound)
            if custom.get("kind") == "app":
                ok = self.open_app(custom.get("target", ""))
            else:
                ok = self.open_url(custom.get("target", ""))
            self.emit("response", f"Custom: {custom.get('name', phrase)} ({score:.0%})" if ok else "Custom command failed")
            return True

        tab_number = parse_tab_number(text)
        if tab_number and "вклад" in text and max(ratio(text, "перейди на первую вкладку"), ratio(text, "переключись на первую вкладку")) >= 0.62:
            self.play("good")
            self.win.switch_tab(tab_number)
            self.emit("response", f"Перехожу на вкладку {tab_number}.")
            return True

        score, site, phrase = best_phrase(text, self.site_commands, threshold=0.80)
        if site:
            self.play("good")
            ok = self.open_url(site[2])
            self.emit("response", f"Открываю сайт: {site[1]} ({score:.0%}, {phrase})" if ok else f"Не смог открыть сайт: {site[1]}")
            return True

        if "браузер" in text or ratio(text[:18], "открой в браузере") >= 0.72:
            target = strip_words(text, ["открой", "открыть", "запусти", "запустить", "в", "браузер", "браузере", "сайт"])
            score, site, phrase = best_match(target, SITES, threshold=0.72)
            if site:
                self.play("good")
                ok = self.open_url(site[2])
                self.emit("response", f"Открываю сайт: {site[1]} ({score:.0%})" if ok else f"Не смог открыть сайт: {site[1]}")
                return True

        score, app, phrase = best_phrase(text, self.app_commands, threshold=0.80)
        if app:
            self.play("doing")
            ok = self.open_app(app[2])
            self.emit("response", f"Открываю приложение: {app[1]} ({score:.0%}, {phrase})" if ok else f"Не смог открыть приложение: {app[1]}")
            return True

        if text.startswith("открой") or text.startswith("запусти") or ratio(text[:8], "открой") >= 0.74:
            target = strip_words(text, ["открой", "открыть", "запусти", "запустить", "приложение"])
            score, app, phrase = best_match(target, APPS, threshold=0.72)
            if app:
                self.play("doing")
                ok = self.open_app(app[2])
                self.emit("response", f"Открываю приложение: {app[1]} ({score:.0%})" if ok else f"Не смог открыть приложение: {app[1]}")
                return True

        best = max(((ratio(text, name), name, fn, msg, sound) for name, fn, msg, sound in self.system_commands), key=lambda x: x[0])
        if best[0] >= 0.80:
            self.play(best[4])
            best[2]()
            self.emit("response", f"{best[3]} ({best[0]:.0%})")
            return True

        return False

    def _wiki_command(self, text):
        query = parse_wiki_query(text)
        if not query:
            return False
        self.emit("response", f"Ищу в Википедии: {query}")

        def worker():
            result = find_wikipedia(query)
            if not result:
                message = "Не нашёл в Википедии, сэр."
                self.emit("wiki_card", {
                    "title": "Wikipedia",
                    "description": "",
                    "extract": message,
                    "url": "",
                    "image_path": "",
                })
                self.emit("response", message)
                self.say(message)
                return
            text_to_say = result.get("extract", "")
            self.emit("wiki_card", result)
            self.emit("response", text_to_say)
            self.say(text_to_say)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _response_command(self, text):
        responses = [
            (["как ты", "как дела", "ты как"], "status_ok", "Я функционирую нормально и готов к работе, сэр."),
            (["джарвис че за фигня", "что за фигня", "че за фигня"], "confused", "Я сам вахуйе, сэр."),
            (["хороший день", "добрый день", "хорошего дня", "хороший день сэр", "добрый день сэр"], "ask_plan", "Что на сегодня планируете, сэр."),
            (["спасибо", "благодарю"], "thanks", "Всегда к вашим услугам, сэр."),
        ]
        for aliases, sound, message in responses:
            if max(ratio(text, alias) for alias in aliases) >= 0.80:
                self.play(sound)
                self.emit("response", message)
                if sound == "ask_plan":
                    self.pending_plan = True
                return True
        return False

    def _language_command_ru(self, text):
        if max(ratio(text, "казахский режим"), ratio(text, "казахский язык"), ratio(text, "включи казахский режим")) >= 0.78:
            self.play("unknown")
            self.emit("response", "Казахский режим отключён, сэр. Сейчас доступен только русский режим.")
            return True
        return False

    def _cancel_command(self, text):
        if max(ratio(text, "отмени"), ratio(text, "отмена"), ratio(text, "сбрось")) < 0.82:
            return False
        self.pending_timer = False
        self.pending_plan = False
        self.pending_scenario = None
        if self.reminder_timers:
            timer = self.reminder_timers.pop()
            timer.cancel()
        self.play("good", force=True)
        self.emit("response", "Отменяю, сэр.")
        return True

    def _silent_command(self, text):
        if "тихий" not in text and "голос" not in text:
            return False
        if "выключ" in text or "отключ" in text or "говори" in text or "голос" in text and "включ" in text:
            self.silent_mode = False
            self.play("good", force=True)
            self.emit("response", "Тихий режим выключен.")
            return True
        if "тихий" in text and ("режим" in text or "включ" in text):
            self.play("good", force=True)
            self.silent_mode = True
            self.emit("response", "Тихий режим включен.")
            return True
        return False

    def _remember_command(self, text):
        if not text.startswith("запомни "):
            return False
        note = text.replace("запомни", "", 1).strip()
        if not note:
            return False
        self.memory["note"] = note
        save_memory(self.memory)
        self.play("remembered")
        self.emit("response", f"Запомнил: {note}")
        return True

    def _show_memory_command(self, text):
        aliases = [
            "что я просил запомнить",
            "что просил запомнить",
            "что я попросил запомнить",
            "что ты запомнил",
            "покажи что запомнил",
            "покажи заметку",
            "напомни что я просил запомнить",
        ]
        if max(ratio(text, alias) for alias in aliases) < 0.78:
            return False
        note = self.memory.get("note", "").strip()
        if not note:
            self.play("unknown")
            self.emit("response", "Пока нечего показывать, сэр.")
            return True
        self.play("remember_show")
        self.win.write_notepad(note)
        self.emit("response", f"Вы просили запомнить: {note}")
        return True

    def _reminder_command(self, text):
        parsed = parse_reminder(text)
        if not parsed:
            return False
        message, seconds = parsed
        timer = threading.Timer(seconds, lambda: self._reminder_done(message))
        timer.daemon = True
        timer.start()
        self.reminder_timers.append(timer)
        self.play("reminder_set")
        self.emit("response", f"Напомню через {format_duration(seconds)}: {message}")
        return True

    def _scenario_command(self, text):
        rest_score = max(ratio(text, "режим отдыха"), ratio(text, "отдых"), ratio(text, "режим отдохнуть"))
        work_score = max(ratio(text, "режим работы"), ratio(text, "работа"), ratio(text, "рабочий режим"))
        if rest_score >= 0.80:
            self.pending_scenario = "rest"
            self.play("rest_choice")
            self.emit("response", "Как вы хотите отдохнуть, сэр? Первый, второй или третий вариант.")
            return True
        if work_score >= 0.80:
            self.pending_scenario = "work"
            self.play("work_choice")
            self.emit("response", "Какой вариант выбираете, сэр? Первый или второй.")
            return True
        return False

    def _handle_scenario_choice(self, text):
        number = parse_option_number(text)
        scenario = self.pending_scenario
        if not number:
            self.play("work_choice" if scenario == "work" else "rest_choice")
            self.emit("response", "Скажите номер варианта, сэр.")
            return True
        self.pending_scenario = None
        if scenario == "rest":
            return self._run_rest_scenario(number)
        if scenario == "work":
            return self._run_work_scenario(number)
        return False

    def _run_rest_scenario(self, number):
        if number == 1:
            self.open_site_key("youtube")
            self.win.set_volume(55)
        elif number == 2:
            self.open_site_key("kinopoisk")
            self.open_bluetooth_settings()
            self.win.set_volume(60)
        elif number == 3:
            self.open_app_key("steam")
            self.open_site_key("yandex_music")
        else:
            self.play("rest_choice")
            self.emit("response", "Для отдыха есть только три варианта, сэр.")
            return True
        self.play("rest_done")
        self.emit("response", f"Режим отдыха, вариант {number}, выполнен.")
        return True

    def _run_work_scenario(self, number):
        if number == 1:
            self.open_app_key("claude")
        elif number == 2:
            self.open_app_key("codex")
        else:
            self.play("work_choice")
            self.emit("response", "Для работы есть только два варианта, сэр.")
            return True
        self.open_app_key("vscode")
        self.open_site_key("yandex_music")
        self.play("work_done")
        self.emit("response", f"Режим работы, вариант {number}, выполнен.")
        return True

    def _dispatch_kz(self, text):
        if self._language_command_kz(text):
            return True
        if self._cancel_command_kz(text):
            return True
        if self.pending_scenario:
            return self._handle_scenario_choice_kz(text)
        if self._remember_command_kz(text):
            return True
        if self._show_memory_command_kz(text):
            return True
        if self._reminder_command_kz(text):
            return True
        if self._scenario_command_kz(text):
            return True

        if ratio(text, "таймер қой") >= 0.78 or text.startswith("таймер") or ("таймер" in text and ("қой" in text or "баста" in text)):
            if self._set_timer_from_text_kz(text):
                return True
            self.pending_timer = True
            self.emit("response", "Таймерді қанша уақытқа қояйын?")
            return True

        if self._music_command(text):
            return True

        if text.startswith("ізде ") or text.startswith("тауып бер "):
            query = re.sub(r"^(ізде|тауып бер)\s+", "", text).strip()
            if query:
                self.last_search_query = query
                self.last_search_results = []
                threading.Thread(target=self._cache_search_results, args=(query,), daemon=True).start()
                self.open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
                self.emit("response", f"Іздеп жатырмын: {query}")
                return True

        result_number = parse_search_result_number_kz(text)
        if result_number:
            ok = self.open_search_result(result_number)
            self.emit("response", f"Іздеу нәтижесі {result_number} ашылды." if ok else "Алдымен іздеу жасаңыз.")
            return True

        if text.startswith("жаз "):
            phrase = text.replace("жаз", "", 1).strip()
            if phrase:
                self.win.write_notepad(phrase)
                self.emit("response", f"Жазылды: {phrase}")
                return True

        tab_number = parse_option_number_kz(text)
        if tab_number and "қойынды" in text and max(ratio(text, "бірінші қойындыға өт"), ratio(text, "қойындыға ауыс")) >= 0.58:
            self.win.switch_tab(tab_number)
            self.emit("response", f"{tab_number} қойындыға өттім.")
            return True

        score, site, phrase = best_phrase(text, self.site_commands, threshold=0.76)
        if site:
            ok = self.open_url(site[2])
            self.emit("response", f"Сайт ашылды: {site[1]} ({score:.0%})" if ok else f"Сайт ашылмады: {site[1]}")
            return True

        if "браузер" in text or ratio(text[-12:], "сайт аш") >= 0.64:
            target = strip_words(text, ["аш", "қос", "браузер", "браузерде", "сайт", "сайтын"])
            score, site, phrase = best_match_kz(target, SITES, KZ_SITE_ALIASES, threshold=0.68)
            if site:
                ok = self.open_url(site[2])
                self.emit("response", f"Сайт ашылды: {site[1]} ({score:.0%})" if ok else f"Сайт ашылмады: {site[1]}")
                return True

        score, app, phrase = best_phrase(text, self.app_commands, threshold=0.76)
        if app:
            ok = self.open_app(app[2])
            self.emit("response", f"Қолданба ашылды: {app[1]} ({score:.0%})" if ok else f"Қолданба ашылмады: {app[1]}")
            return True

        if text.endswith("аш") or text.endswith("қос") or "қолданба" in text:
            target = strip_words(text, ["аш", "қос", "іске", "қолданба", "қолданбасын"])
            score, app, phrase = best_match_kz(target, APPS, KZ_APP_ALIASES, threshold=0.68)
            if app:
                ok = self.open_app(app[2])
                self.emit("response", f"Қолданба ашылды: {app[1]} ({score:.0%})" if ok else f"Қолданба ашылмады: {app[1]}")
                return True

        if self.system_commands:
            best = max(((ratio(text, name), name, fn, msg, sound) for name, fn, msg, sound in self.system_commands), key=lambda x: x[0])
            if best[0] >= 0.76:
                best[2]()
                self.emit("response", f"{best[3]} ({best[0]:.0%})")
                return True

        return False

    def _language_command_kz(self, text):
        if max(ratio(text, "орысша режим"), ratio(text, "орыс тілі"), ratio(text, "орыс режимі")) >= 0.78:
            self.set_language("ru")
            return True
        return False

    def _cancel_command_kz(self, text):
        if max(ratio(text, "болдырма"), ratio(text, "тоқтат"), ratio(text, "алып таста")) < 0.78:
            return False
        self.pending_timer = False
        self.pending_plan = False
        self.pending_scenario = None
        if self.reminder_timers:
            timer = self.reminder_timers.pop()
            timer.cancel()
        self.emit("response", "Болдырмадым.")
        return True

    def _remember_command_kz(self, text):
        prefixes = ("есте сақта ", "сақтап қой ", "сақта ")
        prefix = next((p for p in prefixes if text.startswith(p)), "")
        if not prefix:
            return False
        note = text.replace(prefix, "", 1).strip()
        if not note:
            return False
        self.memory["note_kz"] = note
        save_memory(self.memory)
        self.emit("response", f"Есте сақтадым: {note}")
        return True

    def _show_memory_command_kz(self, text):
        aliases = ["не есте сақтадың", "мен не есте сақта дедім", "сақтағанымды көрсет", "есте сақтағанды көрсет", "заметканы көрсет"]
        if max(ratio(text, alias) for alias in aliases) < 0.74:
            return False
        note = (self.memory.get("note_kz") or self.memory.get("note", "")).strip()
        if not note:
            self.emit("response", "Әзірге ештеңе сақталған жоқ.")
            return True
        self.win.write_notepad(note)
        self.emit("response", f"Сіз есте сақтауды сұрадыңыз: {note}")
        return True

    def _reminder_command_kz(self, text):
        parsed = parse_reminder_kz(text)
        if not parsed:
            return False
        message, seconds = parsed
        timer = threading.Timer(seconds, lambda: self._reminder_done_kz(message))
        timer.daemon = True
        timer.start()
        self.reminder_timers.append(timer)
        self.emit("response", f"{format_duration_kz(seconds)} кейін еске саламын: {message}")
        return True

    def _scenario_command_kz(self, text):
        rest_score = max(ratio(text, "демалыс режимі"), ratio(text, "демалу режимі"), ratio(text, "демалыс"))
        work_score = max(ratio(text, "жұмыс режимі"), ratio(text, "жұмыс"), ratio(text, "жұмысқа режим"))
        if rest_score >= 0.76:
            self.pending_scenario = "rest"
            self.emit("response", "Қалай демалғыңыз келеді? Бірінші, екінші немесе үшінші нұсқа.")
            return True
        if work_score >= 0.76:
            self.pending_scenario = "work"
            self.emit("response", "Қай нұсқаны таңдайсыз? Бірінші немесе екінші.")
            return True
        return False

    def _handle_scenario_choice_kz(self, text):
        number = parse_option_number_kz(text)
        scenario = self.pending_scenario
        if not number:
            self.emit("response", "Нұсқа нөмірін айтыңыз.")
            return True
        self.pending_scenario = None
        if scenario == "rest":
            return self._run_rest_scenario_kz(number)
        if scenario == "work":
            return self._run_work_scenario_kz(number)
        return False

    def _run_rest_scenario_kz(self, number):
        if number == 1:
            self.open_site_key("youtube")
            self.win.set_volume(55)
        elif number == 2:
            self.open_site_key("kinopoisk")
            self.open_bluetooth_settings()
            self.win.set_volume(60)
        elif number == 3:
            self.open_app_key("steam")
            self.open_site_key("yandex_music")
        else:
            self.emit("response", "Демалыс режимінде үш нұсқа бар.")
            return True
        self.emit("response", f"Демалыс режимі, {number} нұсқа орындалды.")
        return True

    def _run_work_scenario_kz(self, number):
        if number == 1:
            self.open_app_key("claude")
        elif number == 2:
            self.open_app_key("codex")
        else:
            self.emit("response", "Жұмыс режимінде екі нұсқа бар.")
            return True
        self.open_app_key("vscode")
        self.open_site_key("yandex_music")
        self.emit("response", f"Жұмыс режимі, {number} нұсқа орындалды.")
        return True

    def _set_timer_from_text(self, text):
        seconds = parse_duration(text)
        if not seconds:
            return False
        self.pending_timer = False
        self.play("timer_set")
        self.emit("response", f"Таймер поставлен на {format_duration(seconds)}.")
        timer = threading.Timer(seconds, self._timer_done)
        timer.daemon = True
        timer.start()
        return True

    def _timer_done(self):
        self.play("timer_done")
        self.emit("response", "Напоминаю, сэр, время таймера истекло.")

    def _set_timer_from_text_kz(self, text):
        seconds = parse_duration_kz(text)
        if not seconds:
            return False
        self.pending_timer = False
        self.emit("response", f"Таймер {format_duration_kz(seconds)} уақытқа қойылды.")
        timer = threading.Timer(seconds, self._timer_done_kz)
        timer.daemon = True
        timer.start()
        return True

    def _timer_done_kz(self):
        self.emit("response", "Еске саламын, таймер уақыты бітті.")

    def _reminder_done(self, message):
        self.win.media_toggle()
        self.play("reminder_due", force=True)
        self.win.write_notepad(message)
        self.emit("response", f"Вы просили напомнить: {message}")

    def _reminder_done_kz(self, message):
        self.win.media_toggle()
        self.win.write_notepad(message)
        self.emit("response", f"Сіз еске салуды сұрадыңыз: {message}")

    def play_yandex_music(self):
        ok = self.open_yandex_music_window()
        if ok:
            timer = threading.Timer(4.5, self.yandex_music_start)
            timer.daemon = True
            timer.start()
        return ok

    def open_yandex_music_window(self):
        url = "https://music.yandex.kz/"
        try:
            for browser in BROWSER_PATHS:
                path = Path(browser)
                if path.exists():
                    subprocess.Popen([str(path), "--new-window", f"--app={url}"])
                    return True
            webbrowser.open(url)
            return True
        except Exception as exc:
            self.emit("response", f"Ошибка открытия Яндекс Музыки: {exc}")
            return False

    def open_graph(self):
        script = Path(__file__).with_name("jarvis_graph.py")
        if not script.exists():
            self.emit("response", "Модуль графа не найден.")
            return False
        try:
            subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent))
            return True
        except Exception as exc:
            self.emit("response", f"Ошибка открытия графа: {exc}")
            return False

    def open_games(self):
        self.emit("open_games", True)
        return True

    def focus_yandex_music_window(self):
        return self.win.focus_window_containing(("Яндекс Музыка", "Yandex Music", "music.yandex"))

    def yandex_music_start(self):
        hwnd = self.focus_yandex_music_window()
        if not hwnd:
            return False
        time.sleep(0.3)
        if self.win.click_window_relative(hwnd, 0.58, 0.37):
            return True
        return False

    def yandex_music_toggle(self):
        hwnd = self.focus_yandex_music_window()
        if hwnd:
            time.sleep(0.15)
            self.win.press_space()
            return True
        return False

    def yandex_music_next(self):
        if self.focus_yandex_music_window():
            time.sleep(0.15)
            self.win.media_next()
            return True
        return False

    def yandex_music_prev(self):
        if self.focus_yandex_music_window():
            time.sleep(0.15)
            self.win.media_prev()
            return True
        return False

    def open_url(self, url):
        try:
            for browser in BROWSER_PATHS:
                if Path(browser).exists():
                    subprocess.Popen([browser, url])
                    return True
            webbrowser.open(url)
            return True
        except Exception as exc:
            self.emit("response", f"Ошибка открытия сайта: {exc}")
            return False

    def open_site_key(self, key):
        for site in SITES:
            if site[0] == key:
                return self.open_url(site[2])
        return False

    def open_app_key(self, key):
        for app in APPS:
            if app[0] == key:
                return self.open_app(app[2])
        return False

    def open_bluetooth_settings(self):
        try:
            subprocess.Popen(["explorer.exe", "ms-settings:bluetooth"])
            return True
        except Exception as exc:
            self.emit("response", f"Ошибка открытия Bluetooth: {exc}")
            return False

    def _cache_search_results(self, query):
        results = self._fetch_search_results(query)
        if query == self.last_search_query:
            self.last_search_results = results

    def open_search_result(self, number):
        if not self.last_search_query:
            return False
        if len(self.last_search_results) < number:
            self.last_search_results = self._fetch_search_results(self.last_search_query)
        if len(self.last_search_results) < number:
            return False
        return self.open_url(self.last_search_results[number - 1])

    def _fetch_search_results(self, query, limit=10):
        for fetcher in (self._fetch_google_results, self._fetch_duckduckgo_results, self._fetch_bing_results):
            results = fetcher(query, limit)
            if results:
                return results[:limit]
        return []

    def _read_search_page(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _fetch_google_results(self, query, limit):
        page = self._read_search_page("https://www.google.com/search?num=10&hl=ru&q=" + urllib.parse.quote_plus(query))
        results = []
        for match in re.finditer(r'<a href="/url\?q=([^"&]+)', page):
            url = html.unescape(urllib.parse.unquote(match.group(1)))
            if self._is_search_result_url(url):
                results.append(url)
            if len(results) >= limit:
                break
        return unique_urls(results)

    def _fetch_duckduckgo_results(self, query, limit):
        page = self._read_search_page("https://duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query))
        results = []
        for match in re.finditer(r'class="result__a"[^>]+href="([^"]+)"', page):
            url = html.unescape(match.group(1))
            if url.startswith("//"):
                url = "https:" + url
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if "uddg" in params:
                url = params["uddg"][0]
            if self._is_search_result_url(url):
                results.append(url)
            if len(results) >= limit:
                break
        return unique_urls(results)

    def _fetch_bing_results(self, query, limit):
        page = self._read_search_page("https://www.bing.com/search?q=" + urllib.parse.quote_plus(query))
        results = []
        for match in re.finditer(r'<li class="b_algo"[\s\S]*?<h2>[\s\S]*?<a href="([^"]+)"', page):
            url = html.unescape(match.group(1))
            if self._is_search_result_url(url):
                results.append(url)
            if len(results) >= limit:
                break
        return unique_urls(results)

    def _is_search_result_url(self, url):
        if not url.startswith(("http://", "https://")):
            return False
        host = urllib.parse.urlparse(url).netloc.lower()
        blocked = ("google.", "gstatic.", "bing.com", "microsoft.com", "duckduckgo.com")
        return not any(item in host for item in blocked)

    def open_app(self, target):
        try:
            if target.startswith("http"):
                return self.open_url(target)
            if target.startswith("shell:"):
                subprocess.Popen(["explorer.exe", target])
                return True
            if Path(target).exists():
                os.startfile(target)
                return True
            subprocess.Popen(f'start "" "{target}"', shell=True)
            return True
        except Exception as exc:
            self.emit("response", f"Ошибка открытия приложения: {exc}")
            return False

    def _nearest_hint(self, text):
        candidates = []
        candidates.extend(self.site_commands)
        candidates.extend(self.app_commands)
        candidates.extend(self.custom_commands)
        candidates.extend((name, name) for name, *_ in self.system_commands)
        score, payload, phrase = best_phrase(text, candidates, threshold=0.0)
        return f"{phrase} ({score:.0%})" if phrase else "нет"

    def _voice_loop(self, generation=None):
        try:
            import sounddevice as sd
            import vosk
        except Exception as exc:
            self.voice_error = f"Нет голосовых библиотек: {exc}"
            self.emit("voice_error", self.voice_error)
            return

        model_path = model_path_for(self.language)
        if not model_path.exists():
            self.voice_error = f"Модель Vosk не найдена: {model_path}"
            self.emit("voice_error", self.voice_error)
            return

        audio_q = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                self.emit("voice_error", str(status))
            audio_q.put(bytes(indata))

        try:
            model = vosk.Model(str(model_path))
            recognizer = vosk.KaldiRecognizer(model, 16000)
            self.emit("voice_ready", "Vosk слушает микрофон.")
            with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16", channels=1, callback=callback):
                while self.running and (generation is None or generation == self.listener_generation):
                    data = audio_q.get()
                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        self.handle_text(result.get("text", ""), source="voice")
        except Exception as exc:
            self.voice_error = f"Ошибка микрофона: {exc}"
            self.emit("voice_error", self.voice_error)


NUMBERS = {
    "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "пятнадцать": 15,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
}

TAB_NUMBERS = {
    "один": 1, "одну": 1, "первая": 1, "первую": 1, "первой": 1,
    "два": 2, "две": 2, "вторая": 2, "вторую": 2, "второй": 2,
    "три": 3, "третья": 3, "третью": 3, "третьей": 3,
    "четыре": 4, "четвертая": 4, "четвертую": 4, "четвертой": 4,
    "пять": 5, "пятая": 5, "пятую": 5, "пятой": 5,
    "шесть": 6, "шестая": 6, "шестую": 6, "шестой": 6,
    "семь": 7, "седьмая": 7, "седьмую": 7, "седьмой": 7,
    "восемь": 8, "восьмая": 8, "восьмую": 8, "восьмой": 8,
    "девять": 9, "девятая": 9, "девятую": 9, "девятой": 9,
}

RESULT_NUMBERS = {
    **TAB_NUMBERS,
    "десять": 10, "десятая": 10, "десятую": 10, "десятый": 10, "десятой": 10,
}


def parse_tab_number(text):
    text = normalize(text)
    match = re.search(r"\b([1-9])\b", text)
    if match:
        return int(match.group(1))
    words = text.split()
    best = (0.0, None)
    for word in words:
        for name, value in TAB_NUMBERS.items():
            score = ratio(word, name)
            if score > best[0]:
                best = (score, value)
    return best[1] if best[0] >= 0.72 else None


def parse_search_result_number(text):
    text = normalize(text)
    if not any(word in text for word in ("сайт", "результат", "ссылк")):
        return None
    command_score = max(ratio(text[:18], "открой первый сайт"), ratio(text[:22], "перейди на первый сайт"))
    if command_score < 0.58 and not re.search(r"\b(открой|открыть|перейди|запусти|зайди)\b", text):
        return None
    match = re.search(r"\b(10|[1-9])\b", text)
    if match:
        return int(match.group(1))
    best = (0.0, None)
    for word in text.split():
        for name, value in RESULT_NUMBERS.items():
            score = ratio(word, name)
            if score > best[0]:
                best = (score, value)
    return best[1] if best[0] >= 0.72 else None


def unique_urls(urls):
    unique = []
    seen = set()
    for url in urls:
        clean = url.strip()
        if clean and clean not in seen:
            unique.append(clean)
            seen.add(clean)
    return unique


def parse_option_number(text):
    text = normalize(text)
    match = re.search(r"\b([1-9])\b", text)
    if match:
        return int(match.group(1))
    best = (0.0, None)
    for word in text.split():
        for name, value in RESULT_NUMBERS.items():
            score = ratio(word, name)
            if score > best[0]:
                best = (score, value)
    return best[1] if best[0] >= 0.72 else None


def parse_reminder(text):
    text = normalize(text)
    if not text.startswith("напомни "):
        return None
    body = text.replace("напомни", "", 1).strip()
    if not body:
        return None
    match = re.search(r"(.+?)\s+через\s+(.+)$", body)
    if match:
        message = match.group(1).strip()
        seconds = parse_duration(match.group(2))
        return (message, seconds) if message and seconds else None
    match = re.search(r"через\s+((?:\d+|\w+)\s+\w+)\s+(.+)$", body)
    if match:
        seconds = parse_duration(match.group(1))
        message = match.group(2).strip()
        return (message, seconds) if message and seconds else None
    return None


def parse_duration(text):
    text = normalize(text)
    match = re.search(r"(\d+)\s*(сек|секунд|мин|мину|минут|час)", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
    else:
        amount, unit = None, ""
        words = text.split()
        for i, word in enumerate(words):
            if word in NUMBERS:
                amount = NUMBERS[word]
                unit = words[i + 1] if i + 1 < len(words) else ""
                break
    if not amount:
        return None
    if unit.startswith("час"):
        return amount * 3600
    if unit.startswith("мин"):
        return amount * 60
    return amount


def format_duration(seconds):
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600} ч"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60} мин"
    return f"{seconds} сек"


KZ_NUMBERS = {
    "бір": 1, "бірінші": 1, "екі": 2, "екінші": 2, "үш": 3, "үшінші": 3,
    "төрт": 4, "төртінші": 4, "бес": 5, "бесінші": 5, "алты": 6, "алтыншы": 6,
    "жеті": 7, "жетінші": 7, "сегіз": 8, "сегізінші": 8, "тоғыз": 9, "тоғызыншы": 9,
    "он": 10, "оныншы": 10, "он бес": 15, "жиырма": 20, "отыз": 30, "қырық": 40,
    "елу": 50, "алпыс": 60,
}


def best_match_kz(query, items, aliases_by_key, threshold=0.76):
    best = (0.0, None, "")
    for item in items:
        key, title, value, aliases = item
        names = [title, key, *aliases_by_key.get(key, [])]
        for alias in names:
            score = ratio(query, alias)
            if score > best[0]:
                best = (score, item, alias)
    return best if best[0] >= threshold else (best[0], None, best[2])


def parse_option_number_kz(text):
    text = normalize(text)
    match = re.search(r"\b(10|[1-9])\b", text)
    if match:
        return int(match.group(1))
    best = (0.0, None)
    words = text.split()
    phrases = words + [" ".join(words[i:i + 2]) for i in range(max(0, len(words) - 1))]
    for phrase in phrases:
        for name, value in KZ_NUMBERS.items():
            score = ratio(phrase, name)
            if score > best[0]:
                best = (score, value)
    return best[1] if best[0] >= 0.70 else None


def parse_search_result_number_kz(text):
    text = normalize(text)
    if not any(word in text for word in ("сайт", "нәтиже", "сілтеме")):
        return None
    if not any(word in text for word in ("аш", "өт", "қос")):
        return None
    return parse_option_number_kz(text)


def parse_duration_kz(text):
    text = normalize(text)
    match = re.search(r"(\d+)\s*(сек|секунд|мин|минут|сағат)", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
    else:
        amount, unit = None, ""
        words = text.split()
        for i, word in enumerate(words):
            value = KZ_NUMBERS.get(word)
            if value:
                amount = value
                unit = words[i + 1] if i + 1 < len(words) else ""
                break
    if not amount:
        return None
    if unit.startswith("сағат"):
        return amount * 3600
    if unit.startswith("мин"):
        return amount * 60
    return amount


def parse_reminder_kz(text):
    text = normalize(text)
    if "еске сал" not in text:
        return None
    body = text.replace("еске сал", "", 1).strip()
    if not body:
        return None
    match = re.search(r"(.+?)\s+(\d+|\w+)\s+(сек|секунд|мин|минут|сағат)\s*(кейін|соң)$", body)
    if match:
        message = match.group(1).strip()
        seconds = parse_duration_kz(" ".join(match.group(i) for i in (2, 3)))
        return (message, seconds) if message and seconds else None
    match = re.search(r"(\d+|\w+)\s+(сек|секунд|мин|минут|сағат)\s*(кейін|соң)\s+(.+)$", body)
    if match:
        seconds = parse_duration_kz(" ".join(match.group(i) for i in (1, 2)))
        message = match.group(4).strip()
        return (message, seconds) if message and seconds else None
    return None


def format_duration_kz(seconds):
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600} сағат"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60} минут"
    return f"{seconds} секунд"
