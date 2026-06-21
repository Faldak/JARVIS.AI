import datetime as dt
import json
import math
import random
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

from PIL import Image, ImageTk

from jarvis_assistant import JarvisAssistant
from jarvis_settings import JarvisSettings


THEMES = {
    "Cyan": {"accent": "#5fd5e0", "dim2": "#2a5560", "warn": "#d9b96e", "ok": "#7adcb0"},
}

BG = "#06080a"
BG_2 = "#0c1014"
PANEL = "#090d11"
TEXT = "#d6e0e7"
DIM = "#5a6772"
FAINT = "#1c2228"


def mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


def hex_points(cx, cy, r, rot=0):
    out = []
    for i in range(6):
        a = math.radians(60 * i + rot - 30)
        out.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
    return out


def _weather_label(code):
    table = {
        0: ("CLEAR", "ашық"),
        1: ("MAINLY CLEAR", "ашық"),
        2: ("PARTLY CLOUDY", "ала бұлтты"),
        3: ("CLOUDY", "бұлтты"),
        45: ("FOG", "тұман"),
        48: ("RIME FOG", "тұман"),
        51: ("DRIZZLE", "сіркіреме"),
        53: ("DRIZZLE", "сіркіреме"),
        55: ("DRIZZLE", "сіркіреме"),
        61: ("RAIN", "жаңбыр"),
        63: ("RAIN", "жаңбыр"),
        65: ("HEAVY RAIN", "қатты жаңбыр"),
        71: ("SNOW", "қар"),
        73: ("SNOW", "қар"),
        75: ("HEAVY SNOW", "қалың қар"),
        80: ("SHOWERS", "нөсер"),
        81: ("SHOWERS", "нөсер"),
        82: ("HEAVY SHOWERS", "қатты нөсер"),
        95: ("THUNDER", "найзағай"),
        96: ("THUNDER", "найзағай"),
        99: ("THUNDER", "найзағай"),
    }
    return table.get(int(code or 0), ("WEATHER", "ауа райы"))


class SnakeGame:
    CELL = 20
    COLS = 25
    ROWS = 17

    def __init__(self):
        self.reset()

    def reset(self):
        mid_x, mid_y = self.COLS // 2, self.ROWS // 2
        self.snake = deque([(mid_x - 2, mid_y), (mid_x - 1, mid_y), (mid_x, mid_y)])
        self.dir = (1, 0)
        self.next_dir = (1, 0)
        self.score = 0
        self.alive = True
        self.paused = False
        self.last_step = time.time()
        self.step_int = 0.12
        self.food = self._spawn_food()

    def _spawn_food(self):
        while True:
            food = (random.randrange(self.COLS), random.randrange(self.ROWS))
            if food not in self.snake:
                return food

    def turn(self, dx, dy):
        if (dx, dy) != (-self.dir[0], -self.dir[1]):
            self.next_dir = (dx, dy)

    def step(self):
        if not self.alive or self.paused or time.time() - self.last_step < self.step_int:
            return
        self.last_step = time.time()
        self.dir = self.next_dir
        head = self.snake[-1]
        new_head = (head[0] + self.dir[0], head[1] + self.dir[1])
        if not (0 <= new_head[0] < self.COLS and 0 <= new_head[1] < self.ROWS) or new_head in self.snake:
            self.alive = False
            return
        self.snake.append(new_head)
        if new_head == self.food:
            self.score += 1
            self.step_int = max(0.055, self.step_int * 0.97)
            self.food = self._spawn_food()
        else:
            self.snake.popleft()


class MemoryGame:
    def __init__(self):
        self.reset()

    def reset(self):
        self.level = 1
        self.sequence = []
        self.input_index = 0
        self.show_until = 0.0
        self.message = "WATCH"
        self._next_round()

    def _next_round(self):
        self.sequence.append(random.randrange(6))
        self.input_index = 0
        self.show_until = time.time() + 1.2 + len(self.sequence) * 0.22
        self.message = "WATCH"

    def current_flash(self):
        if time.time() >= self.show_until:
            return None
        idx = int((time.time() * 3.6) % max(1, len(self.sequence)))
        return self.sequence[min(idx, len(self.sequence) - 1)]

    def click_hex(self, value):
        if time.time() < self.show_until:
            return
        if value == self.sequence[self.input_index]:
            self.input_index += 1
            self.message = "GOOD"
            if self.input_index >= len(self.sequence):
                self.level += 1
                self.message = "NEXT"
                self.show_until = time.time() + 0.35
                threading.Timer(0.38, self._next_round).start()
        else:
            self.message = "RESET"
            self.level = 1
            self.sequence = []
            self.show_until = time.time() + 0.45
            threading.Timer(0.48, self._next_round).start()


class ReactionGame:
    def __init__(self):
        self.reset()

    def reset(self):
        self.score = 0
        self.best = None
        self.target = (0.5, 0.5)
        self.spawned = time.time()
        self.message = "TARGET"
        self._spawn()

    def _spawn(self):
        self.target = (random.uniform(0.18, 0.82), random.uniform(0.22, 0.78))
        self.spawned = time.time()

    def hit(self):
        elapsed = max(0.001, time.time() - self.spawned)
        self.best = elapsed if self.best is None else min(self.best, elapsed)
        self.score += 1
        self.message = f"{elapsed*1000:.0f} MS"
        self._spawn()


