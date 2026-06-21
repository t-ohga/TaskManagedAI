"""SP-PHASE0 S4 DB-gated fixtures (pytest auto-discovery)。

``session_factory`` を conftest 経由で provide することで、各 test file は fixture を import せず使える
(import + 同名 parameter の F811 redefinition を避ける)。harness 本体は ``tests/secrets/_db_harness.py``。
"""

from __future__ import annotations

from tests.secrets._db_harness import session_factory

__all__ = ["session_factory"]
