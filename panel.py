#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRS-T1 e-mürekkep panosu.

Tek bir HTTP sunucusu:
  /                     -> saat + tarih + hava + sistem durumu + kontrol butonları
  /do?action=<eylem>    -> bir kontrol eylemi çalıştırır, sonra panoya döner
  /stats                -> JSON (hata ayıklama)

E-mürekkep ve eski Android 2.2 tarayıcısı için tasarlandı:
  * yalnızca basit HTML/CSS (tablo tabanlı, flexbox/grid yok)
  * yüksek kontrast, büyük yazı, 800x600 hedefi
  * HTTPS yok, düz HTTP (yerel ağ)

Harici kütüphane gerekmez (yalnızca Python standart kütüphanesi).
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
STATE_PATH = os.path.join(BASE, "state.json")

DEFAULTS = {
    "port": 8787,
    "city": "İstanbul",
    "latitude": 41.0082,
    "longitude": 28.9784,
    "timezone": "Europe/Istanbul",
    "refresh_seconds": 60,
    "rgb_on_color": "00B4FF",
    "openrgb": {"keyboard": 2, "mouse": 1},
}

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe",
           "Cuma", "Cumartesi", "Pazar"]

# WMO hava kodu -> Türkçe açıklama
WMO = {
    0: "Açık", 1: "Az bulutlu", 2: "Parçalı bulutlu", 3: "Kapalı",
    45: "Sisli", 48: "Kırağılı sis",
    51: "Hafif çisenti", 53: "Çisenti", 55: "Yoğun çisenti",
    56: "Dondurucu çisenti", 57: "Yoğun dondurucu çisenti",
    61: "Hafif yağmur", 63: "Yağmurlu", 65: "Şiddetli yağmur",
    66: "Dondurucu yağmur", 67: "Şiddetli dondurucu yağmur",
    71: "Hafif kar", 73: "Kar", 75: "Yoğun kar", 77: "Kar taneleri",
    80: "Hafif sağanak", 81: "Sağanak", 82: "Şiddetli sağanak",
    85: "Kar sağanağı", 86: "Yoğun kar sağanağı",
    95: "Gök gürültülü fırtına", 96: "Dolulu fırtına", 99: "Şiddetli dolulu fırtına",
}


# --- temalar ---
THEMES = {
    "mono": dict(
        name="Mono", bg="#ffffff", fg="#000000", muted="#666666",
        accent="#000000", accent2="#888888", border="#000000",
        btn_bg="#ffffff", btn_fg="#000000",
        btn_on_bg="#000000", btn_on_fg="#ffffff", alert="#d40000"),
    "lcars": dict(
        name="LCARS", bg="#000000", fg="#ffcc99", muted="#cc99cc",
        accent="#ff9c00", accent2="#99ccff", border="#ff9c00",
        btn_bg="#141414", btn_fg="#ffcc99",
        btn_on_bg="#ff9c00", btn_on_fg="#000000", alert="#cc4444"),
    "amber": dict(
        name="Amber", bg="#0b0b0b", fg="#ffb000", muted="#8a5a00",
        accent="#ffb000", accent2="#ff6a00", border="#ffb000",
        btn_bg="#151000", btn_fg="#ffb000",
        btn_on_bg="#ffb000", btn_on_fg="#000000", alert="#ff2a2a"),
    "matrix": dict(
        name="Matrix", bg="#000000", fg="#00ff66", muted="#008844",
        accent="#00ff66", accent2="#00aa44", border="#00ff66",
        btn_bg="#001a0a", btn_fg="#00ff66",
        btn_on_bg="#00ff66", btn_on_fg="#000000", alert="#ff2a2a"),
    "nord": dict(
        name="Nord", bg="#2e3440", fg="#eceff4", muted="#88c0d0",
        accent="#88c0d0", accent2="#b48ead", border="#4c566a",
        btn_bg="#3b4252", btn_fg="#eceff4",
        btn_on_bg="#88c0d0", btn_on_fg="#2e3440", alert="#bf616a"),
    "sunset": dict(
        name="Sunset", bg="#1a1016", fg="#ffd9c0", muted="#b06a7a",
        accent="#ff7a59", accent2="#ff4d6d", border="#ff7a59",
        btn_bg="#2a1620", btn_fg="#ffd9c0",
        btn_on_bg="#ff7a59", btn_on_fg="#000000", alert="#ff2a2a"),
}


def current_theme(name=None):
    key = (name or STATE.get("theme") or "mono")
    if key not in THEMES:
        key = "mono"
    return key, THEMES[key]


def theme_css(t):
    return (
        f":root{{--bg:{t['bg']};--fg:{t['fg']};--muted:{t['muted']};"
        f"--accent:{t['accent']};--accent2:{t['accent2']};"
        f"--border:{t['border']};--btn-bg:{t['btn_bg']};--btn-fg:{t['btn_fg']};"
        f"--btn-on-bg:{t['btn_on_bg']};--btn-on-fg:{t['btn_on_fg']};"
        "--warn:#ffb000;--crit:#ff2a2a;}}"
    )


def theme_swatches(active, back="/widget"):
    parts = []
    for key, t in THEMES.items():
        cls = "sw active" if key == active else "sw"
        parts.append(
            f'<a class="{cls}" href="/do?action=theme:{key}&amp;back={back}" '
            f'title="{esc(t["name"])}">'
            f'<i style="background:{t["accent"]}"></i>'
            f'<i style="background:{t["accent2"]}"></i></a>')
    return "".join(parts)


def alert_level(cpu):
    if cpu is None:
        return "ok"
    try:
        warn = int(STATE.get("warn_threshold", 60))
        crit = int(STATE.get("crit_threshold", 80))
    except Exception:
        warn, crit = 60, 80
    if cpu >= crit:
        return "crit"
    if cpu >= warn:
        return "warn"
    return "ok"


