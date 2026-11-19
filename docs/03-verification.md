# 実機検証手順

前提: 対象機が起動済みで、電源スイッチと FUNCTION ボタンに手が届く状態。
作業はこのリポジトリのクローンがある計算機から行う。
以下のコマンド例では対象機への SSH 接続先を `ls210d` と表記する。自分の環境のホスト名または IP アドレスに読み替えること。

## 1. 入力イベントの実押し確認

```sh
scp tools/probe.sh ls210d:/tmp/
ssh ls210d 'sudo sh /tmp/probe.sh --events'
```

最後の10秒間で以下を行い、イベント行が出ることを確認する:

- FUNCTION 短押し → コード 357 の押下/解放
- FUNCTION 長押し (3秒以上)
- 電源スイッチ OFF → ON → コード 1 の値変化
  (デーモン未導入の段階では OFF にしても落ちないので安全に試せる)

## 2. SPI/MTD の恒常化確認

```sh
# install.sh が /etc/modules-load.d/ls210d-spi-nor.conf を配置する (手順4と同時でも可)
ssh ls210d 'sudo reboot'
ssh ls210d 'cat /proc/mtd; ls /dev/mtd*'
```

期待: 起動直後から mtd0 (u-boot) / mtd1 (u-boot-env) が存在する。
読み取り確認 (書き込みはしない):

```sh
ssh ls210d 'sudo fw_printenv BOOTVER'   # /etc/fw_env.config 配置後
```

## 3. デーモンの試運転 (poweroff は実行されない)

```sh
./install.sh --dry-run-daemon
ssh ls210d 'journalctl -fu ls210d-gpiod'
```

別ターミナルで journal を見ながら:

- FUNCTION 短押し → `function hook (short)` のログ
- FUNCTION 長押し → `function hook (long)` のログ
- 電源スイッチ OFF → 「poweroff scheduled」のログ、grace 内に ON へ戻すと
  「cancelled」のログ (実際に落ちないこと)
- 電源スイッチ OFF のまま → grace 経過後に「would run: systemctl poweroff」の
  ログのみで、落ちないこと

## 4. 本導入と最終確認

```sh
./install.sh
ssh ls210d 'systemctl status ls210d-gpiod'
```

- 電源スイッチ OFF → 正常にシャットダウンし、落ちたままになること
- 電源スイッチ ON → 起動すること
- FUNCTION フック (実フックを置いた場合) が動くこと

## 切り戻し

```sh
ssh ls210d 'sudo systemctl disable --now ls210d-gpiod; \
  sudo rm -f /etc/modules-load.d/ls210d-spi-nor.conf \
             /etc/systemd/system/ls210d-gpiod.service; \
  sudo rm -rf /etc/ls210d-driver /usr/local/sbin/ls210d-gpiod.py; \
  sudo systemctl daemon-reload'
```

## DTS ビルド確認 (参考、実施済み 2026-11-17)

`dts/armada-370-linkstation-ls210d.dts` はカーネル v6.1 の
armada-370.dtsi 等を使って dtc 1.7.0 でビルドできることを確認済み。
出荷 DTB との逆コンパイル diff は無関係な2点のみ
(パーティションノード名の表記、PCIe assigned-addresses の値)。
GPIO/SPI 関連は完全一致。


## 実施記録

### 2026-11-17: 手順1 (入力イベント実押し) 完了

tools/evwatch.py で取得 (対象機の /tmp/ls210d-events.log と一致):

```
 6.713s  FUNCTION pressed
 7.108s  FUNCTION released     (短押し 0.40 秒)
 8.836s  FUNCTION pressed
10.838s  FUNCTION released     (長押し 2.00 秒)
15.137s  POWER-SWITCH -> OFF
16.734s  POWER-SWITCH -> ON
18.280s  POWER-SWITCH -> OFF
20.169s  POWER-SWITCH -> ON
```

- FUNCTION の短押し/長押し、電源スイッチ OFF/ON ×2、すべて想定通りの
  コードと値で受信できた。
- 実測の「自然な長押し」が 2.0 秒だったため、デーモンの長押し判定の
  既定値を 3 秒 → 2 秒へ変更した。


### 2026-11-17: journalctl に何も出ない件

対象機では **systemd-journald 自体が inactive** (低スペック機のため
不要サービスは止める運用で意図的に停止されている。
本プロジェクト起因ではない)。そのため journalctl では
デーモンのログが見えない。対策として ls210d-gpiod.service は
/var/log/ls210d-gpiod.log へもログを出すよう変更した
(`StandardOutput=append:`)。確認は `tail -f /var/log/ls210d-gpiod.log` で行う。

### 2026-11-17: 手順3 (デーモン試運転 / dry-run) 完了

/var/log/ls210d-gpiod.log の実測:

- 起動時: watching event0、初期状態 = 電源 ON
- FUNCTION 押下 ×2 → フック未配置のため skip のログ (想定通り)
- 電源 OFF → poweroff 予約 → ON に戻してキャンセル
- 電源 OFF のまま → grace 経過後に「dry-run, would execute: systemctl
  poweroff」、実際には落ちない

全パターン想定通り。残るは本導入 (dry_run 解除) と再起動での
MTD 恒常化確認、実スイッチ OFF での最終確認。


### 2026-11-17: 手順2・4 (MTD 恒常化 + 本導入 + 実スイッチ最終確認) 完了

- dry_run を解除して本導入し、再起動後に確認:
  起動直後から mtd0/mtd1・mtdblock0/1 が存在し、ls210d-gpiod も
  enabled/active で自動起動 (dry_run=False)。
- 実スイッチでの最終確認 (デーモンログより):
  「power switch OFF detected」→「executing: systemctl poweroff」で
  正常にシャットダウンして落ちたままになり、スイッチ ON で再起動、
  デーモンと MTD が揃った状態で復帰した。

以上で当初の課題はすべて実機で解決を確認:
電源スイッチ OFF で正常終了、FUNCTION ボタンの短押し/長押しフック、
/dev/mtd の恒常的な出現。
