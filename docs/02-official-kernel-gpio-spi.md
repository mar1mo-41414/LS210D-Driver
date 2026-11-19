# LS210D 公式カーネル (Linux 3.3.4 / FW 1.84) GPIO・電源・SPI 解析レポート

- 解析日: 2026-11-17
- 対象: `work-kernel/vmlinux.elf.raw` (zImage の gzip 部を展開した非圧縮カーネルイメージ、5,707,844 バイト)
- 対象機: Buffalo LS210D (LS200 シリーズ、Armada 370、PRODUCTID 0x00003011、LS220D と共通ファーム)
- 目的: Debian 6.1 (検証機) で電源スイッチ / FUNCTION ボタン / `/dev/mtd` を復活させるため、公式カーネルの Buffalo GPIO ドライバ・電源オフ経路・SPI フラッシュ構成をコードから確定する。

カーネルバージョン文字列:

```
Linux version 3.3.4 (root@nasbuild) (gcc version 4.6.2 (Linaro GCC 4.6-2011.12 / Marvell GCC release 20120113) ) #1 Fri Feb 16 16:18:04 JST 2024
```

ビルドパス文字列に `/home/ReleaseBuild/LS200_1.84/F0017_nas-bua/buildroot/buildroot-2012.08/output/build/linux-3.3.4/...` を含む (FW 1.84 用ビルドであることの裏付け)。

---

## 1. 解析手法

### 1.1 kallsyms 抽出

- 解析用の計算機上に venv (`/tmp/venv-kallsyms`) を作り `vmlinux-to-elf 1.4.0` を pip install、`kallsyms-finder` / `vmlinux-to-elf` を使用した。
- カーネルベース VA は **0xc0008000** で確定 (ファイルオフセット = VA − 0xc0008000)。
- kallsyms テーブルのファイルオフセット (kallsyms-finder 出力):
  - addresses: 0x40df40
  - num_syms: 0x42c5f0 (**シンボル総数 31,148**)
  - names: 0x42c600
  - markers: 0x485160
  - token_table: 0x485350
  - token_index: 0x4856d0
- 再構成 ELF `vmlinux.elf` (6.6 MB) を生成。以後の逆アセンブルは `arm-none-eabi-objdump` (binutils 2.42) でこの ELF に対して実施。`.kernel` セクション 1 個 (VA 0xc0008000、file off 0x124、size 0x571844) + `.bss` NOBITS 0x1000000 @ 0xc0579844。シンボルテーブル 20,455 エントリ。
- 注意: objdump はリテラルプールのワードを命令として誤デコードする (例: `blx bec...`)。リテラル値は必ず `vmlinux.elf.raw` から VA − 0xc0008000 のオフセットで u32 として直接読んだ。繰り返し現れるリテラル `0xfbb18fff` はレジスタアクセス用の意図的なアンカー (ベース+0xfff、負オフセットで使う) で、破損ではない。
- proc ハンドラが使う文字列には非アライン VA のものが多い ("on\n" @ 0xc04d412b 等)。`strings` の出力に頼らず生バイトで確認した。

### 1.2 中間生成物 (すべて `work-kernel/` 配下)

| ファイル | 内容 |
|---|---|
| `kallsyms-full.txt` | kallsyms-finder の全出力 (31,147 行のシンボル) |
| `kallsyms-finder.log` | kallsyms-finder のログ |
| `vmlinux.elf` | vmlinux-to-elf 再構成 ELF |
| `buffalo-symbols.txt` | Buffalo 関係シンボルの抽出 |
| `disasm-full.txt` | カーネル全体の objdump (49 MB、1,196,628 行) |
| `disasm-buffalo-core.txt` | Buffalo GPIO コア領域 0xc005b340–0xc005e600 |
| `disasm-buffalo-init.txt` | buffaloGpioDriver_init 0xc052cd48–0xc052d374 |
| `disasm-machine-power.txt` | machine_halt/power_off/restart 0xc000f300–0xc000f600 |
| `disasm-kernel-power.txt` | kernel_power_off 周辺 0xc006ee00–0xc006f100 |
| `disasm-mvboard.txt` | mvBoard 系 0xc001e800–0xc001ee20 |
| `disasm-hdd-usb.txt` | HDD/USB 電源 proc ハンドラ 0xc005c8f8–0xc005cb40 |
| `disasm-fan.txt` | ファン proc ハンドラ 0xc005d29c–0xc005d678 |
| `disasm-cpustatus.txt` | cpu_status ハンドラ 0xc005dca4–0xc005e1f4 |
| `disasm-swpoll.txt` | スイッチポーリング 0xc005c6a0–0xc005c8f8 |
| `disasm-irq-poll.txt` | スイッチ IRQ / ポーリングワーカー 0xc005d678–0xc005dbe0 |
| `disasm-sata-init.txt` | BuffaloSataHotplug_init 0xc005e538–0xc005e720 |
| `disasm-sflash-probe.txt` | sflash_probe 0xc02dc924–0xc02dcb34 |
| `disasm-axpdb.txt`, `disasm-axpdb-part1.txt` | axp_db_init (ボード初期化) |

---

## 2. Buffalo 関係シンボル一覧 (主要分)

すべて再構成 ELF の nm 出力より。アドレスは VA。

### 2.1 GPIO コア / proc ハンドラ