def temp_level(v):
    if v is None:
        return "ok"
    try:
        warn = int(STATE.get("temp_warn", 70))
        crit = int(STATE.get("temp_crit", 85))
    except Exception:
        warn, crit = 70, 85
    if v >= crit:
        return "crit"
    if v >= warn:
        return "warn"
    return "ok"


def overall_level(cpu, gpu, ram, temp=None):
    """Etkin metriklerin (CPU/GPU/RAM/Sıcaklık) en yüksek uyarı seviyesi."""
    levels = []
    if STATE.get("alert_cpu", True):
        levels.append(alert_level(cpu))
    if STATE.get("alert_gpu", True):
        levels.append(alert_level(gpu))
    if STATE.get("alert_ram", True):
        levels.append(alert_level(ram))
    if STATE.get("alert_temp", True):
        levels.append(temp_level(temp))
    if "crit" in levels:
        return "crit"
    if "warn" in levels:
        return "warn"
    return "ok"


def metric_levels(cpu, gpu, ram, vram, temp):
    return {
        "cpu": alert_level(cpu),
        "ram": alert_level(ram),
        "gpu": alert_level(gpu),
        "vram": alert_level(vram),
        "temp": temp_level(temp),
    }


def alert_classes(level):
    if level not in ("warn", "crit"):
        return ""
    cls = ["level-" + level]
    if STATE.get("alert_bg"):
        cls.append("bg")
    if STATE.get("alert_pulse") and level == "crit":
        cls.append("pulse")
    if STATE.get("alert_icons"):
        cls.append("icons")
    return " ".join(cls)


def alert_css():
    return """
 body.level-warn{--alertcolor:#ffb000;}
 body.level-crit{--alertcolor:#ff2a2a;}
 body.bg.level-warn{--bg:#ffb000;--fg:#000000;--muted:#000000;--border:#000000;
   --btn-bg:#ffb000;--btn-fg:#000000;--btn-on-bg:#000000;--btn-on-fg:#ffb000;
   background:#ffb000;color:#000000;}
 body.bg.level-crit{--bg:#ff2a2a;--fg:#ffffff;--muted:#ffffff;--border:#ffffff;
   --btn-bg:#ff2a2a;--btn-fg:#ffffff;--btn-on-bg:#ffffff;--btn-on-fg:#ff2a2a;
   background:#ff2a2a;color:#ffffff;}
 body:not(.bg) .hot-warn{color:#ffb000 !important;}
 body:not(.bg) .hot-crit{color:#ff2a2a !important;}
 body.icons.level-warn:not(.bg) a.ic,body.icons.level-warn:not(.bg) a.b{color:#ffb000;}
 body.icons.level-crit:not(.bg) a.ic,body.icons.level-crit:not(.bg) a.b{color:#ff2a2a;}
 body.pulse.level-crit{animation:eppulse 1s infinite;}
 @keyframes eppulse{0%,100%{opacity:1}50%{opacity:0.55}}
 """


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(default)


CFG = dict(DEFAULTS)
CFG.update({k: v for k, v in load_json(CONFIG_PATH, {}).items()})
STATE = {"kb": False, "mouse": False, "theme": "mono",
         "warn_threshold": 60, "crit_threshold": 80,
         "temp_warn": 70, "temp_crit": 85,
         "alert_bg": True, "alert_pulse": True, "alert_icons": False,
         "show_ram": True, "show_gpu": True, "show_vram": True,
         "alert_cpu": True, "alert_gpu": True, "alert_ram": True, "alert_temp": True,
         "mini_cpu": True, "mini_ram": True, "mini_gpu": True,
         "mini_vram": True, "mini_temp": True,
         "rgb_theme": True, "rgb_alert": True}
STATE.update(load_json(STATE_PATH, {}))

TZ = ZoneInfo(CFG["timezone"])

# --- hava durumu önbelleği ---
_weather = {"data": None, "ts": 0.0}
_weather_lock = time.time()


def save_state():
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(STATE, f)
    except Exception:
        pass


def get_weather():
    """Open-Meteo'dan hava durumu; 15 dakika önbellek."""
    now = time.time()
    if _weather["data"] and now - _weather["ts"] < 900:
        return _weather["data"]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={CFG['latitude']}&longitude={CFG['longitude']}"
        "&current=temperature_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code"
        f"&timezone={urllib.parse.quote(CFG['timezone'])}"
        "&forecast_days=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            raw = json.loads(r.read().decode("utf-8"))
        cur = raw.get("current", {})
        daily = raw.get("daily", {})
        data = {
            "temp": round(cur.get("temperature_2m")),
            "code": cur.get("weather_code"),
            "tmax": round(daily.get("temperature_2m_max", [None])[0]),
            "tmin": round(daily.get("temperature_2m_min", [None])[0]),
        }
        _weather["data"] = data
        _weather["ts"] = now
        return data
    except Exception:
        return _weather["data"]


# --- CPU kullanımı (iki örnek arası fark) ---
_cpu = {"idle": 0, "total": 0}


def _cpu_times():
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()[1:]
        vals = [int(x) for x in parts]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)
    except Exception:
        return 0, 0


def cpu_percent():
    idle, total = _cpu_times()
    di, dt = idle - _cpu["idle"], total - _cpu["total"]
    _cpu["idle"], _cpu["total"] = idle, total
    if dt <= 0:
        return None
    return round(100.0 * (dt - di) / dt)


def mem_percent():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total = info["MemTotal"]
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        return round(100.0 * (total - avail) / total)
    except Exception:
        return None


def cpu_temp():
    try:
        for h in os.listdir("/sys/class/hwmon"):
            p = f"/sys/class/hwmon/{h}"
            try:
                with open(f"{p}/name") as f:
                    name = f.read().strip()
            except Exception:
                continue
            if name in ("k10temp", "coretemp"):
                with open(f"{p}/temp1_input") as f:
                    return round(int(f.read().strip()) / 1000.0)
    except Exception:
        pass
    return None