class WeatherClient:
    """Small no-key weather fetcher for the HUD only."""

    LAT = 43.2389
    LON = 76.8897
    TZ = "Asia/Almaty"
    CITY = "ALMATY"

    def __init__(self):
        self.data = {
            "city": self.CITY,
            "temp": "--",
            "apparent": "--",
            "wind": "--",
            "humidity": "--",
            "code": 0,
            "label_ru": "LOADING",
            "label_kz": "жүктелуде",
            "hours": [],
            "updated": "waiting",
            "error": "",
        }
        self._loading = False
        self._last_fetch = 0.0

    def maybe_refresh(self, force=False):
        if self._loading:
            return
        if not force and time.time() - self._last_fetch < 900:
            return
        self._loading = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            params = {
                "latitude": self.LAT,
                "longitude": self.LON,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "hourly": "temperature_2m,weather_code,wind_speed_10m",
                "forecast_days": "1",
                "timezone": self.TZ,
            }
            url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(url, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            current = payload.get("current", {})
            hourly = payload.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            codes = hourly.get("weather_code", [])
            now_hour = dt.datetime.now().hour
            hours = []
            for idx, value in enumerate(times):
                try:
                    hour = int(value[-5:-3])
                except Exception:
                    hour = idx
                if hour >= now_hour and len(hours) < 5:
                    temp = temps[idx] if idx < len(temps) else None
                    code = codes[idx] if idx < len(codes) else 0
                    hours.append((f"{hour:02d}", temp, code))
            if len(hours) < 5:
                for idx, value in enumerate(times[:5 - len(hours)]):
                    hour = value[-5:-3] if len(value) >= 5 else f"{idx:02d}"
                    temp = temps[idx] if idx < len(temps) else None
                    code = codes[idx] if idx < len(codes) else 0
                    hours.append((hour, temp, code))
            label_ru, label_kz = _weather_label(current.get("weather_code", 0))
            self.data = {
                "city": self.CITY,
                "temp": current.get("temperature_2m"),
                "apparent": current.get("apparent_temperature"),
                "wind": current.get("wind_speed_10m"),
                "humidity": current.get("relative_humidity_2m"),
                "code": current.get("weather_code", 0),
                "label_ru": label_ru,
                "label_kz": label_kz,
                "hours": hours,
                "updated": dt.datetime.now().strftime("%H:%M"),
                "error": "",
            }
            self._last_fetch = time.time()
        except Exception as exc:
            self.data["error"] = str(exc)[:42]
            self.data["updated"] = "offline"
            self._last_fetch = time.time()
        finally:
            self._loading = False


class SignalCore:
    def __init__(self):
        self.phase = 0.0
        self.rot_outer = 0.0
        self.rot_inner = 0.0
        self.touch_until = 0.0
        self.pulses = []

    def touch(self):
        self.touch_until = time.time() + 1.4
        self.pulses.append(time.time())

    def active(self):
        return time.time() < self.touch_until

    def update(self, dt_):
        spd = 1.0 if not self.active() else 3.2
        self.phase = (self.phase + dt_ * 2.8 * spd) % (math.pi * 2)
        self.rot_outer = (self.rot_outer + dt_ * 12 * spd) % 360
        self.rot_inner = (self.rot_inner - dt_ * 18 * spd) % 360
        self.pulses = [t for t in self.pulses if time.time() - t < 1.5]

    def draw(self, c, cx, cy, R, active=False):
        a = THEMES["Cyan"]["accent"]
        adim = THEMES["Cyan"]["dim2"]
        is_on = active or self.active()
        pulse = (math.sin(self.phase * 1.8) + 1) / 2
        glow = 0.12 + pulse * (0.10 if is_on else 0.04)

        for r in [R * 1.18, R * 0.92, R * 0.62]:
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=mix(BG, a, glow), width=1)

        for i in range(72):
            ang = math.radians(i * 5)
            r1 = R * 1.05
            r2 = r1 - (11 if i % 6 == 0 else 5)
            c.create_line(
                cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                cx + r2 * math.cos(ang), cy + r2 * math.sin(ang),
                fill=mix(BG_2, a, 0.55 if i % 6 == 0 else 0.24),
                width=1,
            )

        for rr, start, extent, col, width in [
            (R * 1.05, self.rot_outer, 26, a, 3),
            (R * 1.05, self.rot_outer + 180, 10, adim, 1),
            (R * 0.78, self.rot_inner, 17, adim, 2),
            (R * 0.48, -self.rot_outer * 0.7, 34, a, 2),
        ]:
            c.create_arc(cx-rr, cy-rr, cx+rr, cy+rr, start=start, extent=extent,
                         style="arc", outline=col, width=width)

        for i in range(6):
            ang = math.radians(self.rot_inner * 0.25 + i * 60)
            c.create_line(
                cx + R * 0.30 * math.cos(ang), cy + R * 0.30 * math.sin(ang),
                cx + R * 0.91 * math.cos(ang), cy + R * 0.91 * math.sin(ang),
                fill=mix(BG_2, a, 0.22), width=1,
            )

        base_r = R * 0.38 + pulse * 5
        for i in range(7):
            r = base_r + i * 5
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=mix(BG_2, a, 0.18 * (1 - i / 7)))
        c.create_oval(cx-base_r, cy-base_r, cx+base_r, cy+base_r,
                      fill=mix(BG, a, 0.11 if is_on else 0.07), outline=a, width=2)
        inner = base_r * 0.58
        c.create_oval(cx-inner, cy-inner, cx+inner, cy+inner,
                      fill=mix(BG, a, 0.20 if is_on else 0.12), outline=mix(BG_2, a, 0.55))

        bars = 13
        total = bars * 4 + (bars - 1) * 5
        x0 = cx - total / 2
        for i in range(bars):
            d = abs(i - (bars - 1) / 2) / ((bars - 1) / 2)
            hgt = 8 + abs(math.sin(self.phase * 2.3 + i * 0.7)) * 48 * (1 - d * 0.45)
            bx = x0 + i * 9
            c.create_rectangle(bx, cy - hgt / 2, bx + 4, cy + hgt / 2, fill=a, outline="")

        for t in self.pulses:
            age = time.time() - t
            r = R * (0.45 + age * 0.7)
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=mix(BG, a, max(0, 0.8 - age / 1.5)), width=2)

        c.create_text(cx, cy + R * 0.68, text="ACTIVE" if is_on else "STANDBY",
                      fill=a, font=("Consolas", 11, "bold"))