| シンボル | アドレス | 役割 |
|---|---|---|
| get_proc_buffalo | 0xc005b384 | /proc/buffalo ディレクトリ取得 |
| BuffaloGpio_HddPowerOff | 0xc005b674 | (4 バイト、末尾ジャンプ) |
| **BuffaloGpio_CpuReset** | **0xc005b678** | §7.3 参照。EXPORT_SYMBOL |
| bfIsSupportMicon | 0xc005b69c | |
| BuffaloGpio_Init | 0xc005b6bc | `bx lr` のみ (no-op) |
| LedEnable / LedDisable / LedInvert / LedBlinkEnable / LedBlinkDisable | 0xc005b6c0–0xc005b6d0 | bfGpp ヘルパへの末尾ジャンプ |
| HddPowerOn | 0xc005b6d4 | 同上 |
| UsbPowerOn / UsbPowerOff | 0xc005b6d8 / 0xc005b6dc | 同上 |
| EthLedOn / EthLedOff | 0xc005b6e0 / 0xc005b6e4 | no-op |
| BuffaloReadPmGpio / BuffaloWritePmGpio / Buffalo_has_PM | 0xc005b6e8–0xc005b6f8 | 常時 0 を返すスタブ (このボードに PM GPIO チップは無い) |
| bfGppInRegBitTest | 0xc005b6fc | Data-In 生読み |
| bfGppOutRegBitTest | 0xc005b73c | Data-Out 生読み |
| bfGppOutRegBitSet / Clr / Inv | 0xc005b770 / 0xc005b7a0 / 0xc005b7d4 | |
| bfGppBlinkRegBitTest / Set / Clr | 0xc005b834 / 0xc005b868 / 0xc005b898 | |
| bfGppPolarityRegBitTest | 0xc005b8cc | 極性レジスタ読み |
| bfGppOutEnableRegBitTest / Set / Clr | 0xc005b8f8 / 0xc005b92c / 0xc005b95c | |
| bfGppDataInPolRegBitTest | 0xc005b990 | Assert 判定用 |
| **bfGppOutRegBitAssert** | **0xc005b9c4** | 極性を考慮して「有効レベル」に駆動 (§3.3) |
| **bfGppOutRegBitNagate** | **0xc005bab0** | Assert の逆 |
| bfGppAllLedOn / AllLedOff | 0xc005ba10 / 0xc005baf8 | LED 種別 36,37,38,35 を使用 |
| BuffaloKernevnt_read_proc / init / queueout / queuein | 0xc005bcec / 0xc005be48 / 0xc005bee4 / 0xc005bf88 | イベントキュー (/proc/buffalo/kernevnt) |
| BuffaloFanStatusWriteProc | 0xc005c3f0 | fan/lock 書き込み (実質 no-op 側) |
| BuffaloFuncReadProc | 0xc005c3f8 | switch/func 読み |
| BuffaloSwPollingReadProc | 0xc005c488 | switch/sw_control 読み |
| BuffaloAutoPowerReadProc | 0xc005c510 | switch/auto_power 読み |
| BuffaloPowerReadProc | 0xc005c5a0 | switch/power 読み |
| BuffaloSwPollingCheck | 0xc005c6a0 | スライドスイッチ状態監視タイマ (§5.2) |
| BuffaloSwPollingWriteProc | 0xc005c808 | sw_control 書き込み (ポーリング開始/停止) |
| BuffaloHddWriteProc / BuffaloUsbWriteProc | 0xc005c8f8 / 0xc005c970 | |
| BuffaloHddReadProc / BuffaloUsbReadProc | 0xc005ca20 / 0xc005cab0 | |
| BuffaloLed_StatChange, LedReadProc, LedBlinkReadProc, LedBlinkWriteProc, LedWriteProc | 0xc005cb40–0xc005d29c | LED (本レポート対象外) |
| BuffaloFanControlWriteProc | 0xc005d29c | fan/control 書き込み (§6) |
| BuffaloFanControlReadProc | 0xc005d428 | fan/control 読み (§6) |
| gpio_power_read_proc | 0xc005d548 | /proc/buffalo/power_sw 読み (§4.3) |
| BuffaloFanStatusReadProc | 0xc005d5e0 | fan/lock 読み |
| BuffaloCpuInterrupts_exit | 0xc005d678 | |
| PowerSWInt_en_proc_open / show | 0xc005d6e8 / 0xc005d8f4 | /proc/buffalo/PowerSWInt_en |
| FuncSwInterrupts | 0xc005d6fc | IRQ トップハーフ (種別 40) |
| InitSwInterrupts | 0xc005d764 | IRQ トップハーフ (種別 43) |
| PowSwInterrupts | 0xc005d7cc | IRQ トップハーフ (種別 41) |
| PollingPowerSWStatus | 0xc005d830 | デバウンス + イベント発行 (§5.3) |
| PollingFuncSWStatus | 0xc005d930 | 同上 (種別 40) |
| PollingINITSWStatus | 0xc005da04 | 同上 (種別 43) |
| buffaloDriver_init / exit | 0xc052d2cc / 0xc005dbe0 | |
| BuffaloCpuStatusReadProc | 0xc005dca4 | /proc/buffalo/cpu_status 読み (§7.4) |
| BuffaloCpuStatusWriteProc (.part.0 / 本体) | 0xc005de08 / 0xc005df8c | 同書き込み |
| BuffaloClassGet | 0xc005e1f4 | |
| bfSetBoardId / bfGetBoardId | 0xc005e250 / 0xc005e260 | Buffalo ボード ID (§3.2) |
| bfSet/GetSataHotDetectType | 0xc005e270 / 0xc005e280 | ATAG ビット 14–15 |
| bfSet/GetFanControlType | 0xc005e290 / 0xc005e2a0 | ATAG ビット 12–13 |
| bfSet/GetSataMaxCh | 0xc005e2b0 / 0xc005e2c4 | ATAG ビット 9–11 (+1) |
| bfSet/GetUsbMaxCh | 0xc005e2d4 / 0xc005e2e8 | ATAG ビット 7–8 (+1) |
| bfSetPowerSwType / bfGetPowerSwtype | 0xc005e2f8 / 0xc005e308 | ATAG ビット 6 |
| PollingSATAHotplug | 0xc005e318 | |
| BuffaloSataHotplugReadProc | 0xc005e410 | hotplug/sata%d 読み |
| SataHotplugInterrupts | 0xc005e4c0 | |
| BuffaloSataHotplug_init | 0xc005e538 | §8 |
| getSataHotplugIrq / initSataHotplug / resetSataHotplugIrq / resetSataHotplugDev / getSataHotplugStat / getSataHotplugDevId | 0xc005e720–0xc005e87c | |

### 2.2 初期化エントリ

| シンボル | アドレス |
|---|---|
| mv_gpio_init | 0xc052ccfc |
| BuffaloMicon_init | 0xc052cd48 |
| buffaloGpioDriver_init | 0xc052cd98 |
| BuffaloCpuInterrupts_init | 0xc052d18c |
| axp_db_init (.part.1 / 本体) | 0xc052bfe4 / 0xc052c318 |
| parse_tag_mv_uboot | 0xc052bcec (ATAG パーサ) |

### 2.3 Marvell GPP / ボード系

| シンボル | アドレス |
|---|---|
| mvBoardIdGet | 0xc001e810 |
| mvBoardGppConfigGet | 0xc001ebe0 |
| mvBoardMppGet | 0xc001ec70 |
| mvBoardGpioIntMaskGet | 0xc001ecbc |
| **mvBoardGpioPinNumGet** | **0xc001ed40** |
| mvBoardUSBVbusEnGpioPinGet (種別 3) | 0xc001edc8 |
| mvBoardUSBVbusGpioPinGet (種別 2) | 0xc001edd4 |
| mvBoardResetGpioPinGet (種別 21) | 0xc001edfc |
| mvBoardReset | 0xc001ee08 |
| mvBoardEnvInit | 0xc001f1a8 付近 (極性/タイプ初期化、§3.4) |
| mvGppInit / mvGppTypeSet / mvGppBlinkEn / mvGppPolaritySet / mvGppPolarityGet / mvGppValueGet / mvGppValueSet | 0xc001c894 / 0xc001c8ac / 0xc001c918 / 0xc001c944 / 0xc001c970 / 0xc001c998 / 0xc001c9b8 |

### 2.4 電源系

| シンボル | アドレス |
|---|---|
| machine_power_off | 0xc000f470 |
| machine_halt | 0xc000f428 |
| machine_restart | 0xc000f494 |
| kernel_power_off | 0xc006eef0 |
| **pm_power_off (変数, .bss)** | **0xc0579a50** |
| pm_power_off_prepare (変数, .bss) | 0xc059d9b0 |
| arm_pm_restart (変数, .data) | 0xc054f2d4 (初期値 0xc000f204) |

