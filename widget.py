#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeskHUD — küçük masaüstü HUD widget'ı.

GTK3 + WebKit2 ile panoyu küçük, çerçevesiz, üstte duran bir pencerede gösterir.
Üç mod vardır:

  * Tam mod     : /widget    (340x264)
  * Mini mod    : /mini      (320x22)
  * Ayarlar     : /settings  (360x540)

Kullanım:
    python3 widget.py            # son kullanılan mod
    python3 widget.py --mini     # mini başlat
    python3 widget.py --full     # tam başlat

Geçiş:
  * Üstteki siyah tutamağa ÇİFT TIK  -> mini / tam
  * Sağ tık -> "Mini mod" / "Ayarlar"
  * 'm' -> mini/tam,  's' -> ayarlar
  * Mini şerit: ▣ (genişlet), ⚙ (ayarlar)
  * Tam mod: "küçült –" ve ⚙

Kapatma:
  * Sağ tık -> Kapat, veya Esc / q.
"""
import os
import sys
import time as _time

# XWayland üzerinden çalıştır: konumlandırma ve "üstte tut" daha güvenilir olur.
os.environ["GDK_BACKEND"] = "x11"

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

BASE = os.environ.get("EPANEL_BASE", "http://127.0.0.1:8787")
WIDTH = int(os.environ.get("EPANEL_WIDTH", "340"))
HEIGHT = int(os.environ.get("EPANEL_HEIGHT", "264"))

MINI_W, MINI_H = 430, 44
SET_W, SET_H = 360, 640
HANDLE_H = 12
MINI_HANDLE_H = 4

HERE = os.path.dirname(os.path.abspath(__file__))
MODE_FILE = os.path.join(HERE, "widget-mode.txt")
POS_FILE = os.path.join(HERE, "widget-pos.txt")

URLS = {"full": "/widget", "mini": "/mini", "settings": "/settings"}


def load_mode():
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            m = f.read().strip()
        return m if m in ("mini", "full") else None
    except Exception:
        return None


def save_mode(mode):
    if mode not in ("mini", "full"):
        return
    try:
        with open(MODE_FILE, "w", encoding="utf-8") as f:
            f.write(mode)
    except Exception:
        pass


def load_pos():
    try:
        with open(POS_FILE, "r", encoding="utf-8") as f:
            parts = f.read().strip().split(",")
        return int(parts[0]), int(parts[1])
    except Exception:
        return None


def save_pos(x, y):
    try:
        with open(POS_FILE, "w", encoding="utf-8") as f:
            f.write(f"{int(x)},{int(y)}")
    except Exception:
        pass


def dbg(msg):
    try:
        with open(os.path.join(HERE, "widget-debug.log"), "a", encoding="utf-8") as f:
            f.write(f"{_time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


class Widget(Gtk.Window):
    def __init__(self, start_mode="full"):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.mode = start_mode
        self.prev_mode = "full"

        self.set_title("e-Panel")
        self.set_resizable(False)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        css = Gtk.CssProvider()
        css.load_from_data(b"window { background-color: #000000; }")
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.webview = WebKit2.WebView()
        self.webview.set_background_color(Gdk.RGBA(1, 1, 1, 1))
        self.webview.connect("decide-policy", self.on_decide_policy)
        self.webview.connect("button-press-event", self.on_web_press)

        self.handle = Gtk.EventBox()
        self.handle.modify_bg(Gtk.StateType.NORMAL, Gdk.Color(0, 0, 0))
        self.handle.connect("button-press-event", self.on_press)
        self.handle.connect("button-release-event", self.on_release)
        self.handle.connect("motion-notify-event", self.on_motion)

        self.grip = Gtk.Label()
        self.grip.set_markup(
            '<span foreground="#8a8a8a" size="x-small">&#183; &#183; &#183;</span>')
        self.grip.set_halign(Gtk.Align.CENTER)
        self.grip.set_valign(Gtk.Align.CENTER)
        self.handle.add(self.grip)
        self.handle.connect("realize", self.on_handle_realize)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self.handle, False, False, 0)
        box.pack_start(self.webview, True, True, 0)
        self.add(box)

        self.connect("map-event", self.on_map)
        self.connect("configure-event", self.on_configure)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key)

        self._drag = None
        self._ready = False
        self._restored = False
        self._save_timer = None
        self.handle.set_size_request(-1, self._handle_h())
        self.grip.set_visible(self.mode != "mini")
        self._apply_size()
        self.webview.load_uri(self._url())

    # --- mod / boyut ---
    def _url(self):
        return BASE + URLS.get(self.mode, "/widget")

    def _dims(self):
        return {
            "full": (WIDTH, HEIGHT),
            "mini": (MINI_W, MINI_H),
            "settings": (SET_W, SET_H),
        }.get(self.mode, (WIDTH, HEIGHT))

    def _handle_h(self):
        return MINI_HANDLE_H if self.mode == "mini" else HANDLE_H

    def _apply_size(self):
        w, h = self._dims()
        self.set_default_size(w, h)
        self.set_resizable(True)
        self.resize(w, h)
        geom = Gdk.Geometry()
        geom.min_width = w
        geom.min_height = h
        geom.max_width = w
        geom.max_height = h
        self.set_geometry_hints(
            None, geom, Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE)

    def set_mode(self, mode, initial=False):
        if mode not in URLS:
            return
        if mode == self.mode and not initial:
            return
        dbg(f"set_mode {self.mode} -> {mode} (initial={initial})")
        old_w = self.get_size()[0] if not initial else self._dims()[0]
        x, y = self.get_position() if not initial else (0, 0)

        self.mode = mode
        self.handle.set_size_request(-1, self._handle_h())
        self.grip.set_visible(mode != "mini")
        self._apply_size()
        if not initial:
            w = self._dims()[0]
            self.move(x + old_w - w, y)  # sağ kenarı sabit tut
        self.webview.load_uri(self._url())
        save_mode(mode)

    def toggle_mode(self):
        if self.mode == "settings":
            self.set_mode(self.prev_mode or "full")
        else:
            self.set_mode("full" if self.mode == "mini" else "mini")

    def open_settings(self):
        if self.mode != "settings":
            self.prev_mode = self.mode
            self.set_mode("settings")

    def on_map(self, *_):
        if not self._restored:
            pos = load_pos()
            if pos and self._pos_on_screen(pos):
                self.move(pos[0], pos[1])
            else:
                display = Gdk.Display.get_default()
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                geo = monitor.get_geometry()
                w, h = self._dims()
                self.move(geo.x + geo.width - w - 30, geo.y + 40)
            self._restored = True
            GLib.idle_add(self._mark_ready)
        return False

    def _mark_ready(self):
        self._ready = True
        try:
            x, y = self.get_position()
            save_pos(x, y)
        except Exception:
            pass
        return False

    def _pos_on_screen(self, pos):
        x, y = pos
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            geo = display.get_monitor(i).get_geometry()
            if (geo.x - 40 <= x <= geo.x + geo.width - 40 and
                    geo.y - 30 <= y <= geo.y + geo.height - 30):
                return True
        return False

    def on_configure(self, widget, event):
        if not self._ready:
            return False
        if self._save_timer is None:
            self._save_timer = GLib.timeout_add(500, self._save_timer_cb)
        return False

    def _save_timer_cb(self):
        self._save_timer = None
        try:
            x, y = self.get_position()
            save_pos(x, y)
        except Exception:
            pass
        return False

    def on_destroy(self, *_):
        try:
            x, y = self.get_position()
            save_pos(x, y)
        except Exception:
            pass
        Gtk.main_quit()

    # --- sürükleme ---
    def on_press(self, widget, event):
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS and event.button == 1:
            self.toggle_mode()
            return True
        if event.button == 1:
            x, y = self.get_position()
            self._drag = (event.x_root, event.y_root, x, y)
            return True
        if event.button == 3:
            self.show_menu(event)
            return True
        return False

    def on_release(self, widget, event):
        self._drag = None
        return False

    def on_motion(self, widget, event):
        if self._drag and (event.state & Gdk.ModifierType.BUTTON1_MASK):
            x0, y0, wx, wy = self._drag
            self.move(int(wx + event.x_root - x0), int(wy + event.y_root - y0))
            return True
        return False

    def on_handle_realize(self, widget):
        win = widget.get_window()
        if win:
            win.set_cursor(Gdk.Cursor.new_from_name(widget.get_display(), "move"))

    def on_web_press(self, widget, event):
        # Web görünümünün üzerindeyken: Alt + sol tık veya orta tık ile taşı
        if event.button == 2 or (
                event.button == 1 and (event.state & Gdk.ModifierType.MOD1_MASK)):
            self.begin_move_drag(event.button, int(event.x_root),
                                 int(event.y_root), event.time)
            return True
        return False

    # --- epanel:// bağlantıları ---
    def on_decide_policy(self, view, decision, dtype):
        try:
            if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
                uri = decision.get_navigation_action().get_request().get_uri() or ""
                if uri.startswith("epanel://"):
                    cmd = uri[len("epanel://"):].strip("/")
                    dbg(f"epanel://{cmd}")
                    if cmd in ("mini", "full"):
                        self.set_mode(cmd)
                    elif cmd == "settings":
                        self.open_settings()
                    elif cmd == "widget":
                        self.set_mode(self.prev_mode or "full")
                    decision.ignore()
                    return True
        except Exception:
            pass
        return False

    # --- menü / klavye ---
    def show_menu(self, event):
        menu = Gtk.Menu()

        item = Gtk.MenuItem(label="Yenile")
        item.connect("activate", lambda *_: self.webview.reload())
        menu.append(item)

        chk = Gtk.CheckMenuItem(label="Mini mod")
        chk.set_active(self.mode == "mini")
        chk.connect("toggled", lambda w: self.set_mode("mini" if w.get_active() else "full"))
        menu.append(chk)

        item = Gtk.MenuItem(label="Ayarlar")
        item.connect("activate", lambda *_: self.open_settings())
        menu.append(item)

        above = Gtk.CheckMenuItem(label="Üstte tut")
        above.set_active(self.get_keep_above())
        above.connect("toggled", lambda w: self.set_keep_above(w.get_active()))
        menu.append(above)

        item = Gtk.MenuItem(label="Kapat")
        item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(item)

        menu.show_all()
        menu.popup_at_pointer(event)

    def on_key(self, widget, event):
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            Gtk.main_quit()
            return True
        if event.keyval == Gdk.KEY_m:
            self.toggle_mode()
            return True
        if event.keyval == Gdk.KEY_s:
            self.open_settings()
            return True
        return False


def main():
    if "--mini" in sys.argv:
        start = "mini"
    elif "--full" in sys.argv:
        start = "full"
    else:
        start = load_mode() or "full"

    win = Widget(start_mode=start)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
