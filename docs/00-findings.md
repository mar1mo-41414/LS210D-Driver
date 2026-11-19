# LS210D 調査結果 (2026-11-17 時点)

対象機: Buffalo LinkStation LS210D (LS200 シリーズ、SoC Marvell Armada 370)。
検証に用いた Debian 化個体 (Debian 12、kernel 6.1.0-56-armmp、root は NFS)。
公式 FW 資料は `SampleData/` (FW 1.84 rootfs/initrd 展開済み、FW 1.86 実機回収分、SPI ダンプ)。
※ SampleData は git 管理外 (.gitignore)。SPI ダンプには機器固有の資格情報レコードが含まれるため外部に出さない。

## 1. 公式 FW (kernel 3.3.4) のスイッチ/GPIO 構成

- Buffalo 独自 GPIO ドライバ (BuffaloGpioDriver、built-in) が `/proc/buffalo/` を提供:
  - `gpio/switch/power` — 電源スライドスイッチ
  - `gpio/switch/auto_power` — AUTO 位置検出
  - `gpio/switch/func` — FUNCTION ボタン
  - `gpio/switch/sw_control`
  - `gpio/power_control/hdd%d`, `gpio/power_control/usb%d`
  - `gpio/fan/control`, `gpio/fan/lock`
  - `gpio/led/*` (LED は Debian 側で動作済みのため本プロジェクト対象外)
  - その他 `cpu_status`, `firmware`, `power_sw`, `kernevnt`
- イベント経路: カーネル内ドライバ → `/proc/buffalo/kernevnt` (イベントキュー) →
  常駐 `kernelmon` デーモン → `kernelmon_exec.sh` がイベント名 (FUNCSW_pushed 等) で分岐し、
  `libfuncsw` の処理 (DirectCopy 等) や電源系処理を呼ぶ。
- 電源スイッチ OFF 時のシャットダウンやスタンバイ遷移は `pwrmgr` / `PowerSave.sh` /
  `pmcd_exec.sh` が `gpio/switch/auto_power` を参照して行う。スタンバイ復帰/移行では
  `standby.rcDown` が `echo swpoff > /proc/buffalo/cpu_status` を書く。
- ファンは LS210D には存在しない (2026-11-17 実機確認)。カーネル文字列にある
  `gpio/fan/*` はシリーズ共通コード側のもので、この機種では未使用。
- 機種特性 (initrd の `.nas_features/*/0x00003011`、LS220D と共通ファーム):
  - `SUPPORT_MICON=0` — マイコン (micon) は無い。全て SoC の GPIO 直結。
  - `SUPPORT_SLIDE_POWER_SWITCH=on`, `POWER_SWITCH_TYPE=none`
  - `SUPPORT_FUNC_SW=1`, `SUPPORT_INIT_SW=1`
  - `SUPPORT_SHUTDOWN_DEPEND_ON_SW=1` — シャットダウン可否がスイッチ位置に依存する設計。

## 2. Debian 側 (検証機) の現状

DTB は Debian カーネルパッケージには含まれず、flash-kernel の
`/etc/flash-kernel/dtbs/armada-370-linkstation-ls210d.dtb` が
`/boot/dtbs/6.1.0-56-armmp/` にコピーされて使われている (現行 .dtb と .bak は同一ハッシュ)。
mainline v6.1 に LS210D の DTS は存在しない (Debian の debian.tar にも追加パッチなし)。