---

## 3. GPIO アーキテクチャ

### 3.1 ピン番号の解決: mvBoardGpioPinNumGet(type, index)

Buffalo ドライバの全 proc ハンドラは、ピンを直接持たず「種別 (type)」から毎回引き直す。

`mvBoardGpioPinNumGet(type, index)` (0xc001ed40) の動作:

1. ボード記述子ポインタ配列 **0xc0551c0c** を `bfGetBoardId()` で引く。
2. 記述子フィールド **+0x68 (104)** = GPP エントリ数 (バイト)、**+0x6c (108)** = GPP エントリ配列へのポインタ。
3. 各エントリは 8 バイト `{u32 type, u8 pin, u8 pad[3]}`。type が一致する index 番目のエントリの **pin バイト** を返す。無ければ −1。
4. 返る pin は **グローバル GPP/GPIO 番号**。bfGpp ヘルパは `bank = (pin > 31) ? 1 : 0`、`bit = pin & 31` と分解する (バンク 0/1 のみ対応。バンク 2 のピンは Buffalo ドライバからは操作されない)。

### 3.2 ボード ID と ATAG

`parse_tag_mv_uboot` (0xc052bcec、ATAG パーサ) が U-Boot から渡されるタグワード `[tag+8]` を分解して Buffalo 側のボード情報構造体 (0xc057be38 付近) に格納する:

| ビット | 意味 | 格納先アクセサ |
|---|---|---|
| 0–3 (下位ニブル) | Buffalo ボード ID | bfSetBoardId / bfGetBoardId |
| 6 | PowerSwType | bfSetPowerSwType |
| 7–8 (+1) | UsbMaxCh | bfSetUsbMaxCh |
| 9–11 (+1) | SataMaxCh | bfSetSataMaxCh |
| 12–13 | FanControlType | bfSetFanControlType |
| 14–15 | SataHotDetectType | bfSetSataHotDetectType |

(同ワードの `lsr #16` は別構造体 0xc0579c00+0x30 に入る Marvell 側の値で、Buffalo 側と混同しないこと。)

ボード記述子配列 0xc0551c0c には有効なエントリが 3 つだけある:

| index | 記述子 VA | 名前文字列 | GPP 数 |
|---|---|---|---|
| 0 | 0xc0551fac | "ISMT370" | 15 |
| 1 | 0xc0551c18 | "JSMT370" | 16 |
| 2 | 0xc0552338 | "RD-88F6710" (Marvell リファレンスデザイン、Buffalo 製品ではない) | 1 (種別 2 → pin 24 のみ) |

**LS210D が ISMT370 / JSMT370 のどちらで起動するかはカーネルイメージだけでは確定できない** (ボード ID は U-Boot が ATAG で渡す実行時値)。§9 の未確定事項に挙げ、実機での判別方法を示す。両者は LS210D に関係するピンの大半が一致し、相違は HDD ch1 と SATA hotplug ch1 のみ (次節)。

### 3.3 レジスタマップと Assert / Nagate の意味

Marvell GPP レジスタブロック。LSP の INTER_REGS 仮想ベース 0xfbb10000 ↔ 物理 0xd0010000 (仮想 = 物理 − 0xd0010000 + 0xfbb10000)。コード中ではアンカー 0xfbb18fff + 負オフセットでアクセスされる。

| レジスタ | バンク 0 (仮想 / 物理) | バンク 1 (仮想 / 物理) |
|---|---|---|
| Data-Out | 0xfbb18100 / 0xd0018100 | 0xfbb18140 / 0xd0018140 |
| Out-Enable (Type) | 0xfbb18104 / 0xd0018104 | 0xfbb18144 |
| Blink-Enable | 0xfbb18108 | 0xfbb18148 |
| Polarity | 0xfbb1810c / 0xd001810c | 0xfbb1814c |
| Data-In | 0xfbb18110 / 0xd0018110 | 0xfbb18150 |

バンクストライドは 0x40。`mvGppValueGet` は `((group + 0x600) << 6) + 0x110 | 0xfbb00000` で Data-In を組み立てる (ソフトウェア側で極性は適用しない生読み)。

`bfGppOutRegBitAssert` (0xc005b9c4) / `bfGppOutRegBitNagate` (0xc005bab0):

- Assert: そのピンの Polarity レジスタビット (bfGppDataInPolRegBitTest、0x...10c/14c) を読み、**polarity==0 なら Data-Out ビットを 1 に、polarity==1 なら 0 に** 駆動する (mvGppValueSet 経由)。
- Nagate はその逆。
- すなわち **Assert = 「極性レジスタで定義された有効レベル」への駆動** で、有効レベルが active-high なのは polarity ビットが 0 のピン。

入力側 `bfGppInRegBitTest` は Data-In レジスタの生ビットをそのまま返す (1 = レジスタ読み 1)。Armada 370 の Polarity レジスタは入力経路では Data-In 読み値をハードウェアで反転させるため、**polarity=1 のピンは「読み 1 ⇔ 物理レベル LOW」** になる (§3.4 の初期値と §5 の読み取り規約、Debian DT の active-low と一致する)。

### 3.4 極性・タイプ・初期出力値 (mvBoardEnvInit)

`mvBoardEnvInit` はボード記述子のフィールドをそのままレジスタへ書き込む:

- 記述子 **+0x8c/+0x90/+0x94** → Data-Out バンク 0/1/2 へ直接書き込み
- 記述子 **+0x98/+0x9c/+0xa0** → `mvGppPolaritySet(group, mask=~0, value)` (バンク 0/1/2 の極性)
- 記述子 **+0x80/+0x84/+0x88** → `mvGppTypeSet(group, mask=~0, value)` (バンク 0/1/2 の Out-Enable。**ビット 1 = 入力 (出力禁止)、0 = 出力**。スイッチ類が 1、電源出力類が 0 であることと整合)

ISMT370 / JSMT370 共通の極性初期値:

- バンク 0 極性 = **0x00018000** → **GPIO15 と GPIO16 のみ polarity=1**、他は全て 0
- バンク 1 極性 = 0、バンク 2 極性 = 0

Data-Out 初期値 (バンク 0):

- ISMT370: **0x110** (GPIO4=USB 電源 ON、GPIO8=HDD0 電源 ON で起動)
- JSMT370: **0x114** (上記 + GPIO2=HDD1 電源 ON)

Type (Out-Enable) バンク 0: ISMT370 = 0xffff8c43、JSMT370 = 0xffff9c43。

対象ピンの初期状態まとめ:

