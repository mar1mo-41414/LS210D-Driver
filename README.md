# LS210D-Driver

> **対象者**: [Debian_on_Buffalo](https://github.com/1000001101000/Debian_on_Buffalo) で Debian 化した Buffalo LinkStation LS210D を使っている人向けのリポジトリです。
> Debian 化そのものの手順は Debian_on_Buffalo を参照してください。

Buffalo LinkStation LS210D (Armada 370) を Debian 化した個体で、公式 FW では
動いていたのに Debian では機能していないハードウェア機能を復活させるための一式。

対象 (LED は Debian 側で動作済みのため対象外):

| 機能 | 状態 |
|---|---|
| 電源スライドスイッチ OFF でシャットダウン | デーモンで実装 (`daemon/`)、実機検証済み (2026-11-17) |
| FUNCTION ボタン | デーモン + フックで実装 (`daemon/`)、実機検証済み (2026-11-17) |
| SPI フラッシュ (`/dev/mtd*`) | モジュールロード設定で対応 (`spi/`)、再起動後の恒常化まで実機検証済み |
| `shutdown` で再起動してしまう挙動 | DT の restart-poweroff による設計上の動作。スイッチ OFF 連動で電源断になる (下記)。スイッチ OFF で正常に落ちることは実機検証済み |

## なぜそうなるか (要点)

- スイッチ類はカーネルの gpio-keys が入力イベントとして既に出している
  (電源 = gpio0_15 / code 1、FUNCTION = gpio0_16 / code 357)。
  公式 FW の kernelmon に相当する「イベントを受けて動くユーザーランド」が
  Debian には無いので、監視デーモン `ls210d-gpiod` を用意した。
- 電源オフの実体は DT の `restart-poweroff` ドライバで、「再起動して U-Boot に
  保持させる」方式。スイッチ ON のまま `shutdown` すると U-Boot が起動し直すため
  再起動に見える。スイッチ OFF を検出して poweroff する上記デーモンと組み合わせると、
  スイッチ OFF → poweroff → U-Boot が保持 → 電源断、の流れになる。
- SPI フラッシュは DT に定義済みだが、spi-nor モジュールが modalias 不一致で
  自動ロードされず MTD が出ていなかった。modules-load.d で明示ロードする。

詳細な調査結果は `docs/00-findings.md`、方式の選定理由は `docs/01-design.md`。

## 導入 (LS210D 本体上で)

事前確認 (モジュール手動ロードで MTD が出るか、イベントが届くか):

```sh
sudo sh tools/probe.sh
```

導入:

```sh
sudo ./install.sh                # 通常導入
sudo ./install.sh --dry-run-daemon   # デーモンだけ試運転 (poweroff しない)
```

FUNCTION ボタンの動作は `/etc/ls210d-driver/function-hook.sh` (短押し) と
`function-hook-long.sh` (長押し) に書く。例が `daemon/function-hook.sh.example`。

## 構成

- `daemon/` — ls210d-gpiod 本体 (Python 標準ライブラリのみ)、systemd unit、設定例
- `spi/` — modules-load.d 設定、fw_env.config 例
- `dts/` — Debian_on_Buffalo の DTS ソース (現行 DTB と一致) と今後の改訂置き場
- `docs/` — 調査結果と設計
- `tools/` — 実機診断スクリプト
- `SampleData/` — 公式 FW の解析資料 (git 管理外)

## ライセンス

MIT License (`LICENSE` 参照)。
