from __future__ import annotations

from typing import Final, Literal, get_args

AutonomyLevel = Literal["L0", "L1", "L2", "L3"]

ALL_AUTONOMY_LEVELS: Final[frozenset[str]] = frozenset({"L0", "L1", "L2", "L3"})
DEFAULT_AUTONOMY_LEVEL: Final[AutonomyLevel] = "L0"

_AUTONOMY_LEVEL_LITERAL_ARGS: Final[frozenset[str]] = frozenset(get_args(AutonomyLevel))
if _AUTONOMY_LEVEL_LITERAL_ARGS != ALL_AUTONOMY_LEVELS:
    raise AssertionError(
        "AutonomyLevel Literal and ALL_AUTONOMY_LEVELS drift: "
        f"Literal={sorted(_AUTONOMY_LEVEL_LITERAL_ARGS)}, "
        f"frozenset={sorted(ALL_AUTONOMY_LEVELS)}"
    )


__all__ = ["ALL_AUTONOMY_LEVELS", "AutonomyLevel", "DEFAULT_AUTONOMY_LEVEL"]