| GPIO | 極性 | 入出力 | Data-Out 初期値 (ISMT / JSMT) |
|---|---|---|---|
| 2 (HDD1 電源, JSMT のみ) | 0 | 出力 | 0 / 1 |
| 4 (USB 電源) | 0 | 出力 | 1 / 1 |
| 8 (HDD0 電源) | 0 | 出力 | 1 / 1 |
| 9 (HDD1 電源, ISMT のみ) | 0 | 出力 | 0 / − |
| 10 (ファンロック入力) | 0 | 入力 | − |
| 11 (SATA0 検出) | 0 | 入力 | − |
| 12 (SATA1 検出, JSMT のみ) | 0 | 入力 | − |
| 13 (ファン制御 32) | 0 | 出力 | 0 / 0 |
| 14 (ファン制御 33) | 0 | 出力 | 0 / 0 |
| 15 (電源スイッチ) | **1** | 入力 | − |
| 16 (FUNCTION) | **1** | 入力 | − |
| 54, 55, 57, 59 (LED) | 0 | 出力 | − |

---

## 4. GPP 種別テーブルと proc 対応表

### 4.1 種別 → GPIO 番号 (ボード記述子の GPP 配列実測値)

GPP 配列: ISMT370 = 0xc0552260 (15 件)、JSMT370 = 0xc0551ecc (16 件)。

| 種別 (type) | 意味 (推定根拠は §4.2) | ISMT370 | JSMT370 |
|---|---|---|---|
| 3 | USB 電源 | GPIO4 | GPIO4 |
| 23 idx0 | HDD0 電源 | GPIO8 | GPIO8 |
| 23 idx1 | HDD1 電源 | **GPIO9** | **GPIO2** |
| 34 | ファンロック (回転検出入力) | GPIO10 | GPIO10 |
| 47 idx0 | SATA0 hotplug 検出 | GPIO11 | GPIO11 |
| 47 idx1 | SATA1 hotplug 検出 | **なし** | **GPIO12** |
| 32 | ファン制御ビット 0 | GPIO13 | GPIO13 |
| 33 | ファン制御ビット 1 | GPIO14 | GPIO14 |
| 41 | 電源スイッチ | GPIO15 | GPIO15 |
| 40 | FUNCTION スイッチ | GPIO16 | GPIO16 |
| 38 | LED | GPIO54 | GPIO54 |
| 36 | LED | GPIO55 | GPIO55 |
| 37 | LED | GPIO57 | GPIO57 |
| 35 | LED | GPIO59 | GPIO59 |
| 45 idx0 / idx1 | (LED 系、種別 45) | GPIO60 / GPIO61 | GPIO60 / GPIO61 |

両テーブルに **存在しない種別** (PinNumGet が −1 を返す):

- 種別 2 (USB Vbus 検出)
- 種別 21 (リセット GPIO) → §7.3 のフォールバック経路の根拠
- 種別 42 (auto_power) → §5.2 で重要
- 種別 43 (INIT スイッチ) → §5.3
- 種別 48 (MICON) → nas_feature の SUPPORT_MICON=0 と一致

### 4.2 proc エントリ ↔ 種別 ↔ GPIO ↔ 有効レベル 対応表

MPP 番号は Armada 370 ではグローバル GPIO 番号と同一番号体系 (gpio0 = MPP0–31 相当、gpio1 = 32–63、gpio2 = 64–65)。本カーネルが扱うのはグローバル GPP 番号のみで、MPP 機能割当テーブル (記述子 +0x30) は本解析では未解読 (§9)。

| proc エントリ | 種別 | GPIO (グローバル) | バンク/ビット | 有効レベル | 根拠 |
|---|---|---|---|---|---|
| `buffalo/gpio/switch/power` | 41 | **15** | gpio0_15 | **active-low** (読み "on" ⇔ 物理 LOW) | 極性初期値 bit15=1 + BuffaloPowerReadProc は Data-In 読み 1 で "on\n" |
| `buffalo/gpio/switch/auto_power` | 42 | **なし (−1)** | − | − (常時 "off\n") | 両テーブルに種別 42 が無く InRegBitTest(−1)=0 |
| `buffalo/gpio/switch/func` | 40 | **16** | gpio0_16 | **active-low** (読み "on" ⇔ 物理 LOW) | 極性初期値 bit16=1 + BuffaloFuncReadProc |
| `buffalo/gpio/switch/sw_control` | (41 を監視) | 15 (+42) | gpio0_15 | §5.2 | BuffaloSwPollingWriteProc / Check |
| `buffalo/power_sw` | 41 | 15 | gpio0_15 | 生レベルを "1\n"/"0\n" で返す | gpio_power_read_proc 0xc005d548 |
| `buffalo/gpio/power_control/hdd0` | 23 idx0 | **8** | gpio0_8 | **active-high** (Assert=駆動 1) | 極性 bit8=0 |
| `buffalo/gpio/power_control/hdd1` | 23 idx1 | 9 (ISMT) / 2 (JSMT) | gpio0_9 / gpio0_2 | active-high | 極性 0 |
| `buffalo/gpio/power_control/usb0` | 3 idx0 | **4** | gpio0_4 | **active-high** | 極性 bit4=0、初期 Data-Out=1 (ON) |
| `buffalo/gpio/fan/control` | 32 + 33 | **13 + 14** | gpio0_13 / gpio0_14 | §6 の真理表 | 極性 0 (Assert=1) |
| `buffalo/gpio/fan/lock` | 34 | **10** | gpio0_10 | 入力。読み 1 ⇔ "Stop\n" (ロック)、0 ⇔ "Fine\n" | BuffaloFanStatusReadProc、極性 0 なので物理 HIGH = ロック |
| `buffalo/gpio/hotplug/sata0` | 47 idx0 | **11** | gpio0_11 | 検出入力 (§8) | 極性 0 |
| `buffalo/gpio/hotplug/sata1` | 47 idx1 | 12 (JSMT のみ) | gpio0_12 | 同上 | ISMT ではエントリ自体が作られない |
| `buffalo/gpio/led/*` | 35,36,37,38 (他) | 59, 55, 57, 54 | gpio1_27, gpio1_23, gpio1_25, gpio1_22 | 極性 0 | 対象外のため詳細未追跡 |

GPIO IRQ 番号は `pin + 128` (この LSP の GPIO IRQ ベース): 電源 = 143、FUNCTION = 144、SATA0 = 139、SATA1 (JSMT) = 140。

### 4.3 各ハンドラの読み書き規約 (逆アセンブル確認済み)

