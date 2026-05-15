from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


class ProvValidationError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class _ProvTypedNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    type: str

    @field_validator("id")
    @classmethod
    def _id_must_be_nonempty(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("id must be nonempty.")
        return value


class ProvActivity(_ProvTypedNode):
    @field_validator("type")
    @classmethod
    def _type_must_be_activity(cls, value: str) -> str:
        if value != "prov:Activity":
            raise ValueError("type must be prov:Activity.")
        return value


class ProvEntity(_ProvTypedNode):
    @field_validator("type")
    @classmethod
    def _type_must_be_entity(cls, value: str) -> str:
        if value != "prov:Entity":
            raise ValueError("type must be prov:Entity.")
        return value


class ProvAgent(_ProvTypedNode):
    @field_validator("type")
    @classmethod
    def _type_must_be_agent(cls, value: str) -> str:
        if value != "prov:Agent":
            raise ValueError("type must be prov:Agent.")
        return value


class _ProvRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*")
    @classmethod
    def _refs_must_be_nonempty(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("relation references must be nonempty.")
        return value


class ProvWasGeneratedBy(_ProvRelation):
    entity: str
    activity: str


class ProvUsed(_ProvRelation):
    activity: str
    entity: str


class ProvWasAttributedTo(_ProvRelation):
    entity: str
    agent: str


class ProvWasInformedBy(_ProvRelation):
    informed: str
    informant: str


class ProvWasDerivedFrom(_ProvRelation):
    generated: str
    used: str


_PROV_TOP_LEVEL_ALIASES = {
    "prov:activities": "activities",
    "prov:entities": "entities",
    "prov:agents": "agents",
    "prov:wasGeneratedBy": "wasGeneratedBy",
    "prov:used": "used",
    "prov:wasAttributedTo": "wasAttributedTo",
    "prov:wasInformedBy": "wasInformedBy",
    "prov:wasDerivedFrom": "wasDerivedFrom",
}


class ProvBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    activities: list[ProvActivity] = []
    entities: list[ProvEntity] = []
    agents: list[ProvAgent] = []
    wasGeneratedBy: list[ProvWasGeneratedBy] = []
    used: list[ProvUsed] = []
    wasAttributedTo: list[ProvWasAttributedTo] = []
    wasInformedBy: list[ProvWasInformedBy] = []
    wasDerivedFrom: list[ProvWasDerivedFrom] = []

    @model_validator(mode="before")
    @classmethod
    def _normalize_prov_namespace_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"PROV top-level key must be str, got {type(key).__name__}")
            normalized_key = _PROV_TOP_LEVEL_ALIASES.get(key, key)
            if normalized_key in normalized:
                raise ValueError(f"duplicate PROV top-level key after namespace normalization: {key}")
            normalized[normalized_key] = item
        return normalized


def _assert_unique_ids(kind: str, ids: list[str]) -> None:
    # F-PR19-R4-002 P2 adopt: O(N^2) を O(N) に修正 (Counter で各 ID の count を 1 pass)
    from collections import Counter
    counts = Counter(ids)
    duplicates = sorted(item for item, count in counts.items() if count > 1)
    if duplicates:
        raise ProvValidationError(f"duplicate {kind} ids: {', '.join(duplicates)}")


def _assert_refs_exist(
    relation_name: str,
    field_name: str,
    refs: list[str],
    allowed_ids: set[str],
) -> None:
    missing = sorted({ref for ref in refs if ref not in allowed_ids})
    if missing:
        raise ProvValidationError(
            f"{relation_name}.{field_name} references unknown ids: {', '.join(missing)}"
        )


def validate_provenance_json(provenance_json: dict[str, Any]) -> ProvBundle:
    """Validate the TaskManagedAI P0 W3C PROV-DM minimal subset."""

    try:
        bundle = ProvBundle.model_validate(provenance_json)
    except ValidationError as exc:
        # F-PR19-R4-003 P1 adopt: raw caller-supplied input value を echo しない (audit / response にも)
        # Pydantic ValidationError.str() は raw input value を含む経路があるため、loc + type のみ抽出して sanitize。
        # 完全な error context は audit log の structured form に閉じる (本 endpoint レベルでは expose しない)。
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        locations = sorted({".".join(str(p) for p in err.get("loc", ())) for err in errors})
        raise ProvValidationError(
            f"PROV schema validation failed: {len(errors)} error(s) at locations: {', '.join(locations) or '(root)'}"
        ) from exc
    except ValueError as exc:
        # ValueError は _normalize_prov_namespace_keys 由来、caller key (raw) を含む可能性、message を sanitize
        raise ProvValidationError(
            "PROV namespace normalization failed (caller-controlled key conflict, see audit logs)"
        ) from exc

    if not bundle.wasGeneratedBy:
        raise ProvValidationError("wasGeneratedBy must contain at least one relation.")

    activity_ids = [activity.id for activity in bundle.activities]
    entity_ids = [entity.id for entity in bundle.entities]
    agent_ids = [agent.id for agent in bundle.agents]

    _assert_unique_ids("activity", activity_ids)
    _assert_unique_ids("entity", entity_ids)
    _assert_unique_ids("agent", agent_ids)

    activities = set(activity_ids)
    entities = set(entity_ids)
    agents = set(agent_ids)

    _assert_refs_exist(
        "wasGeneratedBy",
        "entity",
        [relation.entity for relation in bundle.wasGeneratedBy],
        entities,
    )
    _assert_refs_exist(
        "wasGeneratedBy",
        "activity",
        [relation.activity for relation in bundle.wasGeneratedBy],
        activities,
    )
    _assert_refs_exist("used", "activity", [relation.activity for relation in bundle.used], activities)
    _assert_refs_exist("used", "entity", [relation.entity for relation in bundle.used], entities)
    _assert_refs_exist(
        "wasAttributedTo",
        "entity",
        [relation.entity for relation in bundle.wasAttributedTo],
        entities,
    )
    _assert_refs_exist(
        "wasAttributedTo",
        "agent",
        [relation.agent for relation in bundle.wasAttributedTo],
        agents,
    )
    _assert_refs_exist(
        "wasInformedBy",
        "informed",
        [relation.informed for relation in bundle.wasInformedBy],
        activities,
    )
    _assert_refs_exist(
        "wasInformedBy",
        "informant",
        [relation.informant for relation in bundle.wasInformedBy],
        activities,
    )
    _assert_refs_exist(
        "wasDerivedFrom",
        "generated",
        [relation.generated for relation in bundle.wasDerivedFrom],
        entities,
    )
    _assert_refs_exist(
        "wasDerivedFrom",
        "used",
        [relation.used for relation in bundle.wasDerivedFrom],
        entities,
    )

    return bundle


__all__ = [
    "ProvActivity",
    "ProvAgent",
    "ProvBundle",
    "ProvEntity",
    "ProvUsed",
    "ProvValidationError",
    "ProvWasAttributedTo",
    "ProvWasDerivedFrom",
    "ProvWasGeneratedBy",
    "ProvWasInformedBy",
    "validate_provenance_json",
]