def disk_percent():
    try:
        u = shutil.disk_usage("/")
        return round(100.0 * u.used / u.total)
    except Exception:
        return None


_gpu_cache = {"util": None, "mem": None, "ts": 0.0}


def _amd_gpu_dir():
    import glob
    for p in glob.glob("/sys/class/drm/card[0-9]*/device/gpu_busy_percent"):
        return os.path.dirname(p)
    return None


def gpu_stats():
    """(kullanım %, VRAM %) — NVIDIA (nvidia-smi) veya AMD (sysfs). 2 sn önbellek."""
    now = time.time()
    if now - _gpu_cache["ts"] < 2:
        return _gpu_cache["util"], _gpu_cache["mem"]

    util = mem = None
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        line = (out.stdout or "").strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        util = int(float(parts[0]))
        used, total = float(parts[1]), float(parts[2])
        if total > 0:
            mem = round(100.0 * used / total)
    except Exception:
        base = _amd_gpu_dir()
        if base:
            try:
                with open(os.path.join(base, "gpu_busy_percent")) as f:
                    util = int(f.read().strip())
            except Exception:
                util = None
            try:
                with open(os.path.join(base, "mem_info_vram_used")) as f:
                    used = int(f.read().strip())
                with open(os.path.join(base, "mem_info_vram_total")) as f:
                    total = int(f.read().strip())
                if total > 0:
                    mem = round(100.0 * used / total)
            except Exception:
                mem = None

    _gpu_cache.update(util=util, mem=mem, ts=now)
    return util, mem


def gpu_percent():
    return gpu_stats()[0]


def gpu_mem_percent():
    return gpu_stats()[1]


def uptime_str():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if d:
            return f"{d}g {h}s"
        if h:
            return f"{h}s {m}dk"
        return f"{m}dk"
    except Exception:
        return "?"