- スイッチ読み (BuffaloPowerReadProc 0xc005c5a0 / BuffaloFuncReadProc 0xc005c3f8 / BuffaloAutoPowerReadProc 0xc005c510、3 者とも同構造): pin = PinNumGet(type, 0); `bfGppInRegBitTest(pin) != 0` → `"on\n"` (0xc04d412b)、`== 0` → `"off\n"` (0xc0499f98)。ピンが無い (−1) 場合は InRegBitTest が 0 を返すので "off\n"。
- `buffalo/power_sw` (gpio_power_read_proc 0xc005d548): pin < 0 なら空、else Data-In 読み 1 → `"1\n"` (0xc04bee25)、0 → `"0\n"` (0xc04a2d36)。後述の通り極性反転後の値なので、電源スイッチ ON (物理 LOW) で "1"。
- HDD/USB 書き込み (BuffaloHddWriteProc 0xc005c8f8 / BuffaloUsbWriteProc 0xc005c970): `strncmp(buf,"on",2)==0` → Assert(PinNumGet(23 or 3, ch))、`strncmp(buf,"off",3)==0` → Nagate。ch は proc の data (チャネル番号)。
- HDD/USB 読み: `bfGppOutRegBitTest` (Data-Out の生ビット、極性調整なし) で 1 → "on\n"、0 → "off\n"。書き込み (Assert=極性考慮) と読み (生) の非対称性からも、HDD/USB ピンの極性が 0 = active-high でなければ製品ファームとして自己矛盾することの傍証になる (初期値実測でも極性 0)。
- proc 生成 (buffaloGpioDriver_init 0xc052cd98): 静的テーブル 0xc05538d8 (24 バイトレコード {名前, dir フラグ, read, write, data, 種別 or −1} × 終端 NULL まで) を走査。HDD は `buffalo/gpio/power_control/hdd%d` (書式文字列 0xc0499cb9) を PinNumGet(23, idx) が −1 になるまで、USB は同 (種別 3、書式 0xc0499cda) 生成。fan/control は種別 32 と 33 の両方が引ける場合のみ生成。switch/power は「種別 48 (MICON) が無い」フラグ (0xc05527c0、ファイル初期値 1) が立っている場合にのみ単独生成される (LS210D はこちら)。

---

## 5. スイッチの詳細

### 5.1 電源スイッチは 3 位置スライド (OFF / ON / AUTO)

nas_feature: SUPPORT_SLIDE_POWER_SWITCH=on、SUPPORT_SHUTDOWN_DEPEND_ON_SW=1、POWER_SWITCH_TYPE=none。

### 5.2 BuffaloSwPollingCheck (0xc005c6a0) の真理表

sw_control に "on" を書くと 1 秒周期タイマ (jiffies + 1000) で BuffaloSwPollingCheck が回り、種別 41 (電源) と種別 42 (auto_power) の 2 ピンを 2 回サンプル (デバウンス) して状態を決め、変化時に buffalo_kernevnt_queuein でイベント文字列をキューする。"off" で del_timer。sw_control の読みは有効フラグ (0xc057bca8) を "on"/"off" で返す。initrd の `etc/init.d/pmcd.sh` が `echo on > /proc/buffalo/gpio/switch/sw_control` で有効化している。

MICON 無しフラグ (0xc05527c0 != 0、LS210D の経路) での状態判定:

| 種別 41 (GPIO15) 読み | 種別 42 読み | 状態 | イベント文字列 |
|---|---|---|---|
| 0 | 0 | 0 | "PSW_off" (0xc0499c57) |
| 1 | 0 | 1 | "PSW_on" (0xc0499c5f) |
| 0 | 1 | 2 | "PSW_auto" (0xc0499c66) |
| 1 | 1 | −1 | "PSW_unknown" (0xc0499c6f) |

**LS210D では種別 42 が存在しないため種別 42 の読みは常時 0** で、状態は GPIO15 のみで OFF (読み 0) / ON (読み 1) の 2 値になる。AUTO 位置はこのボードの GPP テーブルでは検出できない (AUTO 用接点が GPIO に割り当てられていない)。MICON 有りボードの経路 (フラグ==0) では種別 42 のみで状態 1/2 を決める。

### 5.3 割り込みと押下イベント

BuffaloCpuInterrupts_init (0xc052d18c): フラグ 0xc05527c0 == 0 (MICON 有り) の場合は電源スイッチブロック全体をスキップする。LS210D (フラグ=1) では以下が登録される:

- 種別 41 → proc `buffalo/PowerSWInt_en` (fops 0xc03d2eb8) を作成し、`request_threaded_irq(pin + 128, ..., handler=PwSwInterrupts 0xc005d7cc, "PowSw")`
- 種別 40 → FuncSwInterrupts 0xc005d6fc ("FuncSw")
- 種別 43 → InitSwInterrupts 0xc005d764 ("InitSw")。ただし種別 43 は両テーブルに無いため、この登録は実効を持たない見込み (ピン −1 の扱いは §9)。

IRQ トップハーフは対応する Polling ワーカーを threaded IRQ として起動するだけ:

| ワーカー | アドレス | デバウンス | 発行イベント |
|---|---|---|---|
| PollingPowerSWStatus | 0xc005d830 | 10 jiffies 周期で再サンプル、カウント > 9 で長押し確定 | "PSW_pushed" (0xc0499ef2) / "PSW_short_pushed" (0xc0499efd) |
| PollingFuncSWStatus | 0xc005d930 | カウント 10 | "FUNCSW_pushed" (0xc0499f2e) / "FUNCSW_long_pushed" (0xc0499f1b) |
| PollingINITSWStatus | 0xc005da04 | カウント 50 | "INITSW_pushed" (0xc0499f3c) |

PollingPowerSWStatus の詳細: Data-In 読みが 0 なら del_timer + enable_irq して終了 (離された)。読み 1 の間タイマを再装填 (+10 jiffies) し続け、初回サンプルで "PSW_short_pushed"、カウント > 9 (約 100ms 超) で "PSW_pushed" を 1 回キューする。押下判定は Data-In 読み 1 = 極性反転後レベルなので、GPIO15/16 では **物理 LOW = 押下/ON** で一貫する。

---

## 6. ファン制御の真理表

fan/control は 2 ピン (種別 32 = GPIO13、種別 33 = GPIO14) の組合せ。書き込みコマンドは 4 文字 strncmp で **"stop" / "slow" / "fast" / "full"** (0xc04c3097 / 0xc0499caf / 0xc0499cb4 / 0xc04a6879)。動作は ATAG 由来の `bfGetFanControlType()` (ビット 12–13) で分岐し、0 や 3 では書き込み no-op。

書き込み (Assert=1 / Nagate=0 として、極性 0 のため物理レベルと一致):

| コマンド | FanControlType==1 (32, 33) | FanControlType==2 (32, 33) |
|---|---|---|
| stop | Assert, Assert = (1,1) | Nagate, Nagate = (0,0) |
| slow | Nagate, Assert = (0,1) | Assert, Nagate = (1,0) |
| fast | Assert, Nagate = (1,0) | Nagate, Assert = (0,1) |
| full | Nagate, Nagate = (0,0) | Assert, Assert = (1,1) |

読み (BuffaloFanControlReadProc 0xc005d428、Data-In 読み A=GPIO13, B=GPIO14):

- FanControlType==0 → 常時 "stop\n"
- (A,B) = (0,0) → "stop\n" (0xc0499da6)
- (A,B) = (1,0) → "slow\n" (0xc0499dac)
- (A,B) = (0,1) → "fast\n" (0xc0499db2)
- (A,B) = (1,1) → "full\n" (0xc04b5cad)

つまり読み取り表は FanControlType==2 の書き込み表と一致し、Type==1 では書き込みレベルが読み取り表と反転している (Type 1 ボードでは外部回路側で反転しているか、読み側テーブルが Type 2 前提で作られているかはカーネルコードからは決着しない)。LS210D の U-Boot が渡す FanControlType の実値はカーネルイメージからは分からない (§9)。

