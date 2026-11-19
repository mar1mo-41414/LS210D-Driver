#!/usr/bin/env python3
# ls210d-gpiod — Buffalo LinkStation LS210D (Debian) 用スイッチ監視デーモン
#
# 役割 (公式 FW の kernelmon に相当する部分のうち、スイッチ系だけを mainline 流に実装):
#   * 電源スライドスイッチが OFF になったら、猶予の後に systemctl poweroff する
#   * FUNCTION ボタンの押下でフックスクリプトを実行する
#
# 入力はカーネルの gpio-keys ドライバが出す evdev イベントを使う。
# 現行 DT (flash-kernel の armada-370-linkstation-ls210d.dtb) での割り当て:
#   電源スイッチ : gpio0_15 (MPP15), active-low, linux,code = 1   (KEY_ESC)
#   FUNCTION     : gpio0_16 (MPP16), active-low, linux,code = 357 (KEY_OPTION)
# active-low なので「押下 (value=1)」= GPIO Low = スイッチ ON 側 / ボタン押下中。
# 電源スイッチの「解放 (value=0)」= スイッチ OFF 側。
#
# poweroff の実体は DT の restart-poweroff ドライバにより
# 「再起動して U-Boot に保持させる」動作になる。スイッチ OFF 状態であれば
# U-Boot が起動を止めるため、結果として電源断状態になる (docs/01-design.md)。
#
# 依存は Python 3 標準ライブラリのみ。root で実行すること。
import configparser
import fcntl
import os
import struct
import subprocess
import sys
import threading
import time

DEFAULTS = {
    "device_name": "gpio-keys",        # /sys/class/input/event*/device/name で照合する名前
    "power_code": "1",                 # 電源スイッチの linux,code
    "function_code": "357",            # FUNCTION ボタンの linux,code
    "power_off_grace_sec": "3",        # OFF 検出から poweroff までの猶予 (秒)。この間に ON に戻せば取消
    "function_long_press_sec": "2",    # FUNCTION 長押し判定 (秒)
    "poweroff_command": "systemctl poweroff",
    "function_hook": "/etc/ls210d-driver/function-hook.sh",
    "function_hook_long": "/etc/ls210d-driver/function-hook-long.sh",
    "dry_run": "0",                    # 1 にすると poweroff / フックを実行せずログだけ出す
}
CONF_PATH = "/etc/ls210d-driver/ls210d-gpiod.conf"

EV_KEY = 1
# struct input_event (32bit ARM, native): timeval(2 x long) + type(H) + code(H) + value(i)
EVENT = struct.Struct("llHHi")


def log(msg):
    print(f"ls210d-gpiod: {msg}", flush=True)


def load_conf():
    conf = dict(DEFAULTS)
    if os.path.exists(CONF_PATH):
        cp = configparser.ConfigParser()
        cp.optionxform = str
        with open(CONF_PATH) as f:
            cp.read_file(f)
        if cp.has_section("ls210d-gpiod"):
            for k, v in cp.items("ls210d-gpiod"):
                conf[k] = v
    return conf


def find_event_device(name):
    """name が一致する /dev/input/event* を探す。見つからなければ None。"""
    base = "/sys/class/input"
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("event"):
            continue
        try:
            with open(os.path.join(base, entry, "device", "name")) as f:
                if f.read().strip() == name:
                    return "/dev/input/" + entry
        except OSError:
            continue
    return None


