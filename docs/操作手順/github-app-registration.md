# GitHub App 実登録手順

## 前提

- GitHub アカウントに admin 権限
- SOPS + age が設定済み (`config/secrets/` + `.sops.yaml`)
- TaskManagedAI の DB に `secret_refs` row が存在

## 手順

### 1. GitHub App 作成

1. https://github.com/settings/apps/new にアクセス
2. 以下を設定:
   - **App name**: `taskmanagedai-dev` (任意)
   - **Homepage URL**: `https://github.com/t-ohga/TaskManagedAI`
   - **Webhook URL**: 空欄 (Tailscale 内 endpoint は後で設定)
   - **Webhook secret**: ランダム生成 (`openssl rand -hex 32`)

3. Permissions:
   - **Repository permissions**:
     - Contents: Read & Write
     - Pull requests: Read & Write
     - Metadata: Read-only
   - **Organization permissions**: なし
   - **Account permissions**: なし

4. **Generate a private key** → `.pem` ファイルをダウンロード

### 2. Private Key を SOPS encrypt

```bash
# .pem を SOPS encrypted YAML に変換
sops --encrypt --age $(cat config/secrets/.age-recipients) \
  --input-type binary --output-type yaml \
  github-app-private-key.pem > config/secrets/repo/github-app-private-key.v1.enc.yaml
```

### 3. Webhook Secret を SOPS encrypt

```bash
echo -n "YOUR_WEBHOOK_SECRET" | \
  sops --encrypt --age $(cat config/secrets/.age-recipients) \
  --input-type binary --output-type yaml \
  /dev/stdin > config/secrets/p0/github_webhook_hmac.v1.enc.yaml
```

### 4. secret_refs に登録

```sql
INSERT INTO secret_refs (tenant_id, scope, name, version, status, secret_uri, allowed_consumers, allowed_operations)
VALUES (
  1, 'repo', 'github-app-private-key', 'v1', 'active',
  'secret://sops/repo/github-app-private-key#v1',
  ARRAY['api:repo_proxy'],
  ARRAY['repo.push', 'repo.pr_open']
);

INSERT INTO secret_refs (tenant_id, scope, name, version, status, secret_uri, allowed_consumers, allowed_operations)
VALUES (
  1, 'p0', 'github_webhook_hmac', 'v1', 'active',
  'secret://sops/p0/github_webhook_hmac#v1',
  ARRAY['api:repo_proxy'],
  ARRAY['secret.verify']
);
```

### 5. Installation

1. GitHub App 設定ページ → Install App
2. TaskManagedAI リポジトリを選択
3. Installation ID をメモ

### 6. 検証

```bash
# webhook HMAC 検証
curl -X POST http://127.0.0.1:8000/webhooks/github \
  -H "X-Hub-Signature-256: sha256=..." \
  -H "X-GitHub-Event: ping" \
  -d '{"zen": "test"}'

# RepoProxy 経由 Draft PR (テスト)
uv run pytest tests/repoproxy/ -q
```

## 注意事項

- `.pem` ファイルは encrypt 後に削除
- raw secret を git に commit しない
- Installation ID は `.env.local` に設定 (gitignored)