なお LS210D 実機にファンは搭載されていない (プロジェクト側で確認済み)。ファン関係の proc が生成されるのは、ファームが LS200 シリーズ共通で GPP テーブルに種別 32/33/34 が存在するためであり、LS210D では実質未使用。

fan/lock (種別 34 = GPIO10、入力、極性 0): BuffaloFanStatusReadProc (0xc005d5e0) は Data-In 読み 1 → `"Stop\n"` (0xc0499db8)、0 → `"Fine\n"` (0xc0499dbe)、長さ 5 で返す。物理 HIGH = ロック (回転停止) 検出。

---

## 7. 電源オフ経路

### 7.1 pm_power_off は設定されない (no-op)

- `pm_power_off` は .bss の関数ポインタ変数 **0xc0579a50** (__ksymtab_pm_power_off @ 0xc04e74fc = {0xc0579a50, "pm_power_off"} で確定)。
- `machine_power_off` (0xc000f470): `pm_power_off != NULL` なら呼ぶ、NULL なら何もせず return。
- `kernel_power_off` (0xc006eef0): kernel_shutdown_prepare → pm_power_off_prepare (変数 0xc059d9b0、こちらも未設定) → syscore_shutdown → machine_power_off。
- **代入の不在の証拠**: アドレス 0xc0579a50 のバイト列はイメージ全体で 3 箇所にしか現れない — soft_restart のリテラルプール (0xc000f388、call_with_stack のスタックとして使用)、sys_reboot 領域のリテラルプール (0xc006f704)、__ksymtab のデータ (0xc04e74fc)。いずれも「関数ポインタを格納する」文脈ではない。rootfs / initrd のロード可能モジュール (.ko) にも `pm_power_off` への参照は無い (文字列 grep で 0 件)。
- 結論: **このカーネルでは `poweroff` (reboot システムコールの POWER_OFF) を実行しても machine_power_off は no-op で、物理電源は切れない。** カーネルはシャットダウン準備だけ行って戻る。

### 7.2 物理電源を切る唯一のカーネル内シーケンスは machine_halt

`machine_halt` (0xc000f428) の全動作:

```
mvEthPhyRegWrite(phy=0, reg=22, val=3)        @ Marvell PHY のページ 3 (LED ページ) を選択
mvEthPhyRegWrite(phy=0, reg=16, val=0x1880)   @ PHY LED 制御レジスタ
msleep(10)
str 0x61 -> [0xfbb18260]                       @ 物理 0xd0018260
str 0x01 -> [0xfbb18264]                       @ 物理 0xd0018264
b .                                            @ 無限ループ
```

PHY reg16 = 0x1880 は LED2 のフィールド (bits 11:8) = 8 = force ON を含む。88E1318 系 PHY では LED2 は INTn と共用ピンであり、mainline の `linkstation-poweroff.c` (work-kernel に同梱の v6.1 版 / master 版) が電源ラッチ制御として PHY INTn を強制するのと同族の手法。ただし公式カーネルの halt は mainline 版と完全には同じではなく、TCR (reg 18) への FORCE_INT 書き込みは行わない。加えてシステムレジスタ対 0x...260/264 への書き込み (§7.3) を伴う。

判定: 公式 FW の電源断は、カーネルの power_off 経路ではなく、**ユーザーランドが halt 系の終了に進み machine_halt の PHY + レジスタシーケンスで電源ラッチを落とす**か、**スライドスイッチ OFF 状態では SoC が halt で停止した時点で外部ラッチ側が電源を落とす** (SUPPORT_SHUTDOWN_DEPEND_ON_SW=1) 設計と読むのがコードと整合する。どちらの寄与が支配的かは回路情報が無いため断定しない (§9)。

### 7.3 レジスタ対 0xfbb18260 / 0xfbb18264 と BuffaloGpio_CpuReset

仮想 0xfbb18260 / 0xfbb18264 (物理 0xd0018260 / 0xd0018264) のレジスタ対は 3 箇所から触られる:

1. `BuffaloGpio_CpuReset` (0xc005b678): `[0x...260] |= 4`、`[0x...264] |= 1` して return。EXPORT_SYMBOL されているが、**カーネル内に呼び出し元は無い** (disasm-full.txt 全文 grep で BL 呼び出し 0 件)。モジュール向けに公開された SoC リセット用プリミティブで、このイメージでは未使用。
2. `machine_halt` (0xc000f428): 0x61 と 1 を書き込み (§7.2)。
3. `mvBoardReset` (0xc001ee08): リセット GPIO (種別 21) が引けるボードでは GPIO レジスタ側を操作し、**引けないボード (LS210D を含む) ではフォールバックとして `[0x...260] |= 1`、`[0x...264] |= 1`** を実行する。

mvBoardReset のフォールバックがこのレジスタ対であることから、これは SoC のシステムリセット制御レジスタ対と判断できる (Marvell のレジスタ名そのものはカーネル内に文字列が無く未確定、§9)。machine_restart は arm_pm_restart (初期値 0xc000f204) 経由でこのリセットに至る。

### 7.4 /proc/buffalo/cpu_status は「状態変数」であって電源操作ではない

- 状態は構造体 (ベース 0xc05539f8) の +0x54 フィールド (アドレス 0xc0553a4c) の単一整数。**.data 初期値は 67 = "hwpoff"** (毎ブートこの値から始まる)。
- BuffaloCpuStatusWriteProc (0xc005de08 / 0xc005df8c): 入力を最大 256 バイト取り、末尾改行を除去し、strcmp チェーンでコードに変換して **変数に格納するだけ。書き込みハンドラ内に電源操作は一切無い**。
- 書き込み文字列 → コード → 読み戻し文字列:

| 書き込み | コード | 読み戻し |
|---|---|---|
| "reboot" (0xc04a6756) | 24 | "reboot\n" |
| "swpoff" (0xc049a017) | 2 | "swpoff\n" |
| "hwpoff" (0xc049a010) | 67 | "hwpoff\n" |
| "ups_shutdown" (0xc049a037) | 33 | "ups_shutdown\n" |
| "reboot_uboot_passed" (0xc0499fef) | 58 | "reboot_uboot_passed\n" |
| "swpoff_uboot_passed" (0xc049a01e) | 92 | "swpoff_uboot_passed\n" |
| "fwup" (0xc049a032) | 111 | "fwup\n" |
| "normal_state" (0xc049a003) | 113 | "normal_state\n" |
| "WOLReady" (0xc049a044) | 117 | "WOLReady\n" |

未知の状態値は読みで `"Unknown(CpuStatus=%d)"` になる。

消費者はユーザーランドと U-Boot:

