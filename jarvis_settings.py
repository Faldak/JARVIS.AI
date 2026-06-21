import json
import tkinter as tk
from pathlib import Path

from jarvis_data import APPS, SITES, SOUNDS, VOICE_DIR

BLACK = "#000000"
WHITE = "#FFFFFF"
YELLOW = "#FFFF00"
RED = "#FF0000"

CUSTOM_COMMANDS_PATH = Path(__file__).with_name("custom_commands.json")
STATE_PATH = Path(__file__).with_name("jarvis_state.json")


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data):
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_custom_commands():
    if not CUSTOM_COMMANDS_PATH.exists():
        return []
    try:
        data = json.loads(CUSTOM_COMMANDS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_custom_commands(commands):
    CUSTOM_COMMANDS_PATH.write_text(json.dumps(commands, ensure_ascii=False, indent=2), encoding="utf-8")


def voice_phrases():
    return [
        "ok", "good", "doing", "site", "yes", "start", "unknown",
        "timer_set", "timer_done", "remembered", "will_do",
    ]


class JarvisSettings:
    def __init__(self, master=None, on_close=None, language=None, on_language_change=None):
        self.on_close = on_close
        self.on_language_change = on_language_change
        state = load_state()
        self.language = "ru"
        state["language"] = "ru"
        save_state(state)
        self.root = tk.Toplevel(master) if master else tk.Tk()
        self.root.title(self._t("J.A.R.V.I.S SETTINGS", "J.A.R.V.I.S БАПТАУЛАРЫ"))
        self.root.configure(bg=BLACK)
        self.root.geometry("1040x680")
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.commands = load_custom_commands()
        self.sound_options = voice_phrases()
        self.sound_var = tk.StringVar(value=self.sound_options[0])
        self.kind_var = tk.StringVar(value="site")
        self.status_var = tk.StringVar(value=self._t("CUSTOM COMMAND DATABASE READY", "КОМАНДАЛАР БАЗАСЫ ДАЙЫН"))

        self._build()
        self._refresh_list()
        if not master:
            self.root.mainloop()

    def _close(self):
        self.root.destroy()
        if self.on_close:
            self.on_close()

    def _t(self, ru, kz):
        return ru

    def _set_language(self, language):
        self.language = language
        state = load_state()
        state["language"] = "ru"
        save_state(state)
        if self.on_language_change:
            self.on_language_change("ru")
        self.root.title(self._t("J.A.R.V.I.S SETTINGS", "J.A.R.V.I.S БАПТАУЛАРЫ"))
        for child in self.root.winfo_children():
            child.destroy()
        self.status_var.set(self._t("CUSTOM COMMAND DATABASE READY", "КОМАНДАЛАР БАЗАСЫ ДАЙЫН"))
        self._build()
        self._refresh_list()

    def _label(self, parent, text, size=10):
        return tk.Label(parent, text=text, bg=BLACK, fg=YELLOW, font=("Consolas", size, "bold"))

    def _entry(self, parent):
        return tk.Entry(parent, bg=BLACK, fg=WHITE, insertbackground=YELLOW,
                        relief="solid", bd=1, highlightthickness=1,
                        highlightbackground=RED, highlightcolor=YELLOW,
                        font=("Consolas", 10))

    def _button(self, parent, text, command, fg=YELLOW):
        return tk.Button(parent, text=text, command=command, bg=BLACK, fg=fg,
                         activebackground=BLACK, activeforeground=WHITE,
                         relief="solid", bd=1, highlightthickness=1,
                         highlightbackground=fg, font=("Consolas", 10, "bold"))

    def _build(self):
        root = self.root
        tk.Label(root, text=self._t("J.A.R.V.I.S SETTINGS", "J.A.R.V.I.S БАПТАУЛАРЫ"), bg=BLACK, fg=YELLOW,
                 font=("Consolas", 24, "bold")).pack(anchor="w", padx=22, pady=(18, 0))
        tk.Label(root, text=self._t("ADD / DELETE CUSTOM COMMANDS  |  EXISTING CORE LOGIC IS UNCHANGED",
                                    "ЖЕКЕ КОМАНДАЛАРДЫ ҚОСУ / ЖОЮ  |  НЕГІЗГІ ЛОГИКА ӨЗГЕРМЕЙДІ"),
                 bg=BLACK, fg=WHITE, font=("Consolas", 10)).pack(anchor="w", padx=24, pady=(0, 16))

        body = tk.Frame(root, bg=BLACK)
        body.pack(fill=tk.BOTH, expand=True, padx=22, pady=8)

        left = tk.Frame(body, bg=BLACK, highlightthickness=2, highlightbackground=RED)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))
        right = tk.Frame(body, bg=BLACK, highlightthickness=2, highlightbackground=YELLOW)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

        self._label(left, self._t("CUSTOM COMMANDS", "ЖЕКЕ КОМАНДАЛАР"), 12).pack(anchor="w", padx=14, pady=(12, 4))
        self.listbox = tk.Listbox(left, bg=BLACK, fg=WHITE, selectbackground=RED,
                                  selectforeground=WHITE, relief="flat", bd=0,
                                  highlightthickness=1, highlightbackground=YELLOW,
                                  font=("Consolas", 10))
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._load_selected())

        row = tk.Frame(left, bg=BLACK)
        row.pack(fill=tk.X, padx=14, pady=(0, 14))
        self._button(row, self._t("DELETE", "ЖОЮ"), self._delete_selected, RED).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self._button(row, self._t("SAVE", "САҚТАУ"), self._save_all, YELLOW).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

        self._label(right, self._t("COMMAND TEXT", "КОМАНДА МӘТІНІ"), 10).pack(anchor="w", padx=14, pady=(14, 2))
        self.command_entry = self._entry(right)
        self.command_entry.pack(fill=tk.X, padx=14, pady=(0, 8))

        self._label(right, self._t("ALIASES, comma separated", "БАЛАМА АТАУЛАР, үтірмен"), 10).pack(anchor="w", padx=14, pady=(4, 2))
        self.alias_entry = self._entry(right)
        self.alias_entry.pack(fill=tk.X, padx=14, pady=(0, 8))

        self._label(right, self._t("TYPE", "ТҮРІ"), 10).pack(anchor="w", padx=14, pady=(4, 2))
        kind_row = tk.Frame(right, bg=BLACK)
        kind_row.pack(fill=tk.X, padx=14, pady=(0, 8))
        for kind in ("site", "app"):
            label = self._t(kind.upper(), "САЙТ" if kind == "site" else "ҚОЛДАНБА")
            tk.Radiobutton(kind_row, text=label, value=kind, variable=self.kind_var,
                           bg=BLACK, fg=WHITE, selectcolor=BLACK,
                           activebackground=BLACK, activeforeground=YELLOW,
                           font=("Consolas", 10, "bold")).pack(side=tk.LEFT, padx=(0, 16))

        self._label(right, self._t("TARGET URL / APP PATH", "СІЛТЕМЕ / ҚОЛДАНБА ЖОЛЫ"), 10).pack(anchor="w", padx=14, pady=(4, 2))
        self.target_entry = self._entry(right)
        self.target_entry.pack(fill=tk.X, padx=14, pady=(0, 8))

        self._label(right, self._t("VOICE PHRASE", "ДАУЫС ФРАЗАСЫ"), 10).pack(anchor="w", padx=14, pady=(4, 2))
        self.sound_menu = tk.OptionMenu(right, self.sound_var, *self.sound_options)
        self.sound_menu.configure(bg=BLACK, fg=YELLOW, activebackground=BLACK,
                                  activeforeground=WHITE, relief="solid", bd=1,
                                  highlightthickness=1, highlightbackground=RED,
                                  font=("Consolas", 9, "bold"))
        self.sound_menu["menu"].configure(bg=BLACK, fg=WHITE, activebackground=RED,
                                          activeforeground=WHITE, font=("Consolas", 9))
        self.sound_menu.pack(fill=tk.X, padx=14, pady=(0, 12))

        self._button(right, self._t("ADD / UPDATE COMMAND", "КОМАНДАНЫ ҚОСУ / ЖАҢАРТУ"), self._add_or_update, YELLOW).pack(fill=tk.X, padx=14, pady=8)
        self._button(right, self._t("CLEAR FORM", "ФОРМАНЫ ТАЗАРТУ"), self._clear_form, WHITE).pack(fill=tk.X, padx=14, pady=(0, 12))

        tk.Label(root, textvariable=self.status_var, bg=BLACK, fg=WHITE,
                 font=("Consolas", 9)).pack(anchor="w", padx=24, pady=(0, 16))

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for item in self.commands:
            kind = item.get("kind", "site")
            label = kind.upper() if self.language != "kz" else ("САЙТ" if kind == "site" else "ҚОЛДАНБА")
            self.listbox.insert(tk.END, f"{label}  {item.get('name', '')}  ->  {item.get('target', '')}")

    def _selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def _load_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        item = self.commands[idx]
        self.command_entry.delete(0, tk.END)
        self.command_entry.insert(0, item.get("name", ""))
        self.alias_entry.delete(0, tk.END)
        self.alias_entry.insert(0, ", ".join(item.get("aliases", [])))
        self.kind_var.set(item.get("kind", "site"))
        self.target_entry.delete(0, tk.END)
        self.target_entry.insert(0, item.get("target", ""))
        self.sound_var.set(item.get("sound", "ok"))

    def _add_or_update(self):
        name = self.command_entry.get().strip()
        target = self.target_entry.get().strip()
        if not name or not target:
            self.status_var.set(self._t("COMMAND TEXT AND TARGET ARE REQUIRED", "КОМАНДА МЕН МАҚСАТ ЖОЛЫ КЕРЕК"))
            return
        item = {
            "name": name,
            "aliases": [a.strip() for a in self.alias_entry.get().split(",") if a.strip()],
            "kind": self.kind_var.get(),
            "target": target,
            "sound": self.sound_var.get(),
        }
        idx = self._selected_index()
        if idx is None:
            self.commands.append(item)
        else:
            self.commands[idx] = item
        save_custom_commands(self.commands)
        self._refresh_list()
        self.status_var.set(self._t("COMMAND SAVED", "КОМАНДА САҚТАЛДЫ"))

    def _delete_selected(self):
        idx = self._selected_index()
        if idx is None:
            self.status_var.set(self._t("SELECT COMMAND TO DELETE", "ЖОЯТЫН КОМАНДАНЫ ТАҢДАҢЫЗ"))
            return
        del self.commands[idx]
        save_custom_commands(self.commands)
        self._refresh_list()
        self._clear_form()
        self.status_var.set(self._t("COMMAND DELETED", "КОМАНДА ЖОЙЫЛДЫ"))

    def _save_all(self):
        save_custom_commands(self.commands)
        self.status_var.set(self._t("CUSTOM COMMANDS WRITTEN", "ЖЕКЕ КОМАНДАЛАР САҚТАЛДЫ"))

    def _clear_form(self):
        self.command_entry.delete(0, tk.END)
        self.alias_entry.delete(0, tk.END)
        self.target_entry.delete(0, tk.END)
        self.kind_var.set("site")
        self.sound_var.set(self.sound_options[0])
        self.listbox.selection_clear(0, tk.END)


if __name__ == "__main__":
    JarvisSettings()