def eviocgkey(fd, nbits=768):
    """EVIOCGKEY: 現在のキー押下状態ビットマップを取得し、set で返す。"""
    size = (nbits + 7) // 8
    buf = bytearray(size)
    # _IOC(_IOC_READ=2, 'E'=0x45, 0x18, size)
    request = (2 << 30) | (size << 16) | (0x45 << 8) | 0x18
    fcntl.ioctl(fd, request, buf, True)
    pressed = set()
    for code in range(nbits):
        if buf[code // 8] & (1 << (code % 8)):
            pressed.add(code)
    return pressed


def run_hook(path, dry_run, label):
    if not path:
        return
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        log(f"{label}: hook not installed ({path}), skipped")
        return
    if dry_run:
        log(f"{label}: dry-run, would execute {path}")
        return
    log(f"{label}: executing {path}")
    subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PowerSwitch:
    """電源スイッチ OFF → 猶予 → poweroff。ON に戻れば取消。"""

    def __init__(self, conf):
        self.grace = float(conf["power_off_grace_sec"])
        self.command = conf["poweroff_command"]
        self.dry_run = conf["dry_run"] == "1"
        self._timer = None
        self._gen = 0
        self._lock = threading.Lock()

    def on_off_detected(self):
        with self._lock:
            if self._timer is not None:
                return
            log(f"power switch OFF detected, poweroff in {self.grace:.0f}s unless switched back ON")
            self._gen += 1
            t = threading.Timer(self.grace, self._do_poweroff, args=(self._gen,))
            t.daemon = True
            t.start()
            self._timer = t

    def on_on_detected(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
                self._gen += 1
                log("power switch back ON, pending poweroff cancelled")

    def _do_poweroff(self, gen):
        with self._lock:
            if gen != self._gen:
                return  # ON に戻されて取消済み
            self._timer = None
        if self.dry_run:
            log(f"dry-run, would execute: {self.command}")
            return
        log(f"executing: {self.command}")
        subprocess.Popen(self.command.split())


def main():
    conf = load_conf()
    power_code = int(conf["power_code"])
    function_code = int(conf["function_code"])
    long_press = float(conf["function_long_press_sec"])
    dry_run = conf["dry_run"] == "1"
    power = PowerSwitch(conf)

    dev = find_event_device(conf["device_name"])
    if dev is None:
        log(f"input device named {conf['device_name']!r} not found, exiting")
        return 1
    log(f"watching {dev} (power_code={power_code}, function_code={function_code}, dry_run={dry_run})")
    fd = os.open(dev, os.O_RDONLY)

    # 起動時点のスイッチ状態。OFF のまま起動していた場合は即 poweroff せずログのみ
    # (U-Boot がスイッチ OFF で保持する役割と重複させない)。
    try:
        pressed = eviocgkey(fd)
        if power_code in pressed:
            log("initial state: power switch ON")
        else:
            log("initial state: power switch OFF (no action; poweroff triggers on ON->OFF change)")
    except OSError as e:
        log(f"initial state read failed: {e}")

    func_state = {"pressed_at": None, "long_fired": False, "timer": None}

    def func_fire_long():
        func_state["long_fired"] = True
        run_hook(conf["function_hook_long"], dry_run, "FUNCTION long press")

    while True:
        data = os.read(fd, EVENT.size * 64)
        if not data:
            time.sleep(0.1)
            continue
        for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _sec, _usec, ev_type, code, value = EVENT.unpack_from(data, off)
            if ev_type != EV_KEY:
                continue
            if code == power_code:
                if value == 0:      # 解放 = OFF 側
                    power.on_off_detected()
                elif value == 1:    # 押下 = ON 側
                    power.on_on_detected()
            elif code == function_code:
                # gpio-keys はこのボタンでオートリピートを出さないため、
                # 長押しはタイマで判定する (押下継続のまま閾値を超えたら長押し扱い)。
                if value == 1:
                    func_state["pressed_at"] = time.monotonic()
                    func_state["long_fired"] = False
                    t = threading.Timer(long_press, func_fire_long)
                    t.daemon = True
                    t.start()
                    func_state["timer"] = t
                elif value == 0:
                    if func_state["timer"] is not None:
                        func_state["timer"].cancel()
                        func_state["timer"] = None
                    if func_state["pressed_at"] is not None and not func_state["long_fired"]:
                        run_hook(conf["function_hook"], dry_run, "FUNCTION press")
                    func_state["pressed_at"] = None
    return 0


if __name__ == "__main__":
    sys.exit(main())
