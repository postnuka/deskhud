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

# systemd --user servisi
mkdir -p "$HOME/.config/systemd/user"
sed "s|__PROJECT_DIR__|$DIR|g" prs-panel.service \
  > "$HOME/.config/systemd/user/prs-panel.service"
systemctl --user daemon-reload
systemctl --user enable --now prs-panel

# Widget otomatik başlatma (GNOME)
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/prs-widget.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DeskHUD Widget
Comment=DeskHUD e-ink panel desktop widget
Exec=/usr/bin/python3 "$DIR/widget.py"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

# Oturum kapalıyken de çalışsın (opsiyonel)
loginctl enable-linger "$USER" 2>/dev/null || true

PORT=$(python3 -c "import json;print(json.load(open('config.json')).get('port',8787))" 2>/dev/null || echo 8787)

echo
echo "Tamam! Pano: http://127.0.0.1:${PORT}/"
echo "Widget: python3 \"$DIR/widget.py\""
