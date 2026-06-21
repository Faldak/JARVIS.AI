import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
import tkinter as tk

from jarvis_data import APPS, BROWSER_PATHS, SITES

try:
    import cv2
    import mediapipe as mp
except Exception:
    cv2 = None
    mp = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


BLACK = "#000000"
BG = "#020814"
PANEL = "#061221"
CYAN = "#00D7FF"
BLUE = "#0A67FF"
DEEP = "#0B2140"
WHITE = "#DDF8FF"
YELLOW = "#F2D44B"
RED = "#FF3B30"
GREEN = "#3CFFB4"
MUTED = "#42627F"


def dim(color, factor):
    r = max(0, min(255, int(int(color[1:3], 16) * factor)))
    g = max(0, min(255, int(int(color[3:5], 16) * factor)))
    b = max(0, min(255, int(int(color[5:7], 16) * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def open_target(target):
    if not target:
        return False
    try:
        if target.startswith(("http://", "https://")):
            for browser in BROWSER_PATHS:
                if Path(browser).exists():
                    subprocess.Popen([browser, target])
                    return True
            webbrowser.open(target)
            return True
        if target.startswith("shell:"):
            subprocess.Popen(["explorer.exe", target])
            return True
        path = Path(target)
        if path.exists():
            os.startfile(str(path))
            return True
        subprocess.Popen(target, shell=True)
        return True
    except Exception:
        return False


@dataclass
class GraphNode:
    node_id: str
    title: str
    kind: str
    target: str = ""
    aliases: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    radius: float = 9.0
    weight: float = 1.0
    pulse: float = 0.0


@dataclass
class GraphEdge:
    source: str
    target: str
    kind: str = "link"
    weight: float = 1.0


def discover_obsidian_vaults():
    vaults = []
    config = Path(os.getenv("APPDATA", "")) / "obsidian" / "obsidian.json"
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            for item in data.get("vaults", {}).values():
                path = item.get("path") if isinstance(item, dict) else None
                if path and Path(path).exists():
                    vaults.append(Path(path))
        except (OSError, json.JSONDecodeError):
            pass
    for base in (Path.home() / "Documents", Path.home() / "Desktop"):
        if base.exists():
            for marker in base.glob("**/.obsidian"):
                vault = marker.parent
                if vault not in vaults:
                    vaults.append(vault)
                if len(vaults) >= 4:
                    break
    return vaults[:4]


def parse_obsidian_notes(vaults, max_notes=260):
    notes = {}
    edges = []
    for vault in vaults:
        for path in vault.rglob("*.md"):
            if ".obsidian" in path.parts:
                continue
            title = path.stem.strip()
            if not title:
                continue
            node_id = f"obsidian:{path}"
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            notes[title.lower()] = (node_id, title, str(path), text[:4000])
            if len(notes) >= max_notes:
                break
        if len(notes) >= max_notes:
            break
    title_to_id = {title: item[0] for title, item in notes.items()}
    for title, (node_id, _, _, text) in notes.items():
        for raw in re.findall(r"\[\[([^\]#|]+)", text):
            target_title = raw.strip().lower()
            target_id = title_to_id.get(target_title)
            if target_id:
                edges.append(GraphEdge(node_id, target_id, "obsidian", 1.25))
    return notes, edges


class JarvisGraphModel:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.vaults = discover_obsidian_vaults()
        self._build()

    def add_node(self, node):
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, source, target, kind="link", weight=1.0):
        if source in self.nodes and target in self.nodes:
            self.edges.append(GraphEdge(source, target, kind, weight))

    def _build(self):
        rng = Random(42)
        clusters = {
            "sites": ("Сайты", -250, -40, CYAN),
            "apps": ("Приложения", 230, -40, BLUE),
            "scenarios": ("Сценарии", 0, 220, YELLOW),
            "obsidian": ("Obsidian", 0, -260, GREEN),
            "memory": ("Память", -20, 0, WHITE),
        }
        for key, (title, x, y, _) in clusters.items():
            self.add_node(GraphNode(f"cluster:{key}", title, "cluster", x=x, y=y, z=0, radius=18, weight=4.0))

        for index, (key, title, url, aliases) in enumerate(SITES):
            angle = index * 0.47
            r = 90 + (index % 7) * 18
            node = GraphNode(
                f"site:{key}", title, "site", url, aliases,
                x=-250 + math.cos(angle) * r,
                y=-40 + math.sin(angle) * r,
                z=math.sin(angle * 0.83) * 135,
                radius=8 + min(8, len(aliases)),
                weight=1.3,
            )
            self.add_node(node)
            self.add_edge("cluster:sites", node.node_id, "contains", 0.7)

        for index, (key, title, target, aliases) in enumerate(APPS):
            angle = index * 0.76
            r = 80 + (index % 5) * 20
            node = GraphNode(
                f"app:{key}", title, "app", target, aliases,
                x=230 + math.cos(angle) * r,
                y=-40 + math.sin(angle) * r,
                z=math.cos(angle * 0.71) * 130,
                radius=10,
                weight=1.4,
            )
            self.add_node(node)
            self.add_edge("cluster:apps", node.node_id, "contains", 0.7)

        scenarios = {
            "rest": ("Режим отдыха", ["site:youtube", "site:kinopoisk", "site:yandex_music", "app:steam"]),
            "work": ("Режим работы", ["app:claude", "app:codex", "app:vscode", "site:yandex_music"]),
            "search": ("Поиск и ссылки", ["site:google", "site:youtube", "site:wikipedia", "site:translate"]),
            "music": ("Музыка", ["site:yandex_music", "site:spotify", "site:youtube"]),
        }
        for index, (key, (title, links)) in enumerate(scenarios.items()):
            angle = index * math.tau / max(1, len(scenarios))
            node = self.add_node(GraphNode(
                f"scenario:{key}", title, "scenario",
                x=math.cos(angle) * 130,
                y=220 + math.sin(angle) * 70,
                z=math.sin(angle) * 95,
                radius=13,
                weight=2.0,
            ))
            self.add_edge("cluster:scenarios", node.node_id, "contains", 1.1)
            for link in links:
                self.add_edge(node.node_id, link, "uses", 1.35)

        memory_path = Path(__file__).with_name("jarvis_memory.json")
        if memory_path.exists():
            try:
                memory = json.loads(memory_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                memory = {}
            for key, value in memory.items():
                if value:
                    title = "Заметка" if key == "note" else key
                    node = self.add_node(GraphNode(
                        f"memory:{key}", title, "memory", str(value), [],
                        x=rng.uniform(-80, 80), y=rng.uniform(-80, 80), z=rng.uniform(-90, 90),
                        radius=11, weight=1.6,
                    ))
                    self.add_edge("cluster:memory", node.node_id, "contains", 1.0)

        notes, obsidian_edges = parse_obsidian_notes(self.vaults)
        for index, (_, (node_id, title, path, text)) in enumerate(notes.items()):
            angle = index * 0.55
            r = 80 + (index % 9) * 17
            node = GraphNode(
                node_id, title, "obsidian", path, [],
                x=math.cos(angle) * r,
                y=-260 + math.sin(angle) * r,
                z=math.sin(angle * 1.17) * 170,
                radius=7 + min(6, text.count("[[")),
                weight=1.0 + min(2.5, text.count("[[") * 0.15),
            )
            self.add_node(node)
            self.add_edge("cluster:obsidian", node.node_id, "contains", 0.55)
        self.edges.extend(obsidian_edges)

        self._connect_related_sites()

    def _connect_related_sites(self):
        groups = [
            ("media", ["site:youtube", "site:yandex_music", "site:kinopoisk", "site:spotify", "site:twitch", "site:rutube"]),
            ("news", ["site:tengrinews", "site:informburo", "site:zakon", "site:kazinform", "site:nur", "site:kursiv", "site:kapital"]),
            ("work", ["site:chatgpt", "site:claude", "site:github", "site:stackoverflow", "site:docs", "site:drive"]),
            ("money", ["site:tenge", "site:dollar", "site:kurs", "site:kaspi", "site:halyk"]),
        ]
        for kind, ids in groups:
            available = [node_id for node_id in ids if node_id in self.nodes]
            for a, b in zip(available, available[1:]):
                self.add_edge(a, b, kind, 1.1)

    def openable_nodes(self):
        return [node for node in self.nodes.values() if node.kind in {"site", "app", "obsidian"} and node.target]


class CameraFeed:
    def __init__(self, out_queue, frame_queue=None, camera_index=None):
        self.out_queue = out_queue
        self.frame_queue = frame_queue
        self.camera_index = camera_index
        self.running = False
        self.thread = None
        self.last_frame_emit = 0

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _open_camera(self):
        if cv2 is None:
            return None, "opencv не установлен"
        backends = [
            ("DSHOW", cv2.CAP_DSHOW),
            ("MSMF", cv2.CAP_MSMF),
            ("ANY", 0),
        ]
        preferred = 0 if self.camera_index is None else self.camera_index
        indices = [preferred] + [idx for idx in range(4) if idx != preferred]
        for backend_name, backend in backends:
            for index in indices:
                cap = cv2.VideoCapture(index, backend)
                if not cap.isOpened():
                    cap.release()
                    continue
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                ok, _ = cap.read()
                if ok:
                    return cap, f"камера активна: {backend_name} #{index}"
                cap.release()
        return None, "камера не найдена"

    def _run(self):
        cap, status = self._open_camera()
        if cap is None:
            self.out_queue.put({"gesture": "status", "text": status})
            self.running = False
            return
        self.out_queue.put({"gesture": "camera_status", "text": status})
        try:
            while self.running:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.04)
                    continue
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._emit_frame(rgb)
                if self.frame_queue is not None:
                    while True:
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            break
                    self.frame_queue.put(rgb)
                time.sleep(0.02)
        finally:
            cap.release()
            self.running = False
            self.out_queue.put({"gesture": "camera_status", "text": "камера остановлена"})

    def _emit_frame(self, rgb):
        if Image is None or ImageTk is None:
            return
        now = time.time()
        if now - self.last_frame_emit < 0.10:
            return
        self.last_frame_emit = now
        try:
            preview = cv2.resize(rgb, (960, 540), interpolation=cv2.INTER_AREA)
            self.out_queue.put({
                "gesture": "frame",
                "text": "камера показывает",
                "size": (960, 540),
                "data": preview.tobytes(),
            })
        except Exception:
            pass


class GestureReader:
    def __init__(self, out_queue, frame_queue):
        self.out_queue = out_queue
        self.frame_queue = frame_queue
        self.camera_index = None
        self.running = False
        self.thread = None
        self.last_center = None
        self.last_palm_roll = None
        self.last_palm_tilt = None
        self.last_emit = 0
        self.last_gesture = ""
        self.cooldowns = {}

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _emit(self, gesture, **data):
        now = time.time()
        hold = 0.08 if gesture in ("palm", "point", "two_hand_zoom") else 0.65
        if gesture == self.last_gesture and now - self.last_emit < hold:
            return
        self.last_gesture = gesture
        self.last_emit = now
        data["gesture"] = gesture
        self.out_queue.put(data)

    def _cool(self, name, seconds):
        now = time.time()
        if now < self.cooldowns.get(name, 0):
            return False
        self.cooldowns[name] = now + seconds
        return True

    def _run(self):
        if cv2 is None or mp is None:
            self.out_queue.put({"gesture": "status", "text": "mediapipe/opencv не установлены"})
            self.running = False
            return
        hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55,
        )
        self.out_queue.put({"gesture": "gesture_status", "text": "жесты активны"})
        try:
            while self.running:
                try:
                    rgb = self.frame_queue.get(timeout=0.25)
                except queue.Empty:
                    self._emit("none", text="камера ожидается")
                    continue
                result = hands.process(rgb)
                if not result.multi_hand_landmarks:
                    self.last_center = None
                    self.last_palm_roll = None
                    self.last_palm_tilt = None
                    self._emit("none", text="рука не видна")
                    continue
                gesture_data = self._classify_hands([hand.landmark for hand in result.multi_hand_landmarks])
                if gesture_data:
                    self._emit(**gesture_data)
                time.sleep(0.025)
        finally:
            hands.close()
            self.running = False
            self.out_queue.put({"gesture": "gesture_status", "text": "жесты остановлены"})

    def _finger_extended(self, lm, tip, pip):
        return lm[tip].y < lm[pip].y - 0.025

    def _thumb_extended(self, lm):
        return self._distance(lm[4], lm[9]) > self._distance(lm[3], lm[9]) + 0.025

    def _distance(self, a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    def _palm_orientation(self, lm):
        roll = math.atan2(lm[17].y - lm[5].y, lm[17].x - lm[5].x)
        wrist_to_middle = max(0.05, self._distance(lm[0], lm[9]))
        side_span = self._distance(lm[5], lm[17])
        tilt = clamp((side_span / wrist_to_middle - 0.78) * 1.8, -1.0, 1.0)
        return roll, tilt

    def _hand_state(self, lm):
        index = self._finger_extended(lm, 8, 6)
        middle = self._finger_extended(lm, 12, 10)
        ring = self._finger_extended(lm, 16, 14)
        pinky = self._finger_extended(lm, 20, 18)
        thumb = self._thumb_extended(lm)
        folded = sum(not v for v in (index, middle, ring, pinky))
        open_palm = index and middle and ring and pinky and self._distance(lm[4], lm[17]) > 0.13
        fist = folded >= 4
        return {
            "index": index,
            "middle": middle,
            "ring": ring,
            "pinky": pinky,
            "thumb": thumb,
            "folded": folded,
            "open_palm": open_palm,
            "fist": fist,
        }

    def _classify_hands(self, hands):
        if len(hands) >= 2:
            states = [self._hand_state(hand) for hand in hands[:2]]
            palms = sum(1 for state in states if state["open_palm"])
            fists = sum(1 for state in states if state["fist"])
            if palms == 2:
                self.last_center = None
                return {"gesture": "two_hand_zoom", "text": "приближение", "delta": 0.018}
            if fists == 1:
                self.last_center = None
                return {"gesture": "two_hand_zoom", "text": "отдаление", "delta": -0.018}
        return self._classify(hands[0])

    def _classify(self, lm):
        wrist = lm[0]
        center = ((lm[0].x + lm[9].x) / 2, (lm[0].y + lm[9].y) / 2)
        dx = dy = 0.0
        if self.last_center:
            dx = center[0] - self.last_center[0]
            dy = center[1] - self.last_center[1]
        self.last_center = center

        index = self._finger_extended(lm, 8, 6)
        middle = self._finger_extended(lm, 12, 10)
        ring = self._finger_extended(lm, 16, 14)
        pinky = self._finger_extended(lm, 20, 18)
        thumb = self._thumb_extended(lm)
        folded = sum(not v for v in (index, middle, ring, pinky))
        thumb_tip = lm[4]
        thumb_up = thumb_tip.y < wrist.y - 0.13 and thumb and folded >= 3
        two_fingers = index and middle and not ring and not pinky
        open_palm = index and middle and ring and pinky and self._distance(lm[4], lm[17]) > 0.13
        call_sign = thumb and pinky and not index and not middle and not ring

        if call_sign and self._cool("call_open", 1.6):
            return {"gesture": "call_open", "text": "открыть выбранное"}
        if thumb_up and self._cool("thumb", 0.9):
            return {"gesture": "thumb_up", "text": "следующий узел"}
        if two_fingers and self._cool("two", 0.9):
            return {"gesture": "two_fingers", "text": "нейронный вид"}
        if abs(dx) > 0.105 and self._cool("swipe", 0.7):
            return {"gesture": "swipe_right" if dx > 0 else "swipe_left", "text": "переключение", "dx": dx}
        if open_palm:
            roll, tilt = self._palm_orientation(lm)
            roll_delta = 0.0
            tilt_delta = 0.0
            if self.last_palm_roll is not None:
                roll_delta = roll - self.last_palm_roll
                if roll_delta > math.pi:
                    roll_delta -= math.tau
                elif roll_delta < -math.pi:
                    roll_delta += math.tau
            if self.last_palm_tilt is not None:
                tilt_delta = tilt - self.last_palm_tilt
            self.last_palm_roll = roll
            self.last_palm_tilt = tilt
            return {"gesture": "palm", "text": "кисть вращается", "roll": roll_delta, "tilt": tilt_delta}
        self.last_palm_roll = None
        self.last_palm_tilt = None
        if index and not middle and not ring and not pinky:
            return {"gesture": "point", "text": "выбор", "dx": dx, "dy": dy, "x": lm[8].x, "y": lm[8].y}
        return {"gesture": "idle", "text": "жест не выбран"}


class JarvisGraphWindow:
    FPS = 30

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S Graph")
        self.root.configure(bg=BLACK)
        self.root.geometry("1420x860")
        self.root.minsize(1060, 700)
        self.canvas = tk.Canvas(self.root, bg=BLACK, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.model = JarvisGraphModel()
        self.openable = self.model.openable_nodes()
        self.selected_index = 0
        self.selected_id = self.openable[0].node_id if self.openable else None
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.rotation_x = -0.18
        self.rotation_y = 0.34
        self.rotation_z = 0.0
        self.t = 0.0
        self.last = time.time()
        self.status = "3D GRAPH ONLINE"
        self.gesture_text = "камера запускается"
        self.gesture_queue = queue.Queue()
        self.camera_frame_queue = queue.Queue(maxsize=1)
        self.camera = CameraFeed(self.gesture_queue, self.camera_frame_queue)
        self.gestures = GestureReader(self.gesture_queue, self.camera_frame_queue)
        self.drag_last = None
        self.node_screen = {}
        self.zones = []
        self.camera_image = None
        self.camera_pil = None
        self.camera_bg_photo = None
        self.camera_seen_at = 0.0
        self.running = True

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda event: self.close())
        self.root.bind("g", lambda event: self.toggle_gestures())
        self.root.bind("G", lambda event: self.toggle_gestures())
        self.root.bind("<space>", lambda event: self.open_selected())
        self.root.bind("<Return>", lambda event: self.open_selected())
        self.root.bind("<Left>", lambda event: self.previous_node())
        self.root.bind("<Right>", lambda event: self.next_node())
        self.root.bind("<Up>", lambda event: self.zoom_in())
        self.root.bind("<Down>", lambda event: self.zoom_out())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda event: setattr(self, "drag_last", None))
        self.canvas.bind("<MouseWheel>", self._wheel)

        self.root.after(350, self.start_camera)
        self.root.after(900, self.start_gestures)
        self._loop()
        self.root.mainloop()

    def close(self):
        self.running = False
        self.camera.stop()
        self.gestures.stop()
        self.root.destroy()

    def toggle_gestures(self):
        if self.gestures.running:
            self.gestures.stop()
            self.gesture_text = "камера выключена"
            self.status = "GESTURE OFF"
        else:
            self.start_gestures()

    def start_camera(self):
        if self.camera.running:
            return
        self.camera.start()
        self.gesture_text = "камера запускается"
        self.status = "CAMERA ON"

    def start_gestures(self):
        if self.gestures.running:
            return
        self.start_camera()
        self.gestures.start()
        self.gesture_text = "камера запускается"
        self.status = "GESTURE ON"

    def next_node(self):
        if not self.openable:
            return
        self.selected_index = (self.selected_index + 1) % len(self.openable)
        self.selected_id = self.openable[self.selected_index].node_id
        self.model.nodes[self.selected_id].pulse = 1.0
        self.status = "NEXT LINK"

    def previous_node(self):
        if not self.openable:
            return
        self.selected_index = (self.selected_index - 1) % len(self.openable)
        self.selected_id = self.openable[self.selected_index].node_id
        self.model.nodes[self.selected_id].pulse = 1.0
        self.status = "PREVIOUS LINK"

    def open_selected(self):
        node = self.model.nodes.get(self.selected_id)
        if not node:
            return
        ok = open_target(node.target)
        node.pulse = 1.6
        self.status = f"OPEN: {node.title}" if ok else f"FAILED: {node.title}"

    def zoom_in(self):
        self.zoom = clamp(self.zoom * 1.12, 0.35, 3.0)

    def zoom_out(self):
        self.zoom = clamp(self.zoom / 1.12, 0.35, 3.0)

    def apply_smooth_zoom(self, delta):
        if abs(delta) < 0.003:
            return
        factor = 1.0 + clamp(delta, -0.035, 0.035)
        self.zoom = clamp(self.zoom * factor, 0.35, 3.0)
        self.status = "TWO HAND ZOOM IN" if delta > 0 else "TWO HAND ZOOM OUT"

    def select_node_by_pointer(self, norm_x, norm_y):
        if not self.node_screen:
            return
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        px = clamp(norm_x, 0.0, 1.0) * w
        py = clamp(norm_y, 0.0, 1.0) * h
        candidates = []
        for node_id, (sx, sy, depth) in self.node_screen.items():
            node = self.model.nodes.get(node_id)
            if not node or node.kind not in {"site", "app", "obsidian"}:
                continue
            dist = math.hypot(px - sx, py - sy)
            if dist < 115:
                candidates.append((dist - depth * 0.012, node_id))
        if not candidates:
            self.status = "POINT SELECT"
            return
        _, node_id = min(candidates, key=lambda item: item[0])
        if node_id != self.selected_id:
            self.selected_id = node_id
            self.model.nodes[node_id].pulse = 1.1
            for index, node in enumerate(self.openable):
                if node.node_id == node_id:
                    self.selected_index = index
                    break
        self.status = f"POINT: {self.model.nodes[node_id].title}"

    def reset_view(self):
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.rotation_x = -0.18
        self.rotation_y = 0.34
        self.rotation_z = 0.0
        self.status = "3D NEURAL VIEW"

    def _loop(self):
        if not self.running:
            return
        now = time.time()
        dt = min(now - self.last, 0.05)
        self.last = now
        self.t += dt
        self._drain_gestures()
        self._update_nodes(dt)
        self._render()
        self.root.after(1000 // self.FPS, self._loop)

    def _drain_gestures(self):
        while True:
            try:
                event = self.gesture_queue.get_nowait()
            except queue.Empty:
                break
            gesture = event.get("gesture")
            if gesture == "frame":
                self._update_camera_preview(event)
                continue
            self.gesture_text = event.get("text", gesture)
            if gesture in ("status", "camera_status", "gesture_status"):
                self.status = event.get("text", self.status)
            elif gesture == "thumb_up":
                self.next_node()
            elif gesture == "swipe_left":
                self.next_node()
            elif gesture == "swipe_right":
                self.previous_node()
            elif gesture == "two_hand_zoom":
                self.apply_smooth_zoom(event.get("delta", 0.0))
            elif gesture == "call_open":
                self.open_selected()
            elif gesture == "two_fingers":
                self.reset_view()
            elif gesture == "palm":
                self.rotation_y += event.get("roll", 0) * 1.35
                self.rotation_x += event.get("tilt", 0) * 0.85
                self.rotation_x = clamp(self.rotation_x, -1.15, 1.15)
                self.status = "WRIST ROTATION CONTROL"
            elif gesture == "point":
                self.select_node_by_pointer(event.get("x", 0.5), event.get("y", 0.5))

    def _update_camera_preview(self, event):
        if Image is None or ImageTk is None:
            return
        size = event.get("size")
        data = event.get("data")
        if not size or not data:
            return
        try:
            image = Image.frombytes("RGB", size, data)
            self.camera_pil = image
            self.camera_seen_at = time.time()
            self.gesture_text = event.get("text", "камера показывает")
        except Exception as exc:
            self.gesture_text = f"preview error: {exc}"

    def _update_nodes(self, dt):
        selected = self.model.nodes.get(self.selected_id)
        for node in self.model.nodes.values():
            node.pulse = max(0.0, node.pulse - dt * 1.4)
            drift = 0.35 if node.kind != "cluster" else 0.12
            node.x += math.sin(self.t * 0.7 + hash(node.node_id) % 50) * drift * dt
            node.y += math.cos(self.t * 0.5 + hash(node.title) % 50) * drift * dt
            node.z += math.sin(self.t * 0.45 + hash(node.kind + node.title) % 50) * drift * 0.55 * dt
        if selected:
            selected.pulse = max(selected.pulse, 0.18 + 0.12 * math.sin(self.t * 4))

    def _world_to_screen(self, x, y, z=0.0):
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        cy, sy = math.cos(self.rotation_y), math.sin(self.rotation_y)
        cx, sx = math.cos(self.rotation_x), math.sin(self.rotation_x)
        cz, sz = math.cos(self.rotation_z), math.sin(self.rotation_z)

        x1 = x * cy + z * sy
        z1 = -x * sy + z * cy
        y2 = y * cx - z1 * sx
        z2 = y * sx + z1 * cx
        x3 = x1 * cz - y2 * sz
        y3 = x1 * sz + y2 * cz

        camera_distance = 760.0
        scale = camera_distance / max(260.0, camera_distance - z2)
        sx_ = w * 0.52 + self.pan_x + x3 * self.zoom * scale
        sy_ = h * 0.50 + self.pan_y + y3 * self.zoom * scale
        return sx_, sy_, z2, scale

    def _node_color(self, node):
        return {
            "site": CYAN,
            "app": BLUE,
            "scenario": YELLOW,
            "obsidian": GREEN,
            "memory": WHITE,
            "cluster": RED,
        }.get(node.kind, WHITE)

    def _render(self):
        c = self.canvas
        c.delete("all")
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        self.node_screen = {}
        self.zones = []
        c.create_rectangle(0, 0, w, h, fill=BLACK, outline="")
        self._draw_background(c, w, h)

        projected = {
            node_id: self._world_to_screen(node.x, node.y, node.z)
            for node_id, node in self.model.nodes.items()
        }

        def edge_depth(edge):
            a = projected.get(edge.source, (0, 0, -999, 1))
            b = projected.get(edge.target, (0, 0, -999, 1))
            return (a[2] + b[2]) / 2

        for edge in sorted(self.model.edges, key=edge_depth):
            a = self.model.nodes.get(edge.source)
            b = self.model.nodes.get(edge.target)
            if not a or not b:
                continue
            ax, ay, az, _ = projected[a.node_id]
            bx, by, bz, _ = projected[b.node_id]
            selected_edge = self.selected_id in (edge.source, edge.target)
            color = CYAN if selected_edge else MUTED
            pulse = 0.45 + 0.35 * math.sin(self.t * 2.2 + edge.weight)
            depth_alpha = clamp(((az + bz) / 2 + 280) / 620, 0.18, 1.0)
            c.create_line(ax, ay, bx, by, fill=dim(color, (0.12 + pulse * 0.20) * depth_alpha), width=2 if selected_edge else 1)

        sorted_nodes = sorted(self.model.nodes.values(), key=lambda node: projected[node.node_id][2])
        for node in sorted_nodes:
            sx, sy, depth, scale = projected[node.node_id]
            self.node_screen[node.node_id] = (sx, sy, depth)
            color = self._node_color(node)
            selected = node.node_id == self.selected_id
            depth_alpha = clamp((depth + 310) / 640, 0.26, 1.0)
            r = (node.radius + node.pulse * 10 + (6 if selected else 0)) * self.zoom ** 0.28 * scale
            for mul, alpha in ((3.6, 0.055), (2.1, 0.13)):
                c.create_oval(sx-r*mul, sy-r*mul, sx+r*mul, sy+r*mul, fill=dim(color, alpha * depth_alpha), outline="")
            c.create_oval(
                sx-r, sy-r, sx+r, sy+r,
                fill=dim(color, (0.45 if selected else 0.24) * depth_alpha),
                outline=dim(color, depth_alpha),
                width=2 if selected else 1,
            )
            if selected:
                c.create_oval(sx-r*1.65, sy-r*1.65, sx+r*1.65, sy+r*1.65, outline=dim(WHITE, 0.70), width=1)
            if selected or node.kind == "cluster" or (self.zoom > 1.25 and node.kind in {"site", "app", "obsidian"}):
                c.create_text(sx, sy - r - 13, text=node.title[:28], fill=dim(WHITE, (0.90 if selected else 0.48) * depth_alpha), font=("Consolas", 9, "bold" if selected else "normal"))

        self._draw_hud(c, w, h)

    def _draw_background(self, c, w, h):
        fresh_camera = self.camera_pil is not None and time.time() - self.camera_seen_at < 1.2
        if fresh_camera and Image is not None and ImageTk is not None:
            src_w, src_h = self.camera_pil.size
            scale = max(w / src_w, h / src_h)
            new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
            frame = self.camera_pil.resize(new_size, Image.Resampling.BILINEAR)
            left = max(0, (new_size[0] - w) // 2)
            top = max(0, (new_size[1] - h) // 2)
            frame = frame.crop((left, top, left + w, top + h))
            frame = Image.blend(frame, Image.new("RGB", frame.size, (0, 0, 0)), 0.48)
            tint = Image.new("RGB", frame.size, (0, 18, 34))
            frame = Image.blend(frame, tint, 0.26)
            self.camera_bg_photo = ImageTk.PhotoImage(frame)
            c.create_image(0, 0, image=self.camera_bg_photo, anchor="nw")
        else:
            c.create_rectangle(0, 0, w, h, fill=BG, outline="")
        cx, cy = w * 0.52, h * 0.50
        for r, alpha in ((470, 0.10), (310, 0.16), (165, 0.24)):
            c.create_oval(cx-r, cy-r*0.72, cx+r, cy+r*0.72, outline=dim(CYAN, alpha), width=1)
        horizon = h * 0.50
        for i in range(9):
            offset = (i - 4) * 58
            c.create_line(cx + offset, horizon - 360, cx + offset * 0.28, horizon + 330, fill=dim(DEEP, 0.20), width=1)
        for i in range(8):
            y = horizon + i * 44
            c.create_line(cx - 520 + i * 54, y, cx + 520 - i * 54, y, fill=dim(DEEP, 0.18), width=1)

    def _draw_hud(self, c, w, h):
        c.create_text(34, 28, text="JARVIS GRAPH", fill=CYAN, anchor="w", font=("Consolas", 24, "bold"))
        c.create_text(36, 58, text="3D Obsidian + commands + links neural model", fill=dim(WHITE, 0.40), anchor="w", font=("Consolas", 9))
        c.create_text(w - 34, 28, text=self.status, fill=YELLOW, anchor="e", font=("Consolas", 12, "bold"))
        c.create_text(w - 34, 54, text=f"gesture: {self.gesture_text}", fill=dim(WHITE, 0.48), anchor="e", font=("Consolas", 9))
        bw, bh = 128, 30
        bx, by = w - 34 - bw, 76
        camera_on = self.camera.running
        c.create_rectangle(bx, by, bx + bw, by + bh, fill=dim(PANEL, 0.95), outline=dim(GREEN if camera_on else CYAN, 0.70), width=1)
        c.create_text(bx + bw / 2, by + bh / 2, text="CAMERA ON" if camera_on else "CAMERA OFF", fill=GREEN if camera_on else WHITE, font=("Consolas", 9, "bold"))
        self.zones.append((bx, by, bx + bw, by + bh, self.start_camera if not camera_on else self.camera.stop))
        camera_live = self.camera_pil is not None and time.time() - self.camera_seen_at < 1.2
        c.create_text(
            bx + bw / 2, by + bh + 16,
            text="LIVE BACKGROUND" if camera_live else "WAITING FOR FEED",
            fill=GREEN if camera_live else dim(YELLOW, 0.75),
            font=("Consolas", 8, "bold"),
        )

        panel_w = 330
        c.create_rectangle(26, h - 178, 26 + panel_w, h - 26, fill=dim(PANEL, 0.90), outline=dim(CYAN, 0.45), width=1)
        node = self.model.nodes.get(self.selected_id)
        if node:
            c.create_text(46, h - 150, text=node.title[:34], fill=WHITE, anchor="w", font=("Consolas", 15, "bold"))
            c.create_text(46, h - 124, text=f"type: {node.kind}", fill=dim(CYAN, 0.68), anchor="w", font=("Consolas", 9))
            target = node.target if node.kind != "obsidian" else Path(node.target).name
            c.create_text(46, h - 100, text=target[:48], fill=dim(WHITE, 0.45), anchor="w", font=("Consolas", 8))
        c.create_text(46, h - 62, text="G камера  |  Space открыть  |  Wheel zoom  |  указательный выбирает", fill=dim(WHITE, 0.55), anchor="w", font=("Consolas", 8))
        c.create_text(46, h - 42, text="Жесты: ладонь rotate, 2 ладони zoom-in, кулак+рука zoom-out, CALL open", fill=dim(WHITE, 0.55), anchor="w", font=("Consolas", 8))

        vault_text = ", ".join(v.name for v in self.model.vaults) if self.model.vaults else "Obsidian vault не найден"
        c.create_text(w - 34, h - 35, text=f"vault: {vault_text}", fill=dim(WHITE, 0.35), anchor="e", font=("Consolas", 8))

    def _draw_camera_preview(self, c, w, h):
        pw, ph = 284, 206
        x2 = w - 34
        y1 = 118
        x1 = x2 - pw
        c.create_rectangle(x1, y1, x2, y1 + ph, fill=dim(PANEL, 0.86), outline=dim(CYAN, 0.46), width=1)
        c.create_text(x1 + 14, y1 + 17, text="CAMERA FEED", fill=dim(WHITE, 0.78), anchor="w", font=("Consolas", 9, "bold"))
        fresh = self.camera_image is not None and time.time() - self.camera_seen_at < 1.2
        if fresh:
            c.create_image(x1 + 12, y1 + 34, image=self.camera_image, anchor="nw")
            c.create_rectangle(x1 + 12, y1 + 34, x1 + 272, y1 + 194, outline=dim(GREEN, 0.70), width=1)
        else:
            c.create_rectangle(x1 + 12, y1 + 34, x1 + 272, y1 + 194, fill=BLACK, outline=dim(MUTED, 0.65), width=1)
            text = "camera starting..." if self.gestures.running else "camera off"
            c.create_text(x1 + pw / 2, y1 + 112, text=text, fill=dim(WHITE, 0.45), font=("Consolas", 10, "bold"))
        state = "LIVE" if fresh else ("WAITING" if self.gestures.running else "OFF")
        c.create_text(x2 - 14, y1 + 17, text=state, fill=GREEN if fresh else YELLOW, anchor="e", font=("Consolas", 9, "bold"))

    def _click(self, event):
        for x1, y1, x2, y2, action in self.zones:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                action()
                return
        nearest = None
        best = 999999
        for node_id, (x, y, _depth) in self.node_screen.items():
            dist = math.hypot(event.x - x, event.y - y)
            if dist < best:
                best = dist
                nearest = node_id
        if nearest and best < 32:
            self.selected_id = nearest
            for index, node in enumerate(self.openable):
                if node.node_id == nearest:
                    self.selected_index = index
                    break
            self.model.nodes[nearest].pulse = 1.2

    def _drag(self, event):
        if self.drag_last:
            lx, ly = self.drag_last
            self.rotation_y += (event.x - lx) * 0.004
            self.rotation_x += (event.y - ly) * 0.004
            self.rotation_x = clamp(self.rotation_x, -1.15, 1.15)
            self.status = "MOUSE 3D ROTATION"
        self.drag_last = (event.x, event.y)

    def _wheel(self, event):
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()


def main():
    JarvisGraphWindow()


if __name__ == "__main__":
    main()
