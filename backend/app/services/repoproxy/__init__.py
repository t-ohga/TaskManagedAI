"""Sprint 8: GitHub App + RepoProxy + Draft PR boundary.

ADR-00011 (GitHub App Permission Matrix) accepted 化前提 + SP-008 implementation
の package。Sprint 8 batch 1 では Permission Matrix loader を最初に実装。

server-owned-boundary §1:
- installation_token は SecretBroker 内でのみ resolve
- RepoProxy は broker-mediated operation 経由のみ httpx request 実行
- raw token は caller / AI / runner / artifact / log / audit に渡さない
"""

from __future__ import annotations
