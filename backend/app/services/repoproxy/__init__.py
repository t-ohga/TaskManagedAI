"""Sprint 8: GitHub App + RepoProxy + Draft PR boundary.

ADR-00011 (GitHub App Permission Matrix) は Sprint 8 で `proposed`、Sprint 11
`acceptance_blocked_by` 完了後に `accepted` 昇格予定 (本 package は
`proposed` 段階で Matrix loader / Mock RepoProxy / Webhook HMAC helper を
先行整備、Sprint 11 で実 GitHub App integration と一緒に accepted 化する)。

server-owned-boundary §1:
- installation_token は SecretBroker 内でのみ resolve
- RepoProxy は broker-mediated operation 経由のみ httpx request 実行
- raw token は caller / AI / runner / artifact / log / audit に渡さない
"""

from __future__ import annotations
