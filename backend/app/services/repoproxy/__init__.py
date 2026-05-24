"""Sprint 8: GitHub App + RepoProxy + Draft PR boundary.

ADR-00011 (GitHub App Permission Matrix) は design decision として
`accepted`。SP-008 は `partial_skeleton` で、Matrix loader / Mock RepoProxy /
Webhook HMAC helper / server-owned Draft PR binding を先行整備している。
実 GitHub App integration は後続 batch で実装する。

server-owned-boundary §1:
- installation_token は SecretBroker 内でのみ resolve
- RepoProxy は broker-mediated operation 経由のみ httpx request 実行
- raw token は caller / AI / runner / artifact / log / audit に渡さない
"""

from __future__ import annotations