- initrd `/init` の CheckSleepFlag(): 起動時に cpu_status を読み、"swpoff" / "swpoff_uboot_passed" なら STOP_AT_INITRD="yes" として initrd 内のスリープモード (kernelmon / SleepCtrl) に留まる。
- `usr/local/sbin/miconapl-nomicon` (MICON 無し機の電源管理): boot_end → "normal_state"、shutdown_wait → "swpoff"、shutdown_ups_recover → "ups_shutdown"、reboot → "reboot" を書く。power_off コマンド自体は電源 LED 点滅のみ。
- `etc/init.d/standby.rcDown`: スタンバイ終了時に "swpoff" を書く (ups_shutdown 時を除く)。
- "_uboot_passed" 系の存在は、再起動を跨いだ状態伝達に U-Boot が関与することを示す。ただしこの変数自体は .data で毎ブート 67 に初期化されるため、**ブートを跨ぐ保持媒体はこの変数ではない** (保持経路の実体はカーネルイメージからは未確定、§9)。同一ブート内のスタンバイ復帰フローでは変数が保持される。

### 7.5 電源オフ経路の結論

1. 公式カーネルに pm_power_off の実体は無く、`poweroff` は物理電源を切らない。
2. 物理電源断のカーネル側プリミティブは machine_halt の「PHY LED ページ書き込み (LED2/INTn 強制) + システムリセットレジスタ対への書き込み + 無限ループ」のみ。
3. cpu_status は電源操作ではなく、initrd / U-Boot / ユーザーランド間の状態伝達変数。"swpoff を書いて再起動し、次段 (U-Boot + initrd) がそれを見て止まる/眠る" のが公式フロー。
4. BuffaloGpio_CpuReset は未使用の輸出シンボルで、リセットレジスタ対への OR 書き込みプリミティブ。
5. Debian 側で再現すべきは「GPIO ラッチで切る」ではなく、スイッチ状態の監視と、halt 相当の終了 + (必要なら) PHY INTn 強制という構成になる。

---

## 8. SATA hotplug

BuffaloSataHotplug_init (0xc005e538):

- `buffalo/gpio/hotplug` ディレクトリを作成し、チャネルごとに `request_threaded_irq(pin + 128, handler=SataHotplugInterrupts 0xc005e4c0)` と `buffalo/gpio/hotplug/sata%d` (create_proc_entry、読み = BuffaloSataHotplugReadProc) を作る。ポーリングタイマ (PollingSATAHotplug 0xc005e318) も併用。
- 検出ピンは種別 **47**: getSataHotplugDevId (0xc005e87c) = PinNumGet(47, devId)。ISMT370 では sata0 = GPIO11 のみ、JSMT370 では sata0 = GPIO11 / sata1 = GPIO12。
- initSataHotplug (0xc005e728) は極性レジスタ (0xfbb1810c / 0xfbb1814c) の初期値を BSS 構造体 (0xc057be84) に保存し、`"initial_polarity_val = 0x%08x\n"` (0xc049a24d) / `"initial_polarity_val_high = 0x%08x\n"` (0xc049a26c) を printk する。
- getSataHotplugStat (0xc005e814) は Data-In 生レベル + 極性ビット + SataHotDetectType (ATAG ビット 14–15) から接続状態を 1/2 で返す。読み proc は `"SATA %d plugged"` (0xc049a161) / `"SATA %d unplugged"` (0xc049a171) 系。resetSataHotplugDev は mvGppPolaritySet で極性を反転して両エッジ検出を再アームする。
- ユーザーランド側の実在確認: nasapi の `DISK_CONNECT_INFO = '/proc/buffalo/gpio/hotplug/sata{}'`、initrd の buffalo_rescue.sh が sata0 を読む。

---

## 9. SPI フラッシュ / MTD

### 9.1 構成要素

- modules.builtin (rootfs-1.84 `lib/modules/3.3.4/modules.builtin`、115 件) に `kernel/drivers/mtd/devices/m25p80.ko` (built-in) が含まれる。他に mtd コア、mtdchar、mtdblock、physmap、nand、ubi、jffs2 等。
- しかし実際に SPI フラッシュの MTD を提供するのは **Marvell LSP 独自の sflash ドライバ + flash_map_init** で、以下の証拠がある:
  - platform_driver「sflash」(ドライバ構造体 0xc056dfb4、probe = sflash_probe 0xc02dc924、remove = sflash_destroy 0xc02dc90c、driver.name = "sflash" @ 0xc04c8640)。
  - sflash_probe は mvSFlashInit (0xc00379fc) でチップを検出し (printk 書式 `"SPI Serial flash detected @ 0x%08x, %dKB (%dsec x %dKB)\n"` @ 0xc04c9177)、mtd_info を構築する (type=3 = MTD_NORFLASH、flags=0xc00)。**パーティション解析の呼び出しは probe 内に無い**。
  - `flash_map_init` (init セクション、0xc0539f6c 付近〜0xc053a240) が map エントリ (0x60 バイト構造) を走査し、ioremap → do_map_probe → **mtd_device_parse_register(mtd, types=NULL, origin=0, defs=NULL, def_nr=0)** を呼ぶ。map エントリの名前が **"spi_flash"** (文字列 0xc04c859a、flash_map_init のリテラルプール 0xc053a280 から参照)。
  - ボード初期化 axp_db_init.part.1 (0xc052bfe4) は SPI コントローラ用に mvSysSpiInit を 2 回 (アドレスウィンドウ 0x1000000 = 16MB) 呼ぶが、**m25p80 用の spi_board_info 登録は行わない**。m25p80 の probe 呼び出しは m25p80 ドライバ内部のもののみで、ボード側からのデバイス登録は確認できない。

### 9.2 パーティション定義の出所

**カーネル内固定テーブルは存在しない。** 根拠:

1. sflash_probe / flash_map_init のどちらにも mtd_partition 配列への参照が無い。flash_map_init の mtd_device_parse_register 呼び出しは defs=NULL、def_nr=0 (レジスタ r1/r2/[sp] がすべて r6=0 から設定されることを逆アセンブルで確認)。
2. mtd_device_parse_register (0xc02c2524) の意味論: types=NULL の場合はデフォルトパーサ群 (cmdlinepart 等) で解析し、見つからなければ add_mtd_device でデバイス全体を 1 MTD として登録する。
3. したがって SPI フラッシュのパーティションは **カーネルコマンドラインの `mtdparts=` でデバイス名 `spi_flash` を指定した場合にのみ分割され、それ以外は全体が単一 MTD** になる。

実機での裏付け (過去の実機調査): LS210D の /proc/mtd は mtd0 単一パーティション **`spi_flash`、サイズ 1MiB、erasesize 64KiB**。SPI ダンプも 1MiB (U-Boot + 環境 + 資格情報レコード等を含む)。

| MTD | 名前 | オフセット | サイズ | 備考 |
|---|---|---|---|---|
| mtd0 | spi_flash | 0x000000 | 0x100000 (1 MiB、チップ検出値依存) | 単一パーティション。内部の U-Boot / env / 各種レコードの配置はカーネルではなく U-Boot・工場レイアウト側の話 |

### 9.3 注意: armada-nand と mtdparts の混同

