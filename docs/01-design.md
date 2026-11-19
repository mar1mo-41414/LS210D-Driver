# 設計 (LS210D-Driver)

調査結果は `docs/00-findings.md` を参照。

## 基本方針

カーネル側の部品は Debian 6.1 (armmp) にほぼ揃っているのに「配線」だけが欠けている、
というのが現状の本質。なので新規カーネルドライバを書く前に、既存部品の配線を直し、
足りない部分だけを小さく作る。

| 症状 | 本質 | 対処 |
|---|---|---|
| 電源スイッチ OFF で落ちない | gpio-keys の入力イベントを受けるユーザーランドが無い (公式 FW では kernelmon が担当) | 監視デーモン `ls210d-gpiod` を作る |
| FUNCTION が効かない | 同上 (公式では kernelmon → libfuncsw が DirectCopy 等を実行) | 同デーモンがフックスクリプトを呼ぶ形で実装 |
| shutdown で再起動する | DT の `restart-poweroff` により poweroff = 再起動 + U-Boot 保持が設計。スイッチ ON では U-Boot が起動し直す | 仕様として明記。スイッチ OFF と連動した poweroff で「切れる」状態にする |
| /dev/mtd が無い | spi-nor モジュールが modalias 不一致で自動ロードされない (DT 定義は既にある) | modules-load.d で明示ロードする設定を配布 |

## 1. ls210d-gpiod (daemon/)

- Python 3 標準ライブラリのみ。evdev (`/dev/input/event*` のうち name が `gpio-keys`) を読む。
  公式 FW の「kernevnt → kernelmon」の mainline における等価物がこの形。
- 電源スイッチ (code 1、active-low):
  - 押下 (value=1) = スイッチ ON 側、解放 (value=0) = OFF 側。
  - OFF を検出したら猶予 (既定 3 秒) を置き、戻らなければ `systemctl poweroff` を実行。
    猶予内に戻せばキャンセル (誤操作・カチャつき対策)。
  - 起動時に EVIOCGKEY で現在状態を読み、OFF のまま起動した場合はログだけ出す
    (起動直後に即シャットダウンはしない。U-Boot 側の保持と役割が被るため)。
- FUNCTION ボタン (code 357):
  - 短押しで `/etc/ls210d-driver/function-hook.sh` があれば実行 (無ければログのみ)。
    公式 FW の DirectCopy 相当をやりたい場合は利用者がここに処理を書く。
  - 長押し (既定 3 秒) は別フック `function-hook-long.sh` (任意)。
- 設定は `/etc/ls210d-driver/ls210d-gpiod.conf` (key=value)。コード値も変更可能にし、
  DT を差し替えても追従できるようにする。
- systemd unit `ls210d-gpiod.service` で常駐 (root 実行。/dev/input/event0 は root:input 660、
  gpiochip も root 専用のため root 前提)。

## 2. SPI / MTD (spi/)

- `/etc/modules-load.d/ls210d-spi-nor.conf` に `spi-nor` と `mtdblock` を列挙し、
  起動時にロードして `/dev/mtd0` (u-boot) / `/dev/mtd1` (u-boot-env) を出現させる。
- `fw_env.config` の例を同梱 (fw_printenv 用)。DT のパーティションは両方 read-only のため、
  書き込みが必要な場合は DT 側の read-only 解除が別途必要 (dts/ で管理、既定では行わない)。

## 3. DTS (dts/)

- 現行コミュニティ DTS (Debian_on_Buffalo の Bookworm 版、検証機の DTB と
  ハッシュ一致確認済み) を `dts/` に複写して正本とし、改訂はここから行う。
- AUTO 位置については公式カーネル解析で「GPIO 割り当てなし (未配線)」と確定したため、
  DTS への auto-power 追加は行わない。スイッチは ON/OFF の2状態として扱う。
  (公式の pwrmgr 相当の自動スタンバイは、検出手段自体が無いので対象外)

## 対象外

- LED (Debian 側で動作済み)。
- ファン制御 (LS210D にはファン自体が存在しないため対象外。公式カーネルの fan 系
  proc エントリはシリーズ共通コードのもの)。
- HDD 電源レギュレータ (always-on で実用上問題なし)。