class JarvisHUD:
    FPS = 30
    SIDEBAR_W = 76
    HEADER_H = 64
    FOOTER_H = 36

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.configure(bg=BG)
        self.root.geometry("1360x820")
        self.root.minsize(1060, 680)

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.command_var = tk.StringVar()
        self.entry = tk.Entry(
            self.root,
            textvariable=self.command_var,
            bg=BG,
            fg=TEXT,
            insertbackground=THEMES["Cyan"]["accent"],
            relief="flat",
            font=("Consolas", 11),
            highlightthickness=0,
        )
        self.entry.bind("<Return>", self._manual_command)

        self.W, self.H = 1360, 820
        self.t = 0.0
        self.last = time.time()
        self.core = SignalCore()
        self.weather = WeatherClient()
        self.heard = ""
        self.response = "SYSTEM ONLINE"
        self.voice_state = "VOICE CORE LOADING"
        self.language = "ru"
        self.screen = "home"
        self.wiki_card = None
        self.wiki_photo = None
        self.wiki_photo_path = ""
        self.wiki_pos = None
        self.wiki_rect = None
        self.wiki_drag = None
        self.stop_rect = None
        self.active = False
        self.events = []
        self.zones = []
        self.settings_window = None
        self.snake = SnakeGame()
        self.memory = MemoryGame()
        self.reaction = ReactionGame()
        self.particles = [
            [math.sin(i * 12.989) % 1 * 1360, math.sin(i * 78.233) % 1 * 820,
             -0.8 + (math.sin(i * 4.13) % 1) * 1.6, -0.4 + (math.sin(i * 8.41) % 1) * 0.8, i]
            for i in range(80)
        ]

        self.assistant = JarvisAssistant(event_callback=self._assistant_event)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Escape>", lambda e: self._close())
        self.root.bind("<space>", self._space_key)
        self.root.bind("<Key>", self._key)
        self.root.bind("<Control-s>", lambda e: self._open_settings())
        self.root.bind("g", lambda e: self._open_graph())
        self.root.bind("G", lambda e: self._open_graph())
        self.root.bind("<Configure>", self._resize)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<B1-Motion>", self._drag_wiki)
        self.canvas.bind("<ButtonRelease-1>", self._release_drag)

        self.weather.maybe_refresh(force=True)
        self.assistant.start()
        self._loop()
        self.root.mainloop()

    def theme(self):
        return THEMES["Cyan"]

    def _close(self):
        self.assistant.stop()
        self.root.destroy()

    def _resize(self, event):
        self.W = self.canvas.winfo_width()
        self.H = self.canvas.winfo_height()

    def _assistant_event(self, event, value=None):
        self.root.after(0, lambda: self._apply_event(event, value))

    def _apply_event(self, event, value):
        if event == "heard":
            self.heard = value
            self._push_event("HEARD", value)
        elif event == "response":
            self.response = value
            self._push_event("JARVIS", value)
        elif event == "voice_error":
            self.voice_state = value
            self._push_event("VOICE", value)
        elif event == "voice_ready":
            self.voice_state = value
            self._push_event("VOICE", value)
        elif event == "self_mute":
            self.voice_state = value
            self._push_event("MUTE", value)
        elif event == "ignored":
            self._push_event("IGN", value)
        elif event == "active":
            self.active = bool(value)
        elif event == "language":
            self.language = "ru"
        elif event == "open_games":
            self.screen = "games"
            self._push_event("GAMES", "opened")
        elif event == "wiki_card":
            self.wiki_card = value if isinstance(value, dict) else None
            self.wiki_pos = None
            self.wiki_rect = None
            self.wiki_drag = None
            self._load_wiki_photo()
            self.screen = "home"
            self._push_event("WIKI", (self.wiki_card or {}).get("title", "opened"))

    def _push_event(self, kind, value):
        self.events.insert(0, (time.strftime("%H:%M:%S"), kind, str(value)))
        self.events = self.events[:7]

    def _focus_command(self, event=None):
        self.entry.focus_set()
        return "break"

    def _space_key(self, event=None):
        if self.screen == "snake" and self.root.focus_get() is not self.entry:
            self.snake.paused = not self.snake.paused
            return "break"
        return self._focus_command(event)

    def _key(self, event):
        if self.root.focus_get() is self.entry:
            return None
        key = (event.keysym or "").lower()
        char = (event.char or "").lower()
        if char == "1":
            self.screen = "home"
        elif char == "2":
            self.screen = "games"
        elif key == "escape":
            if self.screen in ("snake", "memory", "reaction"):
                self.screen = "games"
                return "break"
        if self.screen == "snake":
            if key in ("left", "a"):
                self.snake.turn(-1, 0)
                return "break"
            if key in ("right", "d"):
                self.snake.turn(1, 0)
                return "break"
            if key in ("up", "w"):
                self.snake.turn(0, -1)
                return "break"
            if key in ("down", "s"):
                self.snake.turn(0, 1)
                return "break"
            if key == "r" or char == "r":
                self.snake.reset()
                return "break"
        elif self.screen == "memory" and (key == "r" or char == "r"):
            self.memory.reset()
            return "break"
        elif self.screen == "reaction" and (key == "r" or char == "r"):
            self.reaction.reset()
            return "break"
        return None

    def _go(self, screen):
        self.screen = screen

    def _manual_command(self, event=None):
        text = self.command_var.get().strip()
        self.command_var.set("")
        if text:
            self.assistant.handle_text(text, force=True)
        return "break"

    def _open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        settings = JarvisSettings(master=self.root, language="ru")
        self.settings_window = settings.root

    def _open_graph(self):
        if self.assistant.open_graph():
            self.response = "Graph online."
            self._push_event("GRAPH", "opened")

    def _set_language(self, language):
        self.assistant.set_language(language)
        self.language = self.assistant.language

    def _toggle_language(self):
        self.language = "ru"

    def _click(self, event):
        if self.stop_rect:
            x1, y1, x2, y2 = self.stop_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._stop_speaking()
                return
        for x1, y1, x2, y2, action in self.zones:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                action()
                return
        if self.wiki_card and self.wiki_rect:
            x1, y1, x2, y2 = self.wiki_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y1 + 42:
                self.wiki_drag = (event.x - x1, event.y - y1)
                return

    def _drag_wiki(self, event):
        if not self.wiki_drag or not self.wiki_rect:
            return
        dx, dy = self.wiki_drag
        _, _, x2, y2 = self.wiki_rect
        w = x2 - self.wiki_rect[0]
        h = y2 - self.wiki_rect[1]
        nx = max(self.SIDEBAR_W + 8, min(self.W - w - 8, event.x - dx))
        ny = max(self.HEADER_H + 8, min(self.H - self.FOOTER_H - h - 8, event.y - dy))
        self.wiki_pos = (nx, ny)

    def _release_drag(self, event):
        self.wiki_drag = None

    def _touch_core(self):
        self.core.touch()
        self.response = "CORE SIGNAL BOOST"
        self._push_event("CORE", "manual boost")

    def _stop_speaking(self):
        self.assistant.stop_speaking()
        self.response = "Слушаю, сэр."
        self._push_event("STOP", "tts stopped")

    def _load_wiki_photo(self):
        self.wiki_photo = None
        self.wiki_photo_path = ""
        path = (self.wiki_card or {}).get("image_path", "")
        if not path:
            return
        try:
            image_path = Path(path)
            if not image_path.exists():
                return
            image = Image.open(image_path)
            image.thumbnail((190, 190))
            self.wiki_photo = ImageTk.PhotoImage(image)
            self.wiki_photo_path = str(image_path)
        except Exception:
            self.wiki_photo = None

    def _t(self, ru, kz):
        return ru

    def _event_label(self, kind):
        return kind

    def _loop(self):
        now = time.time()
        dt_ = min(now - self.last, 0.05)
        self.last = now
        self.t += dt_
        self.core.update(dt_)
        if self.screen == "snake":
            self.snake.step()
        self.active = self.assistant.is_active()
        self.weather.maybe_refresh()
        self._render()
        self.root.after(1000 // self.FPS, self._loop)

    def _draw_panel(self, c, x, y, w, h, title=None, ident=None):
        a = self.theme()["accent"]
        c.create_rectangle(x, y, x+w, y+h, fill=PANEL, outline=FAINT)
        for dx, dy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
            cx = x + (w if dx < 0 else 0)
            cy = y + (h if dy < 0 else 0)
            c.create_line(cx, cy, cx + 13 * dx, cy, fill=a)
            c.create_line(cx, cy, cx, cy + 13 * dy, fill=a)
        if title:
            c.create_text(x+14, y+14, anchor="w", text=title.upper(), fill=a, font=("Consolas", 9, "bold"))
        if ident:
            c.create_text(x+w-14, y+14, anchor="e", text=ident, fill=DIM, font=("Consolas", 8))

    def _button(self, c, x, y, w, h, label, action, active=False):
        a = self.theme()["accent"]
        c.create_rectangle(x, y, x+w, y+h, fill=BG_2, outline=a if active else FAINT)
        c.create_text(x+w/2, y+h/2, text=label, fill=TEXT if not active else a,
                      font=("Consolas", 9, "bold"))
        self.zones.append((x, y, x+w, y+h, action))

    def _render(self):
        c = self.canvas
        c.delete("all")
        self.zones = []
        c.create_rectangle(0, 0, self.W, self.H, fill=BG, outline="")
        self._draw_background(c)
        self._draw_header(c)
        self._draw_sidebar(c)
        self._draw_footer(c)
        if self.screen == "home":
            self._draw_home(c)
        elif self.screen == "games":
            self._draw_games(c)
        elif self.screen == "snake":
            self._draw_snake(c)
        elif self.screen == "memory":
            self._draw_memory(c)
        elif self.screen == "reaction":
            self._draw_reaction(c)
        self._place_entry()
        self._draw_stop_button(c)

    def _draw_background(self, c):
        a = self.theme()["accent"]
        step = 48
        grid = mix(BG, a, 0.035)
        for x in range(0, self.W, step):
            c.create_line(x, 0, x, self.H, fill=grid)
        for y in range(0, self.H, step):
            c.create_line(0, y, self.W, y, fill=grid)
        for p in self.particles:
            p[0] = (p[0] + p[2] * 0.15) % self.W
            p[1] = (p[1] + p[3] * 0.15) % self.H
            k = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self.t * 0.6 + p[4] * 5))
            col = mix(BG, a, 0.16 * k)
            c.create_oval(p[0]-1, p[1]-1, p[0]+1, p[1]+1, fill=col, outline="")

    def _draw_header(self, c):
        a = self.theme()["accent"]
        cx, cy = 28, 32
        c.create_polygon(hex_points(cx, cy, 14), fill="", outline=a)
        c.create_polygon(hex_points(cx, cy, 8, rot=30), fill="", outline=mix(BG, a, 0.5))
        c.create_oval(cx-2, cy-2, cx+2, cy+2, fill=a, outline="")
        c.create_text(52, 25, anchor="w", text="J A R V I S", fill=TEXT, font=("Helvetica", 15, "bold"))
        c.create_text(52, 44, anchor="w",
                      text=self._t("voice assistant interface", "дауыстық көмекші интерфейсі"),
                      fill=DIM, font=("Consolas", 9))
        x = 286
        status = self._t("ACTIVE" if self.active else "STANDBY", "БЕЛСЕНДІ" if self.active else "КҮТУ")
        chips = [("STATUS", status, True), ("VOICE", "EDGE TTS", False), ("AI", "GROQ", False)]
        for label, val, hot in chips:
            tw = max(92, 18 + 7 * len(label) + 7 * len(val))
            c.create_rectangle(x, 18, x+tw, 46, outline=FAINT, fill=BG_2)
            c.create_text(x+10, 32, anchor="w", text=label, fill=DIM, font=("Consolas", 9))
            c.create_text(x+tw-10, 32, anchor="e", text=val, fill=a if hot else TEXT,
                          font=("Consolas", 10, "bold" if hot else "normal"))
            x += tw + 8
        now = dt.datetime.now()
        c.create_text(self.W-24, 24, anchor="e", text=now.strftime("%H:%M:%S"),
                      fill=TEXT, font=("Helvetica", 18))
        c.create_text(self.W-24, 46, anchor="e", text=now.strftime("%A · %d %b %Y").upper(),
                      fill=DIM, font=("Consolas", 9))
        c.create_line(0, self.HEADER_H, self.W, self.HEADER_H, fill=FAINT)

    def _draw_sidebar(self, c):
        a = self.theme()["accent"]
        c.create_rectangle(0, self.HEADER_H, self.SIDEBAR_W, self.H, fill=BG_2, outline=FAINT)
        items = [
            ("◉", "HOME", lambda: self._go("home")),
            ("▣", "GAMES", lambda: self._go("games")),
            ("G", "GRAPH", self._open_graph),
            ("⚙", "SET", self._open_settings),
        ]
        y = self.HEADER_H + 24
        for icon, label, action in items:
            box_h = 56
            cx, cy = self.SIDEBAR_W / 2, y + box_h / 2
            active = (label == "HOME" and self.screen == "home") or (
                label == "GAMES" and self.screen in ("games", "snake", "memory", "reaction")
            )
            c.create_polygon(hex_points(cx, cy, 22), fill="", outline=a if active else mix(BG_2, a, 0.35),
                             width=2 if active else 1)
            if active:
                c.create_polygon(hex_points(cx, cy, 16, rot=30), fill=mix(BG_2, a, 0.15), outline="")
            c.create_text(cx, cy-2, text=icon, fill=a if active else mix(BG_2, a, 0.75),
                          font=("Helvetica", 14, "bold"))
            c.create_text(cx, cy+22, text=label, fill=TEXT if active else DIM, font=("Consolas", 8))
            self.zones.append((0, y, self.SIDEBAR_W, y+box_h+18, action))
            y += box_h + 24
        c.create_polygon(hex_points(self.SIDEBAR_W/2, self.H-40, 18), fill="", outline=mix(BG_2, a, 0.5))
        c.create_text(self.SIDEBAR_W/2, self.H-40, text="T", fill=a, font=("Helvetica", 12, "bold"))

    def _draw_footer(self, c):
        y = self.H - self.FOOTER_H
        a = self.theme()["accent"]
        c.create_line(0, y, self.W, y, fill=FAINT)
        chips = [
            (self._t("wake: ale / jarvis", "ояту: алло / джарвис"), True),
            (self._t("offline voice", "жергілікті дауыс"), False),
            (self._t("privacy: local", "құпия: жергілікті"), False),
        ]
        x = self.SIDEBAR_W + 18
        for text, on in chips:
            tw = 20 + 7 * len(text)
            c.create_rectangle(x, y+8, x+tw, y+28, outline=a if on else FAINT, fill=BG_2)
            c.create_text(x+tw/2, y+18, text=text, fill=a if on else DIM, font=("Consolas", 9))
            x += tw + 8
        c.create_text(self.W-110, y+18, anchor="e",
                      text="1/2 · screens    SPACE · input/pause    CTRL+S · settings    G · graph",
                      fill=DIM, font=("Consolas", 9))

    def _draw_stop_button(self, c):
        y = self.H - self.FOOTER_H
        x = self.W - 92
        w, h = 68, 22
        self.stop_rect = (x, y+7, x+w, y+7+h)
        a = self.theme()["accent"]
        c.create_rectangle(x-2, y+5, x+w+2, y+7+h+2, fill=BG, outline="")
        c.create_rectangle(x, y+7, x+w, y+7+h, fill=BG_2, outline=a, width=1)
        c.create_text(x+w/2, y+18, text="STOP", fill=a, font=("Consolas", 9, "bold"))

    def _draw_home(self, c):
        margin = 18
        cont_x = self.SIDEBAR_W + margin
        cont_y = self.HEADER_H + 10
        cont_w = self.W - self.SIDEBAR_W - margin * 2
        cont_h = self.H - self.HEADER_H - self.FOOTER_H - 20
        left_w = min(320, max(286, int(cont_w * 0.27)))
        right_w = min(320, max(286, int(cont_w * 0.27)))
        gap = 14
        center_x = cont_x + left_w + gap
        right_x = cont_x + cont_w - right_w
        center_w = max(340, right_x - center_x - gap)

        tele_h = min(170, max(145, int(cont_h * 0.24)))
        log_h = min(230, max(180, int(cont_h * 0.34)))
        weather_y = cont_y + tele_h + gap + log_h + gap
        weather_h = max(132, cont_y + cont_h - weather_y)
        self._home_telemetry(c, cont_x, cont_y, left_w, tele_h)
        self._home_log(c, cont_x, cont_y+tele_h+gap, left_w, log_h)
        self._home_weather(c, cont_x, weather_y, left_w, weather_h)
        self._home_status(c, center_x, cont_y, center_w, 76)
        self._home_orb(c, center_x, cont_y+90, center_w, max(350, cont_h-214))
        self._home_transcript(c, center_x, cont_y+cont_h-110, center_w, 110)
        if self.wiki_card:
            self._home_wiki(c, center_x, cont_y+90, center_w, max(350, cont_h-214))
        radar_h = min(255, max(210, int(cont_h * 0.36)))
        net_h = min(185, max(160, int(cont_h * 0.26)))
        modules_y = cont_y + radar_h + gap + net_h + gap
        modules_h = max(132, cont_y + cont_h - modules_y)
        self._home_radar(c, right_x, cont_y, right_w, radar_h)
        self._home_network(c, right_x, cont_y+radar_h+gap, right_w, net_h)
        self._home_modules(c, right_x, modules_y, right_w, modules_h)

    def _home_telemetry(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h, self._t("system telemetry", "жүйе көрсеткіші"), "/ sys.0")
        a = self.theme()["accent"]
        values = [
            ("VOICE", 92 if self.voice_state else 24, "%"),
            ("WAKE WINDOW", 100 if self.active else 28, "%"),
            ("COMMAND BUS", min(99, 38 + len(self.events) * 9), "%"),
        ]
        py = y + 44
        for label, val, unit in values:
            c.create_text(x+14, py, anchor="w", text=label, fill=DIM, font=("Consolas", 9))
            c.create_text(x+w-14, py, anchor="e", text=f"{val:.0f}{unit}", fill=TEXT,
                          font=("Consolas", 10, "bold"))
            c.create_rectangle(x+14, py+12, x+w-14, py+15, fill=BG, outline="")
            c.create_rectangle(x+14, py+12, x+14+(w-28)*val/100, py+15, fill=a, outline="")
            py += 38

    def _home_log(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h, self._t("command log", "команда тарихы"), "/ log.live")
        a = self.theme()["accent"]
        row_h = max(24, (h - 54) // 7)
        for i, (tm, kind, msg) in enumerate(self.events[:7]):
            cy = y + 40 + i * row_h
            c.create_text(x+14, cy, anchor="w", text=tm, fill=DIM, font=("Consolas", 8))
            c.create_text(x+68, cy, anchor="w", text=self._event_label(kind), fill=a,
                          font=("Consolas", 8, "bold"))
            short = msg[:25] + ("..." if len(msg) > 25 else "")
            c.create_text(x+130, cy, anchor="w", text=short, fill=TEXT, font=("Helvetica", 9))

    def _home_weather(self, c, x, y, w, h):
        data = self.weather.data
        self._draw_panel(c, x, y, w, h, self._t("ambient / weather", "ауа райы"), "/ env.3")
        a = self.theme()["accent"]
        warn = self.theme()["warn"]
        label = data["label_ru"]
        temp = data.get("temp")
        temp_text = "--°" if temp in (None, "--") else f"{round(float(temp))}°"
        wind = data.get("wind")
        hum = data.get("humidity")
        c.create_text(x+14, y+48, anchor="w", text=data.get("city", "QYZYLORDA"),
                      fill=DIM, font=("Consolas", 9))
        c.create_text(x+14, y+86, anchor="w", text=temp_text, fill=TEXT, font=("Helvetica", 36))
        detail = f"{label} · wind {wind if wind not in (None, '--') else '--'} km/h · hum {hum if hum not in (None, '--') else '--'}%"
        c.create_text(x+14, y+116, anchor="w", text=detail[:38], fill=mix(BG_2, a, 0.74),
                      font=("Consolas", 9))
        ix, iy = x+w-50, y+78
        c.create_oval(ix-14, iy-14, ix+14, iy+14, fill="", outline=warn)
        for k in range(8):
            ang = k * math.pi / 4
            c.create_line(ix + 18*math.cos(ang), iy + 18*math.sin(ang),
                          ix + 24*math.cos(ang), iy + 24*math.sin(ang), fill=warn)
        hours = data.get("hours") or []
        py = y + h - 42
        if hours:
            bw = (w - 28) / len(hours)
            for i, (hr, t_, code) in enumerate(hours):
                cx = x + 14 + bw * i + bw / 2
                txt = "--°" if t_ is None else f"{round(float(t_))}°"
                c.create_text(cx, py-12, text=txt, fill=TEXT, font=("Consolas", 9))
                c.create_text(cx, py+6, text=hr, fill=DIM, font=("Consolas", 9))
                c.create_oval(cx-2, py-3, cx+2, py+1, fill=a, outline="")
        else:
            fallback = data.get("error") or self._t("weather loading", "ауа райы жүктелуде")
            c.create_text(x+14, y+h-30, anchor="w", text=fallback[:36], fill=DIM, font=("Consolas", 8))
        c.create_text(x+w-14, y+h-18, anchor="e", text=f"upd {data.get('updated', '--')}",
                      fill=DIM, font=("Consolas", 8))

    def _home_status(self, c, x, y, w, h):
        now = dt.datetime.now()
        a = self.theme()["accent"]
        c.create_text(x+20, y+h/2-4, anchor="w", text=now.strftime("%H:%M"),
                      fill=TEXT, font=("Helvetica", 36))
        c.create_text(x+142, y+h/2-4, anchor="w", text=now.strftime("%S"),
                      fill=a, font=("Helvetica", 36))
        c.create_text(x+20, y+h/2+24, anchor="w",
                      text=self._t("LOCAL VOICE CORE · READY", "ЖЕРГІЛІКТІ ДАУЫС ЯДРОСЫ · ДАЙЫН"),
                      fill=DIM, font=("Consolas", 9))
        self._button(c, x+w-112, y+22, 96, 32, "GRAPH", self._open_graph)
        self._button(c, x+w-222, y+22, 98, 32, self._t("SET", "БАП"), self._open_settings)

    def _home_orb(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h)
        cx, cy = x + w / 2, y + h / 2 - 8
        R = min(h, w) / 2 - 48
        R = max(120, min(210, R))
        self.core.draw(c, cx, cy, R, self.active)
        self.zones.append((cx-R, cy-R, cx+R, cy+R, self._touch_core))

    def _home_transcript(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h, self._t("transcript", "сөйлесу"), "/ stt.live")
        a = self.theme()["accent"]
        c.create_text(x+14, y+40, anchor="w", text=self._t("USER", "СІЗ"), fill=DIM, font=("Consolas", 9))
        heard = self.heard or "..."
        c.create_text(x+w/2, y+56, text=f"« {heard} »", fill=TEXT, font=("Helvetica", 13), width=w-32)
        c.create_text(x+14, y+h-24, anchor="w", text="JARVIS", fill=a, font=("Consolas", 9, "bold"))
        c.create_text(x+88, y+h-24, anchor="w", text=(self.response or "...")[:70],
                      fill=a, font=("Helvetica", 10))
        blink = 0.5 + 0.5 * math.sin(self.t * 4)
        c.create_rectangle(x+w-24, y+h-40, x+w-20, y+h-30, fill=mix(BG_2, a, blink), outline="")

    def _home_wiki(self, c, x, y, w, h):
        card = self.wiki_card or {}
        a = self.theme()["accent"]
        pad = 18
        panel_w = min(w - 34, 680)
        panel_h = min(h - 40, 360)
        if self.wiki_pos:
            px, py = self.wiki_pos
        else:
            px = x + w - panel_w - 12
            py = y + 20
        px = max(self.SIDEBAR_W + 8, min(self.W - panel_w - 8, px))
        py = max(self.HEADER_H + 8, min(self.H - self.FOOTER_H - panel_h - 8, py))
        self.wiki_pos = (px, py)
        self.wiki_rect = (px, py, px + panel_w, py + panel_h)
        c.create_rectangle(px-8, py-8, px+panel_w+8, py+panel_h+8, fill=BG, outline="")
        self._draw_panel(c, px, py, panel_w, panel_h, "wikipedia", "/ wiki.live")
        c.create_text(px+panel_w/2, py+17, text="DRAG", fill=DIM, font=("Consolas", 8))
        title = (card.get("title") or "Wikipedia")[:58]
        desc = (card.get("description") or "").strip()
        extract = (card.get("extract") or "").strip()
        image_w = 0
        if self.wiki_photo:
            image_w = 196
            ix = px + panel_w - pad - image_w + 8
            iy = py + 54
            c.create_rectangle(ix-8, iy-8, ix+image_w-8, iy+image_w-8, fill=BG, outline=FAINT)
            c.create_image(ix + (image_w-16)/2, iy + (image_w-16)/2, image=self.wiki_photo)
        tx = px + pad
        text_w = panel_w - pad * 2 - image_w
        c.create_text(tx, py+48, anchor="w", text=title, fill=TEXT, font=("Helvetica", 22, "bold"), width=text_w)
        if desc:
            c.create_text(tx, py+82, anchor="w", text=desc.upper(), fill=mix(BG_2, a, 0.72),
                          font=("Consolas", 9, "bold"), width=text_w)
            body_y = py + 112
        else:
            body_y = py + 92
        c.create_text(tx, body_y, anchor="nw", text=extract, fill=TEXT, font=("Helvetica", 12),
                      width=text_w, justify="left")
        if card.get("url"):
            c.create_text(tx, py+panel_h-24, anchor="w", text=card.get("url")[:76],
                          fill=DIM, font=("Consolas", 8))
        self._button(c, px+panel_w-86, py+panel_h-34, 66, 24, "HIDE", self._clear_wiki)

    def _clear_wiki(self):
        self.wiki_card = None
        self.wiki_photo = None
        self.wiki_photo_path = ""

    def _home_radar(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h, "radar", "/ env.scan")
        a = self.theme()["accent"]
        cx, cy = x + w / 2, y + h / 2 + 8
        r = min(w, h) / 2 - 30
        for k in [1.0, 0.66, 0.33]:
            c.create_oval(cx-r*k, cy-r*k, cx+r*k, cy+r*k, outline=FAINT)
        c.create_line(cx-r, cy, cx+r, cy, fill=FAINT)
        c.create_line(cx, cy-r, cx, cy+r, fill=FAINT)
        sweep = (self.t * 62) % 360
        x2 = cx + r * math.cos(math.radians(sweep))
        y2 = cy + r * math.sin(math.radians(sweep))
        c.create_line(cx, cy, x2, y2, fill=a)
        for i in range(9):
            ang = math.radians(i * 41 + math.sin(self.t + i) * 8)
            rr = r * (0.25 + (i % 5) * 0.14)
            px, py = cx + rr * math.cos(ang), cy + rr * math.sin(ang)
            c.create_oval(px-3, py-3, px+3, py+3, fill=mix(BG_2, a, 0.65), outline="")
        c.create_text(x+14, y+h-18, anchor="w", text="SIGNAL MAP", fill=DIM, font=("Consolas", 8))
        c.create_text(x+w-14, y+h-18, anchor="e", text="LIVE", fill=a, font=("Consolas", 8, "bold"))

    def _home_network(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h, self._t("network mesh", "желі"), "/ net.6")
        a = self.theme()["accent"]
        nodes = []
        for i in range(12):
            px = x + 28 + (w - 56) * ((math.sin(i * 8.13) + 1) / 2)
            py = y + 42 + (h - 72) * ((math.sin(i * 4.77 + 2) + 1) / 2)
            nodes.append((px, py))
        for i, (x1, y1) in enumerate(nodes):
            for j, (x2, y2) in enumerate(nodes):
                if j > i and (i + j) % 4 == 0:
                    c.create_line(x1, y1, x2, y2, fill=mix(BG_2, a, 0.14))
        for i, (px, py) in enumerate(nodes):
            r = 4 if i % 3 == 0 else 2
            c.create_oval(px-r, py-r, px+r, py+r, fill=a if i % 3 == 0 else mix(BG_2, a, 0.6), outline="")

    def _home_modules(self, c, x, y, w, h):
        self._draw_panel(c, x, y, w, h, self._t("active modules", "модульдер"), "/ mod.4")
        a = self.theme()["accent"]
        items = [
            ("50", "sites"),
            ("02", "modes"),
            ("07", "wake"),
            ("ON", "graph"),
            ("AI", "groq"),
            ("OK", "voice"),
        ]
        cols = 2
        cw = (w - 42) / cols
        ch = max(40, (h - 58) / 3)
        for i, (num, lbl) in enumerate(items):
            col = i % cols
            row = i // cols
            bx = x + 14 + col * (cw + 14)
            by = y + 42 + row * ch
            c.create_rectangle(bx, by, bx+cw, by+ch-10, fill=BG, outline=FAINT)
            c.create_text(bx+cw/2, by+ch/2-12, text=num, fill=a, font=("Consolas", 13, "bold"))
            c.create_text(bx+cw/2, by+ch/2+8, text=lbl.upper(), fill=DIM, font=("Consolas", 8))

    def _content_area(self):
        margin = 18
        x = self.SIDEBAR_W + margin
        y = self.HEADER_H + 10
        w = self.W - self.SIDEBAR_W - margin * 2
        h = self.H - self.HEADER_H - self.FOOTER_H - 20
        return x, y, w, h

    def _draw_games(self, c):
        x, y, w, h = self._content_area()
        a = self.theme()["accent"]
        c.create_text(x+4, y+4, anchor="nw", text="GAMES", fill=TEXT, font=("Helvetica", 24, "bold"))
        c.create_text(x+4, y+36, anchor="nw",
                      text="small interface modules from the Jarvis dashboard",
                      fill=DIM, font=("Consolas", 10))
        gap = 18
        card_w = (w - gap * 2) / 3
        card_h = min(430, h - 108)
        cards = [
            ("SNAKE", "WASD / arrows · space pause", "snake", self._card_snake),
            ("MEMORY HEX", "repeat the signal sequence", "memory", self._card_memory),
            ("REACTION PULSE", "click targets as fast as possible", "reaction", self._card_reaction),
        ]
        for i, (title, sub, screen, painter) in enumerate(cards):
            cx = x + i * (card_w + gap)
            cy = y + 88
            c.create_rectangle(cx, cy, cx+card_w, cy+card_h, fill=PANEL, outline=FAINT)
            for dx, dy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
                ax = cx + (card_w if dx < 0 else 0)
                ay = cy + (card_h if dy < 0 else 0)
                c.create_line(ax, ay, ax+16*dx, ay, fill=a)
                c.create_line(ax, ay, ax, ay+16*dy, fill=a)
            painter(c, cx+20, cy+30, card_w-40, card_h-120)
            c.create_text(cx+20, cy+card_h-70, anchor="w", text=title, fill=TEXT,
                          font=("Helvetica", 17, "bold"))
            c.create_text(cx+20, cy+card_h-43, anchor="w", text=sub, fill=DIM,
                          font=("Consolas", 9))
            self._button(c, cx+20, cy+card_h-34, 118, 25, "OPEN", lambda s=screen: self._go(s), active=True)

    def _card_snake(self, c, x, y, w, h):
        a = self.theme()["accent"]
        cols, rows = 12, 8
        cell = min(w / cols, h / rows)
        ox = x + (w - cols * cell) / 2
        oy = y + (h - rows * cell) / 2
        for i in range(cols + 1):
            c.create_line(ox+i*cell, oy, ox+i*cell, oy+rows*cell, fill=FAINT)
        for i in range(rows + 1):
            c.create_line(ox, oy+i*cell, ox+cols*cell, oy+i*cell, fill=FAINT)
        for sx, sy in [(4, 4), (5, 4), (6, 4), (7, 4)]:
            c.create_rectangle(ox+sx*cell+2, oy+sy*cell+2, ox+(sx+1)*cell-2, oy+(sy+1)*cell-2,
                               fill=mix(BG_2, a, 0.7), outline="")
        c.create_oval(ox+9*cell+4, oy+3*cell+4, ox+10*cell-4, oy+4*cell-4,
                      fill=self.theme()["warn"], outline="")

    def _card_memory(self, c, x, y, w, h):
        a = self.theme()["accent"]
        cx = x + w / 2
        cy = y + h / 2
        r = min(w, h) / 6
        for i in range(6):
            ang = math.radians(i * 60 - 30)
            hx = cx + math.cos(ang) * r * 2.1
            hy = cy + math.sin(ang) * r * 2.1
            c.create_polygon(hex_points(hx, hy, r), fill=mix(BG, a, 0.08), outline=mix(BG, a, 0.6))
            c.create_text(hx, hy, text=str(i+1), fill=TEXT, font=("Consolas", 12, "bold"))

    def _card_reaction(self, c, x, y, w, h):
        a = self.theme()["accent"]
        cx = x + w / 2
        cy = y + h / 2
        r = min(w, h) / 3
        for k in [1, 0.66, 0.33]:
            c.create_oval(cx-r*k, cy-r*k, cx+r*k, cy+r*k, outline=FAINT)
        c.create_line(cx-r, cy, cx+r, cy, fill=FAINT)
        c.create_line(cx, cy-r, cx, cy+r, fill=FAINT)
        tx = cx + r * 0.46
        ty = cy - r * 0.22
        c.create_oval(tx-15, ty-15, tx+15, ty+15, outline=a, width=2)
        c.create_oval(tx-4, ty-4, tx+4, ty+4, fill=a, outline="")

    def _draw_snake(self, c):
        x, y, w, h = self._content_area()
        a = self.theme()["accent"]
        c.create_text(x+4, y+4, anchor="nw", text="SNAKE", fill=TEXT, font=("Helvetica", 24, "bold"))
        c.create_text(x+4, y+36, anchor="nw", text="WASD / arrows · space pause · R restart · ESC back",
                      fill=DIM, font=("Consolas", 10))
        bw = self.snake.COLS * self.snake.CELL
        bh = self.snake.ROWS * self.snake.CELL
        bx = x + (w - bw) / 2
        by = y + 100
        self._draw_panel(c, bx-18, by-18, bw+36, bh+74, None, "/ game.snake")
        for i in range(self.snake.COLS + 1):
            c.create_line(bx+i*self.snake.CELL, by, bx+i*self.snake.CELL, by+bh, fill=FAINT)
        for i in range(self.snake.ROWS + 1):
            c.create_line(bx, by+i*self.snake.CELL, bx+bw, by+i*self.snake.CELL, fill=FAINT)
        for sx, sy in self.snake.snake:
            c.create_rectangle(bx+sx*self.snake.CELL+2, by+sy*self.snake.CELL+2,
                               bx+(sx+1)*self.snake.CELL-2, by+(sy+1)*self.snake.CELL-2,
                               fill=a, outline="")
        fx, fy = self.snake.food
        c.create_oval(bx+fx*self.snake.CELL+4, by+fy*self.snake.CELL+4,
                      bx+(fx+1)*self.snake.CELL-4, by+(fy+1)*self.snake.CELL-4,
                      fill=self.theme()["warn"], outline="")
        c.create_text(bx, by+bh+28, anchor="w", text=f"SCORE {self.snake.score}", fill=TEXT,
                      font=("Consolas", 11, "bold"))
        state = "PAUSED" if self.snake.paused else ("GAME OVER" if not self.snake.alive else "RUNNING")
        c.create_text(bx+bw, by+bh+28, anchor="e", text=state, fill=a, font=("Consolas", 11, "bold"))
        if not self.snake.alive:
            c.create_rectangle(bx, by+bh/2-44, bx+bw, by+bh/2+44, fill=BG_2, outline=a)
            c.create_text(bx+bw/2, by+bh/2-12, text="GAME OVER", fill=TEXT, font=("Helvetica", 22, "bold"))
            c.create_text(bx+bw/2, by+bh/2+18, text="press R to restart", fill=DIM, font=("Consolas", 10))

    def _draw_memory(self, c):
        x, y, w, h = self._content_area()
        a = self.theme()["accent"]
        c.create_text(x+4, y+4, anchor="nw", text="MEMORY HEX", fill=TEXT, font=("Helvetica", 24, "bold"))
        c.create_text(x+4, y+36, anchor="nw", text="click hexes in the same sequence · R restart · ESC back",
                      fill=DIM, font=("Consolas", 10))
        cx = x + w / 2
        cy = y + h / 2 + 24
        r = min(68, max(48, min(w, h) / 9))
        active = self.memory.current_flash()
        for i in range(6):
            ang = math.radians(i * 60 - 30)
            hx = cx + math.cos(ang) * r * 2.25
            hy = cy + math.sin(ang) * r * 2.25
            on = active == i
            c.create_polygon(hex_points(hx, hy, r), fill=mix(BG, a, 0.22 if on else 0.08),
                             outline=a if on else mix(BG, a, 0.55), width=2 if on else 1)
            c.create_polygon(hex_points(hx, hy, r-11, rot=30), fill="", outline=mix(BG, a, 0.35))
            c.create_text(hx, hy, text=str(i+1), fill=TEXT, font=("Consolas", 17, "bold"))
            self.zones.append((hx-r, hy-r, hx+r, hy+r, lambda idx=i: self.memory.click_hex(idx)))
        c.create_text(cx, y+88, text=f"LEVEL {self.memory.level}", fill=a, font=("Consolas", 13, "bold"))
        c.create_text(cx, y+116, text=self.memory.message, fill=DIM, font=("Consolas", 10))

    def _draw_reaction(self, c):
        x, y, w, h = self._content_area()
        a = self.theme()["accent"]
        c.create_text(x+4, y+4, anchor="nw", text="REACTION PULSE", fill=TEXT, font=("Helvetica", 24, "bold"))
        c.create_text(x+4, y+36, anchor="nw", text="click the pulse target · R restart · ESC back",
                      fill=DIM, font=("Consolas", 10))
        bx, by = x + 90, y + 92
        bw, bh = w - 180, h - 150
        self._draw_panel(c, bx, by, bw, bh, None, "/ game.react")
        for i in range(12):
            xx = bx + i * bw / 11
            c.create_line(xx, by, xx, by+bh, fill=FAINT)
        for i in range(8):
            yy = by + i * bh / 7
            c.create_line(bx, yy, bx+bw, yy, fill=FAINT)
        tx = bx + self.reaction.target[0] * bw
        ty = by + self.reaction.target[1] * bh
        pulse = 0.5 + 0.5 * math.sin(self.t * 8)
        rr = 18 + pulse * 10
        c.create_oval(tx-rr, ty-rr, tx+rr, ty+rr, outline=mix(BG, a, 0.7), width=2)
        c.create_oval(tx-7, ty-7, tx+7, ty+7, fill=a, outline="")
        self.zones.append((tx-34, ty-34, tx+34, ty+34, self.reaction.hit))
        best = "--" if self.reaction.best is None else f"{self.reaction.best*1000:.0f} MS"
        c.create_text(bx, by+bh+28, anchor="w", text=f"SCORE {self.reaction.score}", fill=TEXT,
                      font=("Consolas", 11, "bold"))
        c.create_text(bx+160, by+bh+28, anchor="w", text=f"BEST {best}", fill=self.theme()["warn"],
                      font=("Consolas", 11, "bold"))
        c.create_text(bx+bw, by+bh+28, anchor="e", text=self.reaction.message, fill=a,
                      font=("Consolas", 11, "bold"))

    def _place_entry(self):
        if self.screen != "home":
            self.entry.place_forget()
            return
        margin = 18
        cont_x = self.SIDEBAR_W + margin
        cont_y = self.HEADER_H + 10
        cont_w = self.W - self.SIDEBAR_W - margin * 2
        cont_h = self.H - self.HEADER_H - self.FOOTER_H - 20
        left_w = min(320, max(286, int(cont_w * 0.27)))
        gap = 14
        center_x = cont_x + left_w + gap
        right_w = min(320, max(286, int(cont_w * 0.27)))
        right_x = cont_x + cont_w - right_w
        center_w = max(340, right_x - center_x - gap)
        y = cont_y + cont_h - 110
        h = 110
        ib_y = y + h - 42
        self.entry.place(x=center_x+92, y=ib_y+5, width=center_w-126, height=22)


if __name__ == "__main__":
    JarvisHUD()
