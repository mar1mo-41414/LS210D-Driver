#!/bin/sh
# LS210D-Driver インストールスクリプト (LS210D 本体上で root 実行する)
#   sudo ./install.sh          … デーモンと SPI 設定を導入する
#   sudo ./install.sh --dry-run-daemon
#                              … デーモンだけ dry_run=1 で導入する (poweroff しない確認用)
set -eu
cd "$(dirname "$0")"

DRY=0
[ "${1:-}" = "--dry-run-daemon" ] && DRY=1

# --- デーモン ---
install -m 0755 daemon/ls210d-gpiod.py /usr/local/sbin/ls210d-gpiod.py
mkdir -p /etc/ls210d-driver
if [ ! -f /etc/ls210d-driver/ls210d-gpiod.conf ]; then
  install -m 0644 daemon/ls210d-gpiod.conf.example /etc/ls210d-driver/ls210d-gpiod.conf
fi
if [ "$DRY" = 1 ]; then
  # dry_run を有効化 (既存 conf がある場合は追記ではなく置換になる点に注意して手動確認すること)
  grep -q '^dry_run' /etc/ls210d-driver/ls210d-gpiod.conf || echo 'dry_run = 1' >> /etc/ls210d-driver/ls210d-gpiod.conf
  echo "dry_run を有効にしました (poweroff は実行されません)"
fi
install -m 0644 daemon/ls210d-gpiod.service /etc/systemd/system/ls210d-gpiod.service

# --- SPI / MTD ---
install -m 0644 spi/ls210d-spi-nor.conf /etc/modules-load.d/ls210d-spi-nor.conf
modprobe spi-nor || true
modprobe mtdblock || true

systemctl daemon-reload
systemctl enable --now ls210d-gpiod.service

echo "== 状態 =="
systemctl --no-pager status ls210d-gpiod.service || true
echo "== /proc/mtd =="
cat /proc/mtd
ls -la /dev/mtd* 2>/dev/null || echo "/dev/mtd* はまだありません (probe.sh の結果と合わせて確認)"
