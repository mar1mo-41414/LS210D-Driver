#!/bin/sh
# probe.sh — Debian 化した LS210D 本体上で sudo 実行する診断スクリプト。
# 目的:
#   1) spi-nor を手動ロードすると SPI フラッシュ (MTD) が現れるか確認する
#   2) GPIO ラインの現在の状態を記録する
# 書き込みは一切しない (モジュールロードと読み取りのみ)。spi-nor の probe は JEDEC ID 読み取りのみ。
# 出力は端末にそのまま出す。保存したい場合は tee を使う:
#   sudo sh probe.sh | tee /tmp/probe.log
# イベント確認 (FUNCTION / 電源スイッチ) をしたい時だけ --events を付ける
# (10秒間 /dev/input/event0 を表示するので、その間にボタンを操作する)。
set -u
echo "== date =="; date
echo "== uname =="; uname -a
echo "== before: /proc/mtd =="; cat /proc/mtd
echo "== before: lsmod spi/mtd =="; lsmod | grep -E 'spi|mtd' || true
echo "== modprobe spi-nor =="
modprobe -v spi-nor
sleep 1
echo "== after: /proc/mtd =="; cat /proc/mtd
echo "== after: /dev/mtd* =="; ls -la /dev/mtd* 2>&1
echo "== spi device driver link =="; ls -la /sys/bus/spi/devices/spi0.0/ | grep -E 'driver|modalias'
cat /sys/bus/spi/devices/spi0.0/modalias
echo "== dmesg (spi/mtd/nor) =="; dmesg | grep -iE 'spi-nor|mtd|jedec' | tail -10
echo "== gpio state =="; cat /sys/kernel/debug/gpio 2>/dev/null || echo "(debug gpio not readable)"
echo "== input devices =="; cat /proc/bus/input/devices
if [ "${1:-}" = "--events" ]; then
  echo "== event check: 10秒間 event0 を表示します。その間に FUNCTION / 電源スイッチを操作してください =="
  if command -v evtest >/dev/null; then
    timeout 10 evtest /dev/input/event0 || true
  else
    timeout 10 od -A d -t x1 /dev/input/event0 | head -40 || true
  fi
fi
echo "== done =="
