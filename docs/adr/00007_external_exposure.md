---
id: "ADR-00007"
title: "外部公開設定: Tailscale Serve + Funnel 不使用 + tag:taskhub-ci grants 最小化"
status: "accepted"
date: "2026-05-07"
authors:
  - "t-ohga"
related_sprints:
  - "SP-000_bootstrap"
  - "SP-012_p0_acceptance"
supersedes: null
superseded_by: null
accepted_at: "2026-05-18T09:10:00Z"
acceptance_history:
  - "2026-05-07: proposed (SP-000_bootstrap で起票)"
  - "2026-05-18: accepted (SP-012 で host-portable invariant 整合 + Tailscale Serve / Funnel 不使用 / tag:taskhub-ci grants 最小化を Sprint 12 batch 7 taskhub admin CLI で参照、Codex PR #67 F-PR67-002 P1 adopt + .claude/rules/sprint-pack-adr-gate.md §12 invariant 整合、ADR-00021 同時 accepted)"
---

最終更新: 2026-05-18 (Sprint 12 で proposed → accepted 昇格)

## 背景

- 決定対象: P0 の network exposure、Tailscale Serve、Funnel 不使用、machine naming、grants、private staging CI/E2E の方針。
- 関連 Sprint: SP-000_bootstrap
- 前提 / 制約: P0 は個人専用、単一 VPS、Tailscale 閉域運用とする。public ingress、Funnel、Cloudflare 経由公開は ADR Gate 対象。ADR Gate Criteria #7（外部公開設定）に該当する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: Tailscale Serve + Funnel 不使用 | tailnet 内 HTTPS のみ公開し、中立 machine 命名と grants 2 系統に限定する | P0 の閉域要件に合い、public bind と意図しない公開を避けやすい | Tailscale 設定ミス、CT log 経由の名前露出、CI key 運用に注意 |
| B: Tailscale Funnel | tailnet 外からも到達可能にする | 端末制約が少ない | public ingress になり、ホスト名露出と攻撃面増加が P0 方針に反する |
| C: Cloudflare Tunnel | public tunnel 経由で app に到達する | 商用化時の公開経路として検討しやすい | P0 では追加 IdP / WAF / DNS / incident response が過大 |

## 採用案

- 採用: A: Tailscale Serve + Funnel 不使用 + 中立 machine 命名 + grants 2 系統のみ
- 理由: P0 の個人利用では tailnet 内 TCP/443 のみで足りる。public ingress を持たず、外部公開変更は ADR で止める。
- 実装 Sprint: SP-000_bootstrap で方針固定、private staging 本運用は Sprint 11.5 へ defer
- 実装対象ファイル:
  - `config/tailscale/`
  - `scripts/deploy/`
  - `config/loki/`