- axp_db_init.part.1 は platform_device **"armada-nand"** (構造体 0xc0550830) も登録する。orion_nfc_probe (0xc02dd6c8) は自前のデフォルト/プラットフォームデータで mtd_device_parse_register を呼ぶ。
- SPI ダンプ内の U-Boot デフォルト環境にある `mtdparts=mtdparts=armada-nand:8m(boot),8m(linux),-(rootfs)` は **この NAND デバイス向けの Marvell デフォルト値であり、SPI フラッシュのレイアウトではない**。LS210D は SPI ブート (mvCtrlIsBootFromSPI 0xc001d158 がボード判定に存在) で、NAND は未実装とみられる。
- U-Boot の bootcommon は `$mtdparts` を bootargs に含めるが、保存環境で確認できる mtdparts の値は上記 armada-nand 向けのみで、`spi_flash` 向けの指定は無い。よって公式 FW でも spi_flash は分割されない。

### 9.4 Debian 側への含意

Debian 6.1 で /dev/mtd0 に "spi_flash" 単一パーティションが出ない問題は、ドライバの自動ロード (spi-nor の modalias) 側の問題であり、パーティションテーブルをカーネルに足す必要はない。公式構成の再現は「SPI NOR 全体を 1 つの MTD として見せる」こと。

---

## 10. Debian DT 既知値との検証

| 項目 | Debian DT (検証機) | 公式カーネル実測 | 判定 |
|---|---|---|---|
| 電源スイッチ | gpio0_15, active-low | 種別 41 → GPIO15、極性 bit15=1、読み "on" ⇔ Data-In 1 ⇔ 物理 LOW | **一致** (番号・有効レベルとも) |
| FUNCTION ボタン | gpio0_16, active-low | 種別 40 → GPIO16、極性 bit16=1、読み "on" ⇔ 物理 LOW | **一致** |
| HDD 電源 regulator | gpio0_8 | 種別 23 idx0 → GPIO8、極性 0 = active-high、起動時 Data-Out=1 (ON) | **一致** |
| LED | gpio0_7、gpio1_22/23/25/27 (=54/55/57/59) | 種別 38/36/37/35 → GPIO54/55/57/59 (gpio1 側は一致)。gpio0_7 に対応する種別は GPP テーブルに見当たらず (LED 詳細は対象外として未追跡) | gpio1 側は **一致**。gpio0_7 は未確認 (§9) |

active-low の根拠について補足: Buffalo の読みハンドラは Data-In レジスタ値をそのまま "on" と解釈するが、GPIO15/16 は極性レジスタ初期値が 1 であり、Armada 370 では極性ビットが入力読み値をハードウェア反転させる。したがって「読み 1 = on」は物理 LOW と等価であり、DT の active-low 宣言と矛盾しない。**DT 側の active-low は正しい。**

---

## 11. 未確定事項

1. **ISMT370 / JSMT370 のどちらが LS210D か**: ボード ID は U-Boot が ATAG で渡す実行時値で、イメージからは決まらない。相違点は HDD1 (GPIO9 vs GPIO2) と SATA hotplug ch1 (無し vs GPIO12) のみ。判別方法: 公式 FW 起動時に (a) `/proc/buffalo/gpio/power_control/hdd1` と `/proc/buffalo/gpio/hotplug/sata1` の有無、(b) dmesg の "initial_polarity_val" 行やボード表示、(c) U-Boot が構築する ATAG ワードの実測。
2. **レジスタ対 0xd0018260 / 0xd0018264 の Marvell 公式レジスタ名**: mvBoardReset のフォールバック先であることからシステムリセット制御であることはコード上確実だが、名称を特定する文字列はカーネル内に無い。
3. **machine_halt の PHY 書き込みと電源ラッチの関係**: LED2/INTn 共用ピンの強制が電源断の主因か、0x...260/264 への書き込みが主因か、スライドスイッチ連動の外部ラッチかは、回路情報なしには切り分けられない。mainline linkstation-poweroff との差異 (TCR reg18 を触らない) も含め、実機実験での検証が必要。
4. **cpu_status のブート跨ぎ保持経路**: "_uboot_passed" 状態の存在から U-Boot の関与は確実だが、保持媒体 (保護 RAM 領域 / SPI 環境 / その他) はカーネルイメージからは特定できなかった。
5. **FanControlType の LS210D 実値** (ATAG ビット 12–13): U-Boot 依存。ファン自体が無い機種のため実害はない。
6. **種別 43 (INIT スイッチ) の IRQ 登録の扱い**: PinNumGet(43) = −1 のとき BuffaloCpuInterrupts_init が request_threaded_irq(127, ...) を試みるのか、事前チェックで弾くのか、関数の該当分岐を完全には追い切っていない。いずれにせよ実効のある INIT スイッチ入力は LS210D に存在しない。
7. **MPP 機能割当テーブル** (ボード記述子 +0x30 の配列): 未解読。GPIO 番号との対応付けには不要だったが、Debian DT の pinctrl 設定を公式と完全一致させたい場合は追加解析が要る。
8. **LED の gpio0_7**: Debian DT にある gpio0_7 の LED が公式 GPP テーブルのどの種別に対応するか未確認 (LED は本タスク対象外。AllLedOn/Off が使う種別 35/36/37/38 は gpio1 側のみだった)。
9. **SataHotDetectType の LS210D 実値** (ATAG ビット 14–15): getSataHotplugStat の plugged/unplugged 判定の向きに影響する。U-Boot 依存の実行時値。

---

## 12. まとめ (Debian 側実装への直接の答え)

- 電源スイッチ = **GPIO15 (gpio0_15)、active-low**。FUNCTION = **GPIO16 (gpio0_16)、active-low**。DT 既知値は正しい。
- スライドスイッチの AUTO 位置は独立 GPIO を持たない (種別 42 は未配線)。Debian 側で検出できるのは ON/OFF の 2 状態のみ。
- 押下イベント相当: 公式は GPIO IRQ (pin+128) + 10 jiffies デバウンスで PSW_pushed / PSW_short_pushed / FUNCSW_pushed / FUNCSW_long_pushed を発行する。gpio-keys + ユーザーランド監視で等価に再現できる。
- HDD 電源: ch0 = GPIO8、ch1 = GPIO9 (ISMT) または GPIO2 (JSMT)、いずれも active-high、起動時 ON。USB 電源 = GPIO4、active-high。
- 電源オフ: 公式カーネルに pm_power_off は無い。物理断は machine_halt の PHY INTn 系シーケンス + リセットレジスタ書き込み + スピン (と、スライドスイッチ連動ラッチ) に依存する。Debian 側の `shutdown` が再起動してしまう挙動は、poweroff 先が restart になっている構成側の問題であり、GPIO ラッチで切る設計は公式にも存在しない。
- SPI: 公式は Marvell sflash ドライバで全体を単一 MTD "spi_flash" として見せる。固定パーティションテーブルは無い (cmdline mtdparts のみ)。Debian 側は spi-nor を正しくロードできれば公式と等価になる。
