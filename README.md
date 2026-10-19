# DeskHUD

**Ubuntu (GNOME) masaüstü için küçük, her zaman üstte duran bir HUD widget'ı.**
Saat, hava durumu, CPU/RAM/GPU/VRAM/sıcaklık gösterir; klavye ve fare RGB'sini,
medyayı ve ışıkları kontrol eder. Temalar (LCARS dahil) ve yük altında renk
değiştiren arayüz destekler.

Aynı panoyu eski bir **Sony PRS-T1** üzerinde **e-mürekkep ekran** olarak da
açabilirsiniz — ama projenin ana odağı masaüstü widget'ı.

## Özellikler

- **Masaüstü HUD widget'ı** — çerçevesiz, üstte duran, sürüklenebilir
- **3 mod** — tam (340×264), mini (430×44), ayarlar (360×640)
- **6 tema** — Mono, LCARS, Amber, Matrix, Nord, Sunset
- **Metrikler** — CPU, RAM, GPU, VRAM, sıcaklık, disk
- **NVIDIA / AMD** GPU desteği (`nvidia-smi` / sysfs)
- **Kademeli uyarı** — %60 sarı, %80 kırmızı; sıcaklık için ayrı eşikler
- **Tüm zemin / pulse / ikon renklendirme**
- **RGB senkronu** — klavye/fare rengi temaya ve uyarıya uyar (OpenRGB)
- **Medya kontrolü** (playerctl), ışık aç/kapat
- **Ayar sayfası** — tüm seçimler kalıcı (`state.json`)
- **Opsiyonel e-mürekkep pano** — PRS-T1'in eski tarayıcısına uygun sade HTML

## Gereksinimler

- Python 3.11+
- `openrgb` (RGB) ve `playerctl` (medya) — opsiyonel
- Ubuntu/GNOME + GTK3/WebKit2 (widget için)
- Sony PRS-T1 (opsiyonel; pano herhangi bir tarayıcıda çalışır)

## Hızlı başlangıç

```bash
git clone https://github.com/postnuka/deskhud.git
cd deskhud
cp config.example.json config.json   # şehir/koordinatları düzenleyin
./install.sh
```

- Pano: <http://127.0.0.1:8787/>
- Widget: oturum açılışında otomatik; elle `python3 widget.py`
- Ayarlar: <http://127.0.0.1:8787/settings>

## Çalıştırma

```bash
python3 panel.py          # sunucu
python3 widget.py         # masaüstü widget'ı
python3 widget.py --mini  # mini şerit
python3 widget.py --full  # tam mod
```

Sunucu `0.0.0.0:8787` üzerinde dinler.

## Yapılandırma

`config.json` (örnek: `config.example.json`):

| Alan | Açıklama |
|---|---|
| `port` | Sunucu portu |
| `city`, `latitude`, `longitude` | Hava durumu konumu |
| `timezone` | Saat dilimi |
| `refresh_seconds` | Sayfa yenileme |
| `rgb_on_color` | Mono temada varsayılan RGB |
| `openrgb.keyboard` / `.mouse` | OpenRGB cihaz indeksleri |

OpenRGB indeksleri: `openrgb --list-devices`

## systemd (otomatik başlatma)

`install.sh` şunları yapar:

- `prs-panel.service` dosyasını `~/.config/systemd/user/` altına kurar,
- `~/.config/autostart/prs-widget.desktop` oluşturur.

Elle:

```bash
systemctl --user status prs-panel
journalctl --user -u prs-panel -f
```

## PRS-T1 tarafı

1. Ayarlar → Wi-Fi: bilgisayarla aynı ağa bağlan.
2. Tarayıcı → `http://<PC-LAN-IP>:8787/`

> PRS-T1 tarayıcısı Android 2.2 tabanlıdır; pano bilinçli olarak basit
> HTML/CSS ile yazıldı. HTTPS yok, düz HTTP (yerel ağ).

## Masaüstü widget'ı

- **Mod geçişi:** tutamağa çift tık, sağ tık → Mini mod, `m` tuşu;
  mini şeritte ▣ / tam modda "küçült –".
- **Taşıma:** üstteki tutamak, **Alt + sol tık + sürükle** veya
  **orta tuşla sürükle**.
- **Konum:** widget son konumunu hatırlar (`widget-pos.txt`); kapanıp
  açılınca aynı yerde açılır.
- **Ayarlar:** ⚙ ikonu veya `s` tuşu.
- **Kapat:** sağ tık → Kapat, `Esc` / `q`.

## Temalar, uyarılar ve RGB

- Temalar: `mono`, `lcars`, `amber`, `matrix`, `nord`, `sunset`.
  Renk ikonlarından veya ayarlardan seçilir.
- Kademeli uyarı: yük eşiği (varsayılan %60 sarı, %80 kırmızı);
  sıcaklık için ayrı eşikler (70 °C / 85 °C).
- Uyarı kaynakları ayarlardan seçilir: **CPU, GPU, RAM, sıcaklık**.
- **RGB senkronu:** klavye/fare açıkken renk tema rengine, uyarıda sarı/kırmızıya
  döner; ayarlardan kapatılabilir.
- Widget `/api/state` adresini **5 saniyede bir** yoklar; değişim sayfa
  yenilenmeden gerçekleşir.

## API

| Yol | Açıklama |
|---|---|
| `/` | E-mürekkep tam sayfa (mono) |
| `/widget` | Masaüstü widget (temalı) |
| `/mini` | Mini şerit (temalı) |
| `/settings` | Ayar sayfası |
| `/api/state` | JSON: cpu, ram, gpu, vram, temp, level, settings |
| `/do?action=...&back=...` | Kontrol eylemleri |

## Dosyalar

- `panel.py` — HTTP sunucusu ve sayfalar
- `widget.py` — GTK3 + WebKit2 masaüstü widget'ı
- `config.example.json` — örnek ayarlar
- `prs-panel.service` — systemd birim şablonu
- `install.sh` — kurulum betiği
- `README.md`, `LICENSE`

## Lisans

MIT — © 2026 Emin Bakan (postnuka)