- 実装ガイダンス:
  - machine naming は `app-<env>-<role>-<NN>` に固定し、顧客名、個人名、repo 名、機密 project 名、用途が推測できる語を禁止する。
  - grants は 2 系統のみ許可する: 人間 identity -> `tag:taskhub` TCP/443、`tag:taskhub-ci` -> `tag:taskhub` TCP/443。その他の src / dst / protocol は deny とする。
  - `tagOwners.tag:taskhub-ci` を明示し、CI は ephemeral auth key 必須、reusable key 禁止、job 終了後 cleanup を前提にする。
  - CI 用 auth key は `secret_ref` 管理とし、Loki / CI log では token、key、tailnet DNS を mask する。
  - Docker service は public interface に bind せず、backend / frontend は `127.0.0.1` または Docker internal network へ閉じる。
  - **Tailscale device approval を必須有効化**: 新規 device は手動承認なしには tailnet 参加不可。device approval 無効化は ADR Gate 対象 (#7 外部公開設定) として通常 deny。`autoApprovers` を使う場合は scope を `tag:taskhub-ci` の ephemeral key 経路のみに限定し、承認待ち device の到達は完全 deny。
- テスト指針:
  - smoke: `ss -lntp` で `0.0.0.0:3000` / `0.0.0.0:8000` がないことを確認する。
  - smoke: `docker ps` の ports が `127.0.0.1` bind であることを確認する。
  - grants 越境 negative: 許可 2 系統以外の src / dst / protocol から TCP/443 へ到達できない。
  - Funnel negative: Funnel が設定されていないこと、public IP から app port へ接続できないことを確認する。
  - **device approval negative**: 未承認 device から tailnet に join 試行 → 到達不可、承認待ち status であることを確認する (`tailscale status` / Tailscale admin console)。
  - **device approval positive**: 承認済み device のみが `tag:taskhub` へ TCP/443 で到達できる。

## 却下案

- B: Tailscale Funnel: public ingress となり、CT log や公開経路の監視、incident response が必要になるため P0 では却下する。
- C: Cloudflare Tunnel: P1 以降の商用化または Tailscale 不可端末対応として再評価する。P0 では閉域の単純さを優先する。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| grants 設定ミスで過剰到達を許す | grants negative test、tailnet ACL review | 2 系統のみを config 化し、差分 review で追加経路を reject |
| machine / tailnet DNS が CT log や screenshot に残る | docs / CI log / screenshot review | `app-<env>-<role>-<NN>` 命名、redaction、log mask を必須化 |
| CI auth key が漏えいする | Loki / CI log scan、secret canary | ephemeral key、reusable key 禁止、SOPS + SecretBroker 経由の短命注入 |
| Docker が public bind する | `ss -lntp` / `docker ps` smoke | compose / deployment script で `127.0.0.1` bind を固定 |

## rollback 手順

### 経路を戻す (到達制御の rollback)

1. 意図しない公開、Funnel 有効化、grants 越境、CI key 漏えい疑い、未承認 device の tailnet 参加を検知したら、Tailscale Serve / CI 接続を停止し、該当 auth key と未承認 / 不正 device を revoke する。
2. grants を人間 identity -> `tag:taskhub` TCP/443 のみ、または一時的に全 deny へ戻す。Docker ports は `127.0.0.1` bind に戻し、Funnel 設定がないこと、device approval が enabled であることを確認する。
3. `ss -lntp`、`docker ps`、tailnet 内外の到達確認、Loki / CI log mask、`tailscale status` の device 一覧を再検証し、許可された 2 系統 + 承認済み device 以外から到達できないことを確認する。

### 識別子漏えい後の対応 (CT log / 公開ログの不可逆性対策)

CT log や screenshot / docs / CI log に非中立 machine 名 / tailnet DNS が出てしまった場合:

4. 該当 device を decommission し、新しい中立名 (`app-<env>-<role>-<NN>` 系列の次番号) で再構築する。Tailscale HTTPS 証明書も再発行する (旧名は CT log に永続するが、新名へ移行することで継続利用面の露出を止める)。
5. docs / screenshot / CI log / Loki の該当箇所を redaction する。git history に残る場合は filter-branch / BFG / 注記コミットで対応 (CT log は不可逆なため記録のみ)。
6. **CT log の不可逆性は残留リスクとして記録**し、本 ADR のリスク表 / Sprint Review に追記する。命名 gate (PR review で `app-<env>-<role>-<NN>` 形式以外を BLOCK) を再強化する。
7. 同種の漏えいが繰り返される場合は ADR-00007 自体を見直し、Tailscale HTTPS の代替 (private CA など) を別 ADR で検討する。

---

## Host-Portable Deployment update (2026-05-10、ADR-00021 連動)

ADR-00021 (Host-Portable Deployment + Data Migration) accepted 化に伴い、本 ADR の **Tailscale 閉域維持 invariant が host を変えても不変** であることを明示化:

### host 中立 invariant (ADR-00021 §6 と同期)

TaskManagedAI の backend host が Mac / Linux / VPS いずれであっても、以下 invariant は **絶対不変**:

| invariant | 強制 |
|---|---|
| 公開 IP からの 22/80/443 deny | UFW (Linux/VPS) / pf (Mac) で deny rule、host 設定の SOP 化 |
| Funnel 不使用 | Tailscale Serve のみ、`tailscale serve --funnel` 禁止 |
| 127.0.0.1 bind | docker-compose.yml で全 service の host port を 127.0.0.1 固定 |
| Tailscale device approval 必須 | tailnet 管理画面で device 承認 + tag:taskhub grants |
| grants minimum | `tag:taskhub`, `tag:taskhub-ci`, `tag:taskhub-cli` (P0.1 SP-016 で追加) のみ |
| Cloudflare / 他公開経路の deny | 同 |

### host 別の追加考慮 (Mac / Linux laptop の sleep 対策)

| host | 公開 IP block 手段 | sleep / shutdown 対策 |
|---|---|---|
| Mac | macOS pf (Packet Filter) で 22/80/443 incoming deny + Tailscale 経由のみ | `caffeinate -i docker compose ...` または `pmset -a sleep 0 disablesleep 1` (電源接続中) |
| Linux (laptop) | UFW deny | `systemd-inhibit` または `systemctl mask sleep.target suspend.target` |
| Linux (desktop / 24/7) | UFW deny | (常時稼働、対策不要) |
| VPS | UFW deny + プロバイダ console で raw IP block 確認 | (常時稼働) |

### host 切替時の Tailscale Serve URL drift

- host が変われば Tailscale Serve URL も変わる (例: `taskhub.t-ohga-mac.tail-xxxxx.ts.net` → `taskhub.t-ohga-vps.tail-xxxxx.ts.net`)
- 全機械の `tm` CLI profile を `tm auth login --backend <new-url>` で再 issue
- ADR-00015 で短命 capability token (TTL 5-30 分) を採用しているため、host 切替の影響軽微 (再 login で済む)

### 関連 ADR

- ADR-00021 (Host-Portable Deployment + Data Migration)
- ADR-00006 update (age key 運搬、ADR-00021 §5 で詳細化)
- ADR-00015 (UI/CLI Parity、`tm auth login --backend` で host 切替対応)

