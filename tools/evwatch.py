#!/usr/bin/env python3
"""evwatch.py — /dev/input/event0 のイベントを人間可読で表示し、ログにも残す。

使い方 (LS210D 本体上で sudo 実行):
    sudo python3 evwatch.py [秒数]     # 既定 30 秒、Ctrl-C でも終了

表示と同時に /tmp/ls210d-events.log へ追記する (後から確認できるように)。
"""
import struct
import sys
import time

DEV = "/dev/input/event0"
LOG = "/tmp/ls210d-events.log"
EV_KEY = 1
NAMES = {1: "POWER-SWITCH", 357: "FUNCTION"}


def describe(code, value):
    name = NAMES.get(code, f"code{code}")
    if code == 1:
        return f"{name} -> {'ON' if value else 'OFF'}"
    if value == 1:
        return f"{name} pressed"
    if value == 0:
        return f"{name} released"
    return f"{name} value={value}"


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    fmt = "llHHi"  # timeval(sec,usec) + type + code + value (32bit)
    size = struct.calcsize(fmt)
    log = open(LOG, "a", buffering=1)
    start = time.time()
    print(f"watching {DEV} for {seconds}s — ボタンを操作してください (log: {LOG})")
    with open(DEV, "rb", buffering=0) as f:
        import select
        while time.time() - start < seconds:
            r, _, _ = select.select([f], [], [], 0.5)
            if not r:
                continue
            data = f.read(size)
            if len(data) < size:
                continue
            _sec, _usec, etype, code, value = struct.unpack(fmt, data)
            if etype != EV_KEY:
                continue
            line = f"{time.time() - start:7.3f}s  {describe(code, value)}"
            print(line)
            log.write(line + "\n")
    print("done")


if __name__ == "__main__":
    main()