def run(cmd, timeout=8):
    try:
        subprocess.run(cmd, timeout=timeout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def capture(cmd, timeout=5):
    try:
        out = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        return out.stdout.strip()
    except Exception:
        return ""


def now_playing():
    status = capture(["playerctl", "status"])
    if status.lower() not in ("playing", "paused"):
        return None
    meta = capture(["playerctl", "metadata", "--format",
                    "{{artist}}|{{title}}"])
    parts = (meta or "").split("|", 1)
    artist = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else ""
    label = " – ".join(x for x in (artist, title) if x) or "Bilinmeyen parça"
    return {"status": status.lower(), "label": label}


OPENRGB = "/usr/bin/openrgb"

_rgb_last = {"color": None}


def _hexcolor(c):
    return str(c).lstrip("#").upper()


def theme_rgb_color():
    t = THEMES.get(STATE.get("theme", "mono"), THEMES["mono"])
    col = _hexcolor(t["accent"])
    if col in ("000000", "FFFFFF"):
        return _hexcolor(CFG.get("rgb_on_color", "00B4FF"))
    return col


def rgb_color_for(level=None):
    """O anki ışık rengi: uyarı varsa sarı/kırmızı, yoksa tema rengi."""
    if level is None:
        level = overall_level(cpu_percent(), gpu_stats()[0],
                              mem_percent(), cpu_temp())
    if STATE.get("rgb_alert", True):
        if level == "warn":
            return "FFB000"
        if level == "crit":
            return "FF2A2A"
    if STATE.get("rgb_theme", True):
        return theme_rgb_color()
    return _hexcolor(CFG.get("rgb_on_color", "00B4FF"))


def set_rgb_color(device_idx, color):
    return run([OPENRGB, "--device", str(device_idx), "--mode", "Direct",
                "--color", color, "--brightness", "100"], timeout=12)


def set_rgb(device_idx, on):
    if on:
        return set_rgb_color(device_idx, rgb_color_for())
    return run([OPENRGB, "--device", str(device_idx), "--mode", "Direct",
                "--color", "000000", "--brightness", "0"], timeout=12)


def apply_rgb_for_level(level):
    color = rgb_color_for(level)
    if color == _rgb_last["color"]:
        return
    _rgb_last["color"] = color
    for key, dev in (("kb", CFG["openrgb"]["keyboard"]),
                     ("mouse", CFG["openrgb"]["mouse"])):
        if STATE.get(key):
            set_rgb_color(dev, color)


def maybe_update_rgb(level):
    if not (STATE.get("rgb_theme", True) or STATE.get("rgb_alert", True)):
        return
    threading.Thread(target=apply_rgb_for_level, args=(level,),
                     daemon=True).start()


def do_action(action):
    if action == "kb_toggle":
        STATE["kb"] = not STATE["kb"]
        set_rgb(CFG["openrgb"]["keyboard"], STATE["kb"])
        save_state()
    elif action == "mouse_toggle":
        STATE["mouse"] = not STATE["mouse"]
        set_rgb(CFG["openrgb"]["mouse"], STATE["mouse"])
        save_state()
    elif action == "all_off":
        STATE["kb"] = STATE["mouse"] = False
        set_rgb(CFG["openrgb"]["keyboard"], False)
        set_rgb(CFG["openrgb"]["mouse"], False)
        save_state()
    elif action == "playpause":
        run(["playerctl", "play-pause"])
    elif action == "next":
        run(["playerctl", "next"])
    elif action == "prev":
        run(["playerctl", "previous"])
    elif action.startswith("theme:"):
        name = action.split(":", 1)[1]
        if name in THEMES:
            STATE["theme"] = name
            save_state()
            maybe_update_rgb(None)
    elif action == "weather":
        _weather["ts"] = 0  # önbelleği geçersiz kıl


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def btn(label, action, on=False):
    cls = "btn on" if on else "btn"
    return f'<a class="{cls}" href="/do?action={action}">{label}</a>'


def render():
    now = datetime.now(TZ)
    date_str = f"{now.day} {TR_MONTHS[now.month - 1]} {now.year}, {TR_DAYS[now.weekday()]}"
    time_str = now.strftime("%H:%M")

    w = get_weather()
    if w and w.get("temp") is not None:
        wdesc = WMO.get(w.get("code"), "Bilinmiyor")
        weather_html = f"""
          <div class="wtemps">{w['temp']}&deg;</div>
          <div class="wdesc">{esc(wdesc)}</div>
          <div class="wminmax">En y&uuml;ksek {w['tmax']}&deg; / En d&uuml;&#351;&uuml;k {w['tmin']}&deg;</div>
          <div class="wcity">{esc(CFG['city'])}</div>"""
    else:
        weather_html = '<div class="wdesc">Hava durumu al&#305;namad&#305;</div>'

    stats = [("CPU", cpu_percent(), "%"), ("RAM", mem_percent(), "%"),
             ("Disk", disk_percent(), "%"), ("S&#305;cakl&#305;k", cpu_temp(), "&deg;C"),
             ("&Ccedil;al&#305;&#351;ma", uptime_str(), "")]
    stats_html = ""
    for label, val, unit in stats:
        v = "?" if val is None else f"{val}{unit}"
        stats_html += f'<td><div class="statlabel">{label}</div><div class="statval">{v}</div></td>'

    np = now_playing()
    if np:
        icon = "&#9654;" if np["status"] == "playing" else "&#10074;&#10074;"
        np_html = f'{icon}&nbsp; {esc(np["label"])}'
    else:
        np_html = "&mdash;"

    port = CFG["port"]
    return f"""<!DOCTYPE html>
<html lang="tr"><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>e-Panel</title>
<style type="text/css">
 html,body{{margin:0;padding:0;background:#fff;color:#000;font-family:Arial,Helvetica,sans-serif;}}
 body{{width:800px;}}
 table{{border-collapse:collapse;width:100%;}}
 td{{vertical-align:top;}}
 .hdr{{border-bottom:3px solid #000;}}
 .hdr td{{padding:14px 20px;}}
 .time{{font-size:76px;font-weight:bold;line-height:1;}}
 .date{{font-size:21px;margin-top:6px;}}
 .weather{{text-align:right;}}
 .wtemps{{font-size:52px;font-weight:bold;line-height:1;}}
 .wdesc{{font-size:20px;margin-top:4px;}}
 .wminmax{{font-size:16px;margin-top:4px;}}
 .wcity{{font-size:16px;margin-top:2px;}}
 .stats td{{padding:12px 20px;border-bottom:1px solid #000;text-align:center;}}
 .statlabel{{font-size:13px;}}
 .statval{{font-size:28px;font-weight:bold;}}
 .np{{font-size:21px;padding:12px 20px;border-bottom:3px solid #000;}}
 .controls td{{padding:8px;}}
 a.btn{{display:block;border:3px solid #000;color:#000;text-decoration:none;
        text-align:center;font-size:21px;font-weight:bold;padding:22px 6px;}}
 a.on{{background:#000;color:#fff;}}
 .footer{{font-size:12px;padding:6px 20px;text-align:right;}}
</style>
</head><body>

<table class="hdr"><tr>
 <td width="55%">
   <div class="time">{time_str}</div>
   <div class="date">{esc(date_str)}</div>
 </td>
 <td class="weather" width="45%">{weather_html}</td>
</tr></table>

<table class="stats"><tr>{stats_html}</tr></table>

<div class="np">{np_html}</div>

<table class="controls"><tr>
 <td width="50%">{btn("Klavye I&#351;&#305;&#287;&#305;", "kb_toggle", STATE.get("kb"))}</td>
 <td width="50%">{btn("Fare I&#351;&#305;&#287;&#305;", "mouse_toggle", STATE.get("mouse"))}</td>
</tr><tr>
 <td>{btn("&#9668;&#9668; &Ouml;nceki", "prev")}</td>
 <td>{btn("&#9654; Oynat / Duraklat", "playpause")}</td>
</tr><tr>
 <td>{btn("Sonraki &#9658;&#9658;", "next")}</td>
 <td>{btn("T&uuml;m &#305;&#351;&#305;klar kapal&#305;", "all_off")}</td>
</tr></table>

<div class="footer">e-Panel &middot; :{port} &middot; {now.strftime('%H:%M:%S')}</div>

<script type="text/javascript">
setTimeout(function(){{location.reload();}}, {int(CFG['refresh_seconds']) * 1000});
</script>
</body></html>"""


def render_mini():
    """Mini şerit: 40px yükseklik; üstte etiket, altta hizalı değer."""
    theme_key, t = current_theme()
    now = datetime.now(TZ)
    time_str = now.strftime("%H:%M")

    w = get_weather()
    weather = f'{w["temp"]}&deg;' if (w and w.get("temp") is not None) else "&ndash;"

    cpu = cpu_percent()
    ram = mem_percent()
    gpu, vram = gpu_stats()
    temp = cpu_temp()
    level = overall_level(cpu, gpu, ram, temp)
    levels = metric_levels(cpu, gpu, ram, vram, temp)
    body_cls = alert_classes(level)

    def block(label, key, value, unit="%"):
        v = "?" if value is None else f"{value}{unit}"
        lvl = levels.get(key, "ok")
        hot = f" hot-{lvl}" if lvl in ("warn", "crit") else ""
        return (f'<div class="m"><div class="ml">{label}</div>'
                f'<div class="mv metric{hot}" id="{key}val">{v}</div></div>')

    metrics = ""
    if STATE.get("mini_cpu", True):
        metrics += block("CPU", "cpu", cpu)
    if STATE.get("mini_ram", True):
        metrics += block("RAM", "ram", ram)
    if STATE.get("mini_gpu", True):
        metrics += block("GPU", "gpu", gpu)
    if STATE.get("mini_vram", True):
        metrics += block("VRAM", "vram", vram)
    if STATE.get("mini_temp", True):
        metrics += block("SIC", "temp", temp, "&deg;")

    return f"""<!DOCTYPE html>
<html lang="tr"><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>e-Panel mini</title>
<style type="text/css">
 {theme_css(t)}
 {alert_css()}
 html,body{{margin:0;padding:0;background:var(--bg);color:var(--fg);font-family:Arial,Helvetica,sans-serif;width:430px;overflow:hidden;}}
 .bar{{display:flex;align-items:center;height:40px;padding:0 6px;white-space:nowrap;}}
 .clock{{font-weight:bold;font-size:15px;padding-right:6px;}}
 .weather{{font-size:15px;font-weight:bold;color:var(--accent2);padding-right:8px;border-right:1px solid var(--border);margin-right:8px;}}
 .metrics{{display:flex;}}
 .m{{width:46px;text-align:center;}}
 .ml{{font-size:8px;color:var(--muted);line-height:10px;letter-spacing:0.5px;}}
 .mv{{font-size:13px;font-weight:bold;line-height:15px;}}
 .spacer{{flex:1;}}
 a.ic{{display:inline-block;text-decoration:none;color:var(--fg);padding:0 4px;font-size:13px;line-height:40px;}}
 a.on{{background:var(--btn-on-bg);color:var(--btn-on-fg);}}
 a.exp{{border-left:1px solid var(--border);}}
</style>
</head><body class="{body_cls}"><div class="bar">
 <span class="clock" id="clock">{time_str}</span>
 <span class="weather">{weather}</span>
 <span class="metrics">{metrics}</span>
 <span class="spacer"></span>
 <a class="ic{' on' if STATE.get('kb') else ''}" href="/do?action=kb_toggle&amp;back=/mini" title="Klavye">&#9000;</a>
 <a class="ic{' on' if STATE.get('mouse') else ''}" href="/do?action=mouse_toggle&amp;back=/mini" title="Fare">&#128433;</a>
 <a class="ic" href="/do?action=playpause&amp;back=/mini" title="Oynat/Duraklat">&#9654;</a>
 <a class="ic" href="epanel://settings" title="Ayarlar">&#9881;</a>
 <a class="ic exp" href="epanel://full" title="Geni&#351;let">&#9635;</a>
</div>
<script type="text/javascript">
function pad(n){{return (n<10?'0':'')+n;}}
function tick(){{var d=new Date();var e=document.getElementById('clock');if(e)e.textContent=pad(d.getHours())+':'+pad(d.getMinutes());}}
setInterval(tick,10000);
function sv(i,v,u){{var e=document.getElementById(i);if(e&&v!=null)e.textContent=v+(u||'%');}}
function hot(i,l){{var e=document.getElementById(i);if(!e)return;var c=e.className.replace(/[ ]*hot-(warn|crit)/g,'');if(l&&l!=='ok')c+=' hot-'+l;e.className=c;}}
function applyState(d){{var cls=[];if(d.level&&d.level!=='ok'){{cls.push('level-'+d.level);if(d.settings.alert_bg)cls.push('bg');if(d.settings.alert_pulse&&d.level==='crit')cls.push('pulse');if(d.settings.alert_icons)cls.push('icons');}}document.body.className=cls.join(' ');sv('cpuval',d.cpu);sv('ramval',d.ram);sv('gpuval',d.gpu);sv('vramval',d.vram);sv('tempval',d.temp,'\u00b0');if(d.levels){{hot('cpuval',d.levels.cpu);hot('ramval',d.levels.ram);hot('gpuval',d.levels.gpu);hot('vramval',d.levels.vram);hot('tempval',d.levels.temp);}}}}
function poll(){{var x=new XMLHttpRequest();x.open('GET','/api/state',true);x.onreadystatechange=function(){{if(x.readyState==4&&x.status==200){{try{{applyState(JSON.parse(x.responseText));}}catch(e){{}}}}}};x.send();}}
setInterval(poll,5000);
setTimeout(function(){{location.reload();}}, 30000);
</script>
</body></html>"""


def render_widget():
    """Küçük masaüstü widget'ı (340px), temalı ve canlı CPU uyarılı."""
    theme_key, t = current_theme()
    now = datetime.now(TZ)
    date_str = f"{now.day} {TR_MONTHS[now.month - 1]} {TR_DAYS[now.weekday()]}"
    time_str = now.strftime("%H:%M")

    w = get_weather()
    if w and w.get("temp") is not None:
        wdesc = WMO.get(w.get("code"), "?")
        weather_html = (f'<div class="temp">{w["temp"]}&deg;</div>'
                        f'<div class="desc">{esc(wdesc)}</div>'
                        f'<div class="minmax">&uarr;{w["tmax"]}&deg; &darr;{w["tmin"]}&deg;</div>')
    else:
        weather_html = '<div class="desc">hava yok</div>'

    cpu = cpu_percent()
    ram = mem_percent()
    gpu, vram = gpu_stats()
    temp = cpu_temp()
    level = overall_level(cpu, gpu, ram, temp)
    levels = metric_levels(cpu, gpu, ram, vram, temp)
    body_cls = alert_classes(level)

    stats = [("CPU", "cpu", cpu, "%")]
    if STATE.get("show_ram", True):
        stats.append(("RAM", "ram", ram, "%"))
    if STATE.get("show_gpu", True):
        stats.append(("GPU", "gpu", gpu, "%"))
    if STATE.get("show_vram", True):
        stats.append(("VRAM", "vram", vram, "%"))
    stats.append(("S&#305;c.", "temp", temp, "&deg;"))
    stats.append(("Disk", None, disk_percent(), "%"))

    stats_html = ""
    for label, key, val, unit in stats:
        v = "?" if val is None else f"{val}{unit}"
        if key:
            lvl = levels.get(key, "ok")
            hot = f" hot-{lvl}" if lvl in ("warn", "crit") else ""
            stats_html += (f'<td><div class="sl">{label}</div>'
                           f'<div class="sv metric{hot}" id="{key}val">{v}</div></td>')
        else:
            stats_html += (f'<td><div class="sl">{label}</div>'
                           f'<div class="sv">{v}</div></td>')

    np = now_playing()
    np_html = ""
    if np:
        np_html = f'<div class="np">&#9835; {esc(np["label"])}</div>'

    return f"""<!DOCTYPE html>
<html lang="tr"><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>e-Panel</title>
<style type="text/css">
 {theme_css(t)}
 {alert_css()}
 html,body{{margin:0;padding:0;background:var(--bg);color:var(--fg);font-family:Arial,Helvetica,sans-serif;width:340px;overflow:hidden;}}
 .wrap{{padding:9px 12px;}}
 table{{border-collapse:collapse;width:100%;}}
 td{{vertical-align:top;}}
 .clock{{font-size:43px;font-weight:bold;line-height:1;letter-spacing:1px;}}
 .date{{font-size:11px;margin-top:3px;color:var(--muted);}}
 .right{{text-align:right;}}
 .temp{{font-size:33px;font-weight:bold;line-height:1;}}
 .desc{{font-size:12px;margin-top:2px;}}
 .minmax{{font-size:10px;margin-top:1px;color:var(--muted);}}
 .stats{{border-top:2px solid var(--border);border-bottom:1px solid var(--border);margin:7px 0;}}
 .stats td{{text-align:center;padding:4px 1px;}}
 .sl{{font-size:8px;color:var(--muted);}}
 .sv{{font-size:14px;font-weight:bold;}}
 .np{{font-size:11px;border-bottom:1px solid var(--border);padding:4px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--accent2);}}
 .controls td{{padding:3px 2px;}}
 a.b{{display:block;border:2px solid var(--border);color:var(--btn-fg);background:var(--btn-bg);text-decoration:none;text-align:center;font-size:10px;font-weight:bold;padding:6px 1px;}}
 a.on{{background:var(--btn-on-bg);color:var(--btn-on-fg);border-color:var(--btn-on-bg);}}
 .foot{{display:flex;justify-content:space-between;align-items:center;font-size:9px;margin-top:4px;color:var(--muted);}}
 .foot a{{color:var(--muted);text-decoration:none;}}
 .footlinks a{{margin-left:7px;}}
 .sw{{display:inline-block;width:22px;height:11px;border:1px solid var(--muted);margin-right:4px;text-decoration:none;overflow:hidden;vertical-align:middle;}}
 .sw i{{display:block;float:left;width:50%;height:100%;}}
 .sw.active{{outline:2px solid var(--accent);outline-offset:1px;}}
 body.alert{{--accent:var(--alert);--accent2:var(--alert);--border:var(--alert);}}
 body.alert .clock, body.alert .temp{{color:var(--alert);}}
 body.alert #cpuval{{color:var(--alert);}}
</style>
</head><body class="{body_cls}"><div class="wrap">

<table><tr>
 <td width="58%"><div class="clock" id="clock">{time_str}</div><div class="date">{esc(date_str)}</div></td>
 <td class="right" width="42%">{weather_html}</td>
</tr></table>

<table class="stats"><tr>{stats_html}</tr></table>
{np_html}
<table class="controls">
<tr>
 <td width="33%"><a class="b{' on' if STATE.get('kb') else ''}" href="/do?action=kb_toggle&amp;back=/widget">Klavye</a></td>
 <td width="34%"><a class="b{' on' if STATE.get('mouse') else ''}" href="/do?action=mouse_toggle&amp;back=/widget">Fare</a></td>
 <td width="33%"><a class="b" href="/do?action=all_off&amp;back=/widget">Kapat</a></td>
</tr>
<tr>
 <td><a class="b" href="/do?action=prev&amp;back=/widget">&#9668;</a></td>
 <td><a class="b" href="/do?action=playpause&amp;back=/widget">Oynat</a></td>
 <td><a class="b" href="/do?action=next&amp;back=/widget">&#9658;</a></td>
</tr>
</table>
<div class="foot">
 <span class="swatches">{theme_swatches(theme_key)}</span>
 <span class="footlinks"><a href="epanel://settings" title="Ayarlar">&#9881;</a><a href="epanel://mini">k&#252;&#231;&#252;lt &#8211;</a></span>
</div>

</div>
<script type="text/javascript">
function pad(n){{return (n<10?'0':'')+n;}}
function tick(){{var d=new Date();var e=document.getElementById('clock');if(e)e.textContent=pad(d.getHours())+':'+pad(d.getMinutes());}}
setInterval(tick,10000);
function applyState(d){{var cls=[];if(d.level&&d.level!=='ok'){{cls.push('level-'+d.level);if(d.settings.alert_bg)cls.push('bg');if(d.settings.alert_pulse&&d.level==='crit')cls.push('pulse');if(d.settings.alert_icons)cls.push('icons');}}document.body.className=cls.join(' ');function sv(i,v,u){{var e=document.getElementById(i);if(e&&v!=null)e.textContent=v+(u||'%');}}sv('cpuval',d.cpu);sv('ramval',d.ram);sv('gpuval',d.gpu);sv('vramval',d.vram);sv('tempval',d.temp,'\u00b0');function hot(i,l){{var e=document.getElementById(i);if(!e)return;var c=e.className.replace(/[ ]*hot-(warn|crit)/g,'');if(l&&l!=='ok')c+=' hot-'+l;e.className=c;}}if(d.levels){{hot('cpuval',d.levels.cpu);hot('ramval',d.levels.ram);hot('gpuval',d.levels.gpu);hot('vramval',d.levels.vram);hot('tempval',d.levels.temp);}}}}
function poll(){{var x=new XMLHttpRequest();x.open('GET','/api/state',true);x.onreadystatechange=function(){{if(x.readyState==4&&x.status==200){{try{{applyState(JSON.parse(x.responseText));}}catch(e){{}}}}}};x.send();}}
setInterval(poll,5000);
setTimeout(function(){{location.reload();}}, {int(CFG['refresh_seconds']) * 1000});
</script>
</body></html>"""


def render_settings(saved=False):
    """Küçük ayar sayfası (widget içinde açılır)."""
    theme_key, t = current_theme()

    def checked(key):
        return " checked" if STATE.get(key) else ""

    try:
        warn_v = int(STATE.get("warn_threshold", 60))
        crit_v = int(STATE.get("crit_threshold", 80))
        temp_warn_v = int(STATE.get("temp_warn", 70))
        temp_crit_v = int(STATE.get("temp_crit", 85))
    except Exception:
        warn_v, crit_v, temp_warn_v, temp_crit_v = 60, 80, 70, 85

    return f"""<!DOCTYPE html>
<html lang="tr"><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>Ayarlar</title>
<style type="text/css">
 {theme_css(t)}
 html,body{{margin:0;padding:0;background:var(--bg);color:var(--fg);font-family:Arial,Helvetica,sans-serif;width:360px;}}
 .wrap{{padding:12px 14px;}}
 .row{{display:flex;justify-content:space-between;align-items:baseline;}}
 h1{{font-size:16px;margin:0 0 4px 0;color:var(--accent);}}
 .sec{{font-size:10px;color:var(--muted);margin:12px 0 4px;border-bottom:1px solid var(--border);padding-bottom:2px;}}
 label{{display:block;font-size:12px;margin:7px 0;}}
 input[type=number]{{width:70px;padding:3px;font-size:13px;background:var(--btn-bg);color:var(--fg);border:1px solid var(--border);}}
 input[type=checkbox]{{vertical-align:middle;margin-right:3px;}}
 button{{margin-top:12px;padding:8px 18px;font-size:13px;font-weight:bold;background:var(--btn-on-bg);color:var(--btn-on-fg);border:2px solid var(--border);cursor:pointer;}}
 a{{color:var(--accent);text-decoration:none;font-size:11px;}}
 .ok{{font-size:11px;color:var(--accent);margin:4px 0;}}
 .sw{{display:inline-block;width:22px;height:11px;border:1px solid var(--muted);margin-right:4px;text-decoration:none;overflow:hidden;vertical-align:middle;}}
 .sw i{{display:block;float:left;width:50%;height:100%;}}
 .sw.active{{outline:2px solid var(--accent);outline-offset:1px;}}
</style>
</head><body><div class="wrap">
<div class="row"><h1>Ayarlar</h1><a href="epanel://widget">Panele d&ouml;n &#8594;</a></div>
{'<div class="ok">Kaydedildi.</div>' if saved else ''}

<div class="sec">TEMA</div>
{theme_swatches(theme_key, back="/settings")}

<form method="get" action="/save-settings">
<div class="sec">METR&#304;KLER (TAM W&#304;DGET)</div>
<label><input type="checkbox" name="show_ram" value="1"{checked('show_ram')}> RAM g&ouml;ster</label>
<label><input type="checkbox" name="show_gpu" value="1"{checked('show_gpu')}> GPU g&ouml;ster</label>
<label><input type="checkbox" name="show_vram" value="1"{checked('show_vram')}> VRAM g&ouml;ster</label>

<div class="sec">M&#304;N&#304; &#350;ER&#304;T</div>
<label><input type="checkbox" name="mini_cpu" value="1"{checked('mini_cpu')}> CPU</label>
<label><input type="checkbox" name="mini_ram" value="1"{checked('mini_ram')}> RAM</label>
<label><input type="checkbox" name="mini_gpu" value="1"{checked('mini_gpu')}> GPU</label>
<label><input type="checkbox" name="mini_vram" value="1"{checked('mini_vram')}> VRAM</label>
<label><input type="checkbox" name="mini_temp" value="1"{checked('mini_temp')}> S&#305;cakl&#305;k</label>

<div class="sec">UYARI E&#350;&#304;KLER&#304;</div>
<label>Y&uuml;k uyar&#305; (%): <input type="number" name="warn" min="0" max="100" value="{warn_v}"></label>
<label>Y&uuml;k kritik (%): <input type="number" name="crit" min="0" max="100" value="{crit_v}"></label>
<label>S&#305;cakl&#305;k uyar&#305; (&deg;C): <input type="number" name="temp_warn" min="0" max="150" value="{temp_warn_v}"></label>
<label>S&#305;cakl&#305;k kritik (&deg;C): <input type="number" name="temp_crit" min="0" max="150" value="{temp_crit_v}"></label>

<div class="sec">G&Ouml;R&Uuml;N&Uuml;M</div>
<label><input type="checkbox" name="alert_bg" value="1"{checked('alert_bg')}> T&uuml;m zemin renklensin</label>
<label><input type="checkbox" name="alert_pulse" value="1"{checked('alert_pulse')}> Kritikte yan&#305;p s&ouml;ns&uuml;n</label>
<label><input type="checkbox" name="alert_icons" value="1"{checked('alert_icons')}> &#304;konlar da renklensin</label>

<div class="sec">KLAVYE / FARE I&#350;I&#286;I</div>
<label><input type="checkbox" name="rgb_theme" value="1"{checked('rgb_theme')}> Tema rengini kullan</label>
<label><input type="checkbox" name="rgb_alert" value="1"{checked('rgb_alert')}> Uyar&#305; rengine ge&ccedil;</label>

<div class="sec">UYARI KAYNAKLARI</div>
<label><input type="checkbox" name="alert_cpu" value="1"{checked('alert_cpu')}> CPU</label>
<label><input type="checkbox" name="alert_gpu" value="1"{checked('alert_gpu')}> GPU</label>
<label><input type="checkbox" name="alert_ram" value="1"{checked('alert_ram')}> RAM</label>
<label><input type="checkbox" name="alert_temp" value="1"{checked('alert_temp')}> S&#305;cakl&#305;k</label>
<button type="submit">Kaydet</button>
</form>
</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            path = os.path.join(BASE, "access.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(TZ).strftime('%H:%M:%S')} "
                        f"{self.client_address[0]} {fmt % args}\n")
        except Exception:
            pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send(200, render())
        elif path == "/widget":
            self._send(200, render_widget())
        elif path == "/mini":
            self._send(200, render_mini())
        elif path == "/settings":
            qs = urllib.parse.parse_qs(parsed.query)
            self._send(200, render_settings(saved=("saved" in qs)))
        elif path == "/save-settings":
            qs = urllib.parse.parse_qs(parsed.query)

            def _int(name, default):
                try:
                    return int(qs.get(name, [default])[0])
                except Exception:
                    return default

            STATE["warn_threshold"] = max(0, min(100, _int("warn", 60)))
            STATE["crit_threshold"] = max(0, min(100, _int("crit", 80)))
            STATE["alert_bg"] = "alert_bg" in qs
            STATE["alert_pulse"] = "alert_pulse" in qs
            STATE["alert_icons"] = "alert_icons" in qs
            STATE["show_ram"] = "show_ram" in qs
            STATE["show_gpu"] = "show_gpu" in qs
            STATE["show_vram"] = "show_vram" in qs
            STATE["alert_cpu"] = "alert_cpu" in qs
            STATE["alert_gpu"] = "alert_gpu" in qs
            STATE["alert_ram"] = "alert_ram" in qs
            STATE["alert_temp"] = "alert_temp" in qs
            STATE["temp_warn"] = max(0, min(150, _int("temp_warn", 70)))
            STATE["temp_crit"] = max(0, min(150, _int("temp_crit", 85)))
            STATE["mini_cpu"] = "mini_cpu" in qs
            STATE["mini_ram"] = "mini_ram" in qs
            STATE["mini_gpu"] = "mini_gpu" in qs
            STATE["mini_vram"] = "mini_vram" in qs
            STATE["mini_temp"] = "mini_temp" in qs
            STATE["rgb_theme"] = "rgb_theme" in qs
            STATE["rgb_alert"] = "rgb_alert" in qs
            save_state()
            maybe_update_rgb(None)
            self.send_response(303)
            self.send_header("Location", "/settings?saved=1")
            self.end_headers()
        elif path == "/do":
            qs = urllib.parse.parse_qs(parsed.query)
            action = (qs.get("action", [""])[0])
            back = (qs.get("back", ["/"])[0]) or "/"
            if not back.startswith("/"):
                back = "/"
            try:
                do_action(action)
            except Exception:
                pass
            self.send_response(303)
            self.send_header("Location", back)
            self.end_headers()
        elif path == "/api/state":
            c = cpu_percent()
            r = mem_percent()
            g, v = gpu_stats()
            t = cpu_temp()
            lvl = overall_level(c, g, r, t)
            maybe_update_rgb(lvl)
            self._send(200, json.dumps({
                "cpu": c, "ram": r, "gpu": g, "vram": v, "mem": r, "temp": t,
                "disk": disk_percent(),
                "level": lvl,
                "levels": metric_levels(c, g, r, v, t),
                "alert": lvl != "ok",
                "theme": STATE.get("theme", "mono"),
                "settings": {
                    "alert_bg": bool(STATE.get("alert_bg")),
                    "alert_pulse": bool(STATE.get("alert_pulse")),
                    "alert_icons": bool(STATE.get("alert_icons")),
                    "show_ram": bool(STATE.get("show_ram", True)),
                    "show_gpu": bool(STATE.get("show_gpu", True)),
                    "show_vram": bool(STATE.get("show_vram", True)),
                    "alert_cpu": bool(STATE.get("alert_cpu", True)),
                    "alert_gpu": bool(STATE.get("alert_gpu", True)),
                    "alert_ram": bool(STATE.get("alert_ram", True)),
                    "alert_temp": bool(STATE.get("alert_temp", True)),
                    "temp_warn": int(STATE.get("temp_warn", 70)),
                    "temp_crit": int(STATE.get("temp_crit", 85)),
                    "mini_cpu": bool(STATE.get("mini_cpu", True)),
                    "mini_ram": bool(STATE.get("mini_ram", True)),
                    "mini_gpu": bool(STATE.get("mini_gpu", True)),
                    "mini_vram": bool(STATE.get("mini_vram", True)),
                    "mini_temp": bool(STATE.get("mini_temp", True)),
                    "rgb_theme": bool(STATE.get("rgb_theme", True)),
                    "rgb_alert": bool(STATE.get("rgb_alert", True)),
                    "warn_threshold": int(STATE.get("warn_threshold", 60)),
                    "crit_threshold": int(STATE.get("crit_threshold", 80)),
                },
            }, ensure_ascii=False), "application/json; charset=utf-8")
        elif path == "/stats":
            self._send(200, json.dumps({
                "cpu": cpu_percent(), "mem": mem_percent(), "disk": disk_percent(),
                "temp": cpu_temp(), "uptime": uptime_str(),
                "weather": get_weather(), "state": STATE,
            }, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "Bulunamadı")


def main():
    # CPU ölçümü için ilk örneği al
    cpu_percent()
    httpd = ThreadingHTTPServer(("0.0.0.0", CFG["port"]), Handler)
    print(f"e-Panel çalışıyor: http://0.0.0.0:{CFG['port']}/  (şehir: {CFG['city']})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
