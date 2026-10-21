#!/usr/bin/env bash
# DeskHUD kurulum betiği
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "DeskHUD kuruluyor: $DIR"

command -v python3 >/dev/null || { echo "HATA: python3 bulunamadı"; exit 1; }
for c in openrgb playerctl; do
  command -v "$c" >/dev/null || echo "UYARI: $c yok (ilgili özellikler çalışmaz)"
done

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "config.json oluşturuldu (şehir/koordinatları düzenleyin)."
fi

# systemd --user servisleri
mkdir -p "$HOME/.config/systemd/user"
sed "s|__PROJECT_DIR__|$DIR|g" prs-panel.service \
  > "$HOME/.config/systemd/user/prs-panel.service"
sed "s|__PROJECT_DIR__|$DIR|g" deskhud-widget.service \
  > "$HOME/.config/systemd/user/deskhud-widget.service"
systemctl --user daemon-reload
systemctl --user enable --now prs-panel
systemctl --user enable --now deskhud-widget

# Eski autostart kaydını kaldır (çift başlatmayı önle)
rm -f "$HOME/.config/autostart/prs-widget.desktop"

# Oturum kapalıyken de çalışsın (opsiyonel)
loginctl enable-linger "$USER" 2>/dev/null || true

PORT=$(python3 -c "import json;print(json.load(open('config.json')).get('port',8787))" 2>/dev/null || echo 8787)

echo
echo "Tamam! Pano: http://127.0.0.1:${PORT}/"
echo "Widget: python3 \"$DIR/widget.py\""