この DTB の出所はコミュニティプロジェクト **Debian_on_Buffalo**
(https://github.com/1000001101000/Debian_on_Buffalo、Debian 導入元)。
`Bookworm/device_trees/armada-370-linkstation-ls210d.dtb` と SHA-256 が完全一致する
ことを確認済み。DTS ソース (Jeremy J. Peper 作、Steve Shih / Toha の DT がベース) も
同リポにあり、本リポの `dts/` に複写を置いた。今後の DTS 改訂はこれを正本として行う。
なお同リポの LS220D 版 DTS との差分から、シリーズ共通基板 (ANTOKU) 上の他機種用配線も
読み取れる (LS220D: HDD present = gpio0_11/12、fan = gpio0_13/14 + alarm gpio0_10、
HDD2 電源 = gpio0_2。LS210D ではいずれも未使用/不存在)。

現行 DT の要点 (逆コンパイルで確認):
- `gpio-keys`:
  - power-switch: gpio0 pin15 (MPP15), active-low, `linux,code = <1>` (KEY_ESC)
  - function-button: gpio0 pin16 (MPP16), active-low, `linux,code = <357>` (KEY_OPTION)
  - → `/dev/input/event0` (gpio-keys) として登録済み。押下イベントは出るが、
    受けて動作するユーザーランドが無いため「機能していない」状態。
- `gpio-leds`: 動作済み (対象外)。function-red=gpio0_7、power-white=gpio1_22、
  power-red=gpio1_23、power-orange=gpio1_25、function-white=gpio1_27。
- HDD 電源: `regulator-fixed` "HDD1 power" = gpio0_8、always-on。
- `restart_poweroff` ノード (`compatible = "restart-poweroff"`) がある。
  このドライバは `pm_power_off` に「REBOOT_HARD で machine_restart」 を登録する。
  つまり **poweroff = 再起動して U-Boot に保持させる** 設計 (ドライバ冒頭コメント:
  "Power off by restarting and let u-boot keep hold of the machine")。
  → スイッチ ON のまま `shutdown` すると U-Boot がそのまま起動し直す = 再起動に見える。
  → スイッチ OFF で `shutdown` すれば U-Boot が起動を止め、電源断状態になる。
    **この挙動は 2026-11-17 に実機で検証済み** (スイッチ OFF なら正常に落ちる)。
- mainline の `linkstation-poweroff` ドライバ (Ethernet PHY の INTn ピンで電源を切る方式、
  Daniel González Cabanelas) は v6.1 時点で `buffalo,ls421d` / `ls421de` のみ対応で
  LS210D は対象外。Debian カーネルでも `CONFIG_POWER_RESET_LINKSTATION is not set`。

## 3. SPI フラッシュ / MTD の現状

- DT には既に定義がある: `spi@10600` (spi-orion) status=okay、配下に
  `spi-flash@0` (`compatible = "mx25l8005", "jedec,spi-nor"`, 50MHz)、
  パーティション `u-boot` (0x0-0xF0000, read-only) と
  `u-boot-env` (0xF0000-0x10000, read-only)。実チップは 1MiB (公式 FW では
  /proc/mtd 単一区画 `spi_flash` 1MiB、m25p80 built-in で駆動)。
- 検証機では `spi_orion` モジュールはロード済みで `/sys/bus/spi/devices/spi0.0` は
  存在するが、ドライバがバインドされておらず `/proc/mtd` は空、`/dev/mtd*` も無い。
- 原因の見立て: spi デバイスの modalias は `spi:mx25l8005` で、spi-nor モジュールの
  エイリアス (`of:N*T*Cjedec,spi-nor`, `spi:m25p*-nonjedec` 等) のどれにも一致しないため
  udev の自動ロードが効かない。`CONFIG_MTD_SPI_NOR=m` でモジュール自体は存在する。
  → `modprobe spi-nor` でバインドされるはず、という見立ては **2026-11-17 に実機で確認済み**:
    `spi-nor spi0.0: mx25l8005 (1024 Kbytes)` と出て、DT 通りの2パーティションで
    mtd0 = `u-boot` (0xF0000)、mtd1 = `u-boot-env` (0x10000) と /dev/mtd0, mtd0ro,
    mtd1, mtd1ro が出現した (tools/probe.sh のログ /tmp/ls210d-probe-20261117-213004.log)。
    つまり SPI 側は modules-load.d の設定だけで恒常化できる。
- 同日の debugfs gpio 表示で現行の線の状態も記録できた:
  gpio-15 Power Switch = in lo (スイッチ ON で Low、入力イベントの押下状態とも一致)、
  gpio-16 Function Button = in hi (未押下)、gpio-8 HDD 電源 = out hi、
  LED は gpio-7 / 54 / 55 / 57 / 59。

## 4. 公式カーネル解析の結論 (2026-11-17、詳細は docs/02-official-kernel-gpio-spi.md)

vmlinux (3.3.4) の kallsyms 抽出 + 逆アセンブルで確定したこと:

- ピン解決は `mvBoardGpioPinNumGet` がボード記述子の GPP 配列を引く方式。
  記述子候補は ISMT370 / JSMT370 の2つで、どちらで起動するかは U-Boot の ATAG 依存
  (イメージからは確定不可)。ただし主要ピンは両者共通で以下と確定:
  - switch/power = **GPIO15, active-low** (DT と一致)
  - switch/func = **GPIO16, active-low** (DT と一致)
  - power_control/hdd0 = **GPIO8, active-high** (DT の HDD 電源レギュレータと一致)
  - power_control/usb0 = GPIO4, active-high (DT に無い線。USB 電源)
  - hotplug/sata0 = GPIO11 (検出入力)
  - fan/control = GPIO13+14、fan/lock = GPIO10 は記述子に存在するが、
    LS210D にはファン自体が無い (シリーズ共通基板の定義のみ)
- **auto_power は未配線 (ピン −1、常時 "off")**。スライドスイッチの真理表コードは
  あるが、この基板では検出できるのは ON/OFF の2状態のみで、AUTO 位置の GPIO 割り当ては
  存在しない。→ Debian 側でも AUTO を扱う必要はない (デーモン/DTS 追加不要)。
- **公式カーネルにも pm_power_off は存在しない** (設定箇所なし、poweroff は no-op)。
  物理的に止めるプリミティブは machine_halt で、Ethernet PHY の LED2/INTn を
  force する書き込み (ページ3 reg16 = 0x1880、mainline の linkstation-poweroff と同族)
  + システムリセットレジスタ対 (0xd0018260/264) への書き込み + 無限ループ、という構成。
- `cpu_status` は電源操作ではなく状態変数。消費者は U-Boot と initrd で、
  「swpoff を書いて再起動 → 次段 (U-Boot) が止まる」が公式フロー。
  Debian の restart-poweroff 方式はこの公式フローの mainline 版と言える。
- SPI は Marvell 独自 sflash ドライバが提供し、固定パーティションは無い
  (cmdline の mtdparts が無ければ全体が単一 MTD "spi_flash")。
  Debian DT の u-boot / u-boot-env 分割はコミュニティ側の定義。

## 5. 残る未確定事項

- ボード記述子が ISMT370 / JSMT370 のどちらか (相違は hdd1 ピンと sata1 の有無のみ。
  本プロジェクトの対象範囲には影響しない)
- halt 時の PHY INTn 書き込みと外部ラッチの寄与分担 (Debian 側は restart-poweroff で
  実用上問題ないため深追いしない)
