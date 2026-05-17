# Tailscale Private Staging - admin manual setup (Sprint 11.5 batch 2 BL-0136)

本 doc は `.github/workflows/private-staging-e2e.yml` (Sprint 11.5 batch 2) が依存する
**admin 手動 setup** を記録する. 本 batch 内では workflow scaffold + smoke test
までを完成、actual production deploy verify は Sprint 12 host migration drill で final.

## Pre-requisites

| 項目 | 状態 |
|---|---|
| Tailscale account | 既存 (tailnet `t-ohga.github.io`) |
| Production VPS (Hostinger) | 既存 (`t-ohga-vps`、Tailscale IP `100.115.27.116`) |
| GitHub repo | 既存 (`t-ohga/TaskManagedAI`) |

## Step 1: Tailscale OAuth client 作成

1. Tailscale admin console (`https://login.tailscale.com/admin/settings/oauth`) を開く
2. "Generate OAuth client..." を click
3. **Description**: `taskmanagedai-github-actions`
4. **Scopes**:
   - `Devices` → `Write` (auth key 発行のため、これ以外不要)
5. **Tags**: `tag:taskhub-ci` を assign (next step で ACL に登録予定)
6. 生成された `Client ID` + `Client Secret` を **secure 場所に一時保存** (再表示不可)

## Step 2: Tailscale ACL 設定 (`tailscale.json` policy)

Tailscale admin console (`https://login.tailscale.com/admin/acls/file`) で
ACL JSON file を編集.

```hujson
{
  "tagOwners": {
    "tag:taskhub": ["autogroup:admin"],
    "tag:taskhub-ci": ["autogroup:admin"]
  },
  "acls": [
    // Existing tag:taskhub (production VPS access) ...

    // Sprint 11.5 batch 2 (BL-0136): tag:taskhub-ci → tag:taskhub の TCP/443 only.
    // ephemeral CI agent から VPS への scrape / smoke 限定 path.
    {
      "action": "accept",
      "src":    ["tag:taskhub-ci"],
      "dst":    ["tag:taskhub:443"]
    }
  ]
}
```

**重要**:
- `tag:taskhub-ci` は **TCP/443 のみ** (Pack §設計判断 line 105 整合)
- `tag:taskhub` (production VPS) には影響なし (既存 grants 不変)
- ACL 保存後、5 sec 程度で propagate (live test possible)

## Step 3: GitHub Actions secrets 登録

```bash
# Local machine から (gh CLI):
gh secret set TS_OAUTH_CLIENT_ID --repo t-ohga/TaskManagedAI --body "<step 1 で取得した Client ID>"
gh secret set TS_OAUTH_SECRET --repo t-ohga/TaskManagedAI --body "<step 1 で取得した Client Secret>"
gh secret set STAGING_API_URL --repo t-ohga/TaskManagedAI --body "https://t-ohga-vps:443"
```

GitHub UI からも設定可能 (`Settings → Secrets and variables → Actions → New repository secret`).

## Step 4: VPS 側 TLS 443 listener 設定 (Sprint 12 で完成)

本 batch (Sprint 11.5 batch 2) では VPS 側の **TLS 443 listener** は未配備.
`docker-compose.yml` の `api` service は `127.0.0.1:8000` bind、Tailscale tag:taskhub-ci
からは到達できない (port mismatch).

Sprint 12 host migration drill (BL-host-migration-drill) で以下を完成:
1. VPS に Caddy/Nginx reverse proxy 配置
2. Tailscale `https://` MagicDNS で 443/TCP を api:8000 に proxy
3. Tailscale 自動 TLS (`tailscale serve`) で cert 取得

## Step 5: 動作 verify

```bash
# GitHub Actions workflow を manual trigger (smoke_only=true で安全試験)
gh workflow run "Private Staging E2E" --ref main --field smoke_only=true

# 実行結果確認
gh run watch
```

## CRITICAL invariant trace

- **deny-by-default**: tag:taskhub-ci は TCP/443 のみ allow (他 port deny)
- **SecretBroker boundary**: OAuth client → ephemeral auth key auto-generate (long-lived secret なし)
- **ADR Gate Criteria**:
  - #6 Secrets: OAuth client credential は ADR-00006 既 accepted scope 内
  - #7 外部公開設定: Tailscale 経由のみ、外部 ingress 不使用 (ADR-00007 既 accepted)
- **AC-HARD-02 secret_canary_no_leak**:
  - workflow yaml で `::add-mask::` 経由で secrets を log shipping から守る
  - Loki shipping 経路 (Sprint 11.5 batch 1 確立) は `_payload_secret_scan` で
    raw secret reject

## Rollback

1. GitHub Actions secrets 削除: `gh secret delete TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET / STAGING_API_URL`
2. Tailscale OAuth client 削除: admin console から
3. Tailscale ACL から `tag:taskhub-ci` 関連 entry 削除
4. workflow file 削除: `.github/workflows/private-staging-e2e.yml`

## 関連 Sprint Pack

- Sprint 11.5 batch 2 (本 BL-0136): scaffold + workflow_dispatch smoke
- Sprint 12 BL-host-migration-drill: actual deploy verify + TLS 443 listener + E2E full suite

## 関連 ADR

- ADR-00007 (External exposure、既 accepted): Tailscale `tag:taskhub-ci` grants 整合
- ADR-00006 (Secrets management、既 accepted): OAuth client credential 経由 ephemeral auth key
