"""Dogfooding seed CLI contract test (SP-012-10 BL-DOG-001/002/003).

frontmatter parse + Sprint Pack 件数 discover + Ticket schema mapping を
DB 接続不要で verify (offline parser unit test)。

DB integration test (idempotent re-run + actual seed apply) は
`tests/cli/test_dogfooding_seed_integration.py` で別途実装予定 (本 PR scope 外)。
"""

from __future__ import annotations

from backend.app.cli.dogfooding_seed import (
    _ADR_STATUS_TO_TICKET_STATUS,
    _SPRINT_STATUS_TO_TICKET_STATUS,
    AdrMeta,
    BlMeta,
    SprintPackMeta,
    discover_adrs,
    discover_bls,
    discover_sprint_packs,
    parse_adr,
    parse_sprint_pack,
)


def test_discover_sprint_packs_finds_at_least_25_files() -> None:
    """docs/sprints/ には少なくとも 25 件 Sprint Pack が存在 (SP-000 〜 SP-022-1)."""
    paths = discover_sprint_packs()
    assert len(paths) >= 25, f"Sprint Pack 件数が少なすぎる: {len(paths)}"

    # template files は除外
    for path in paths:
        assert not path.name.startswith("_template"), (
            f"_template_* file が discover に含まれる: {path.name}"
        )


def test_parse_sprint_pack_sp012_7_completed() -> None:
    """SP-012-7 (status=completed) の frontmatter parse 確認."""
    paths = discover_sprint_packs()
    target = next(
        (p for p in paths if "SP-012-7" in p.name),
        None,
    )
    assert target is not None, "SP-012-7 Sprint Pack file が見つからない"

    meta = parse_sprint_pack(target)
    assert meta is not None
    assert meta.id == "SP-012-7_phase_f_0_prerequisite"
    assert meta.status == "completed"
    assert meta.ticket_status == "closed"  # completed → closed mapping
    assert meta.sprint_no == "12.7"


def test_parse_sprint_pack_sp013_draft() -> None:
    """SP-013 (status=draft) の frontmatter parse 確認."""
    paths = discover_sprint_packs()
    target = next(
        (p for p in paths if "SP-013_multi_agent" in p.name),
        None,
    )
    assert target is not None
    meta = parse_sprint_pack(target)
    assert meta is not None
    assert meta.id == "SP-013_multi_agent_orchestration"
    assert meta.status == "draft"
    assert meta.ticket_status == "open"  # draft → open mapping


def test_sprint_pack_meta_slug_is_kebab_dogfooding_prefix() -> None:
    """SprintPackMeta.slug = `dogfooding-sprint-<id-kebab>` format."""
    meta = SprintPackMeta(
        file_name="SP-012-7_phase_f_0_prerequisite.md",
        id="SP-012-7_phase_f_0_prerequisite",
        status="completed",
        sprint_no="12.7",
        target_days="2",
        max_days="3",
        objective="Phase F-0 prerequisite for SP-013",
    )
    assert meta.slug == "dogfooding-sprint-sp-012-7-phase-f-0-prerequisite"
    assert meta.slug.startswith("dogfooding-sprint-")
    # slug は ticket CHECK constraint URL-safe pattern と整合
    import re
    assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", meta.slug)


def test_sprint_pack_meta_metadata_includes_dogfooding_source() -> None:
    """metadata に dogfooding_source.id / type / file_name / sprint_status を含む."""
    meta = SprintPackMeta(
        file_name="SP-013_multi_agent_orchestration.md",
        id="SP-013_multi_agent_orchestration",
        status="draft",
        sprint_no="13",
        target_days="5",
        max_days="7",
        objective="Multi-agent orchestration foundation",
    )
    assert meta.metadata["dogfooding_source"]["type"] == "sprint_pack"
    assert meta.metadata["dogfooding_source"]["id"] == "SP-013_multi_agent_orchestration"
    assert meta.metadata["dogfooding_source"]["sprint_status"] == "draft"
    assert meta.metadata["rls_ready"] is True


def test_status_mapping_covers_all_known_states() -> None:
    """全 known Sprint Pack status が ticket status enum (6 種) に map される."""
    valid_ticket_statuses = {
        "open", "in_progress", "blocked", "review", "closed", "cancelled"
    }
    for sprint_status, ticket_status in _SPRINT_STATUS_TO_TICKET_STATUS.items():
        assert ticket_status in valid_ticket_statuses, (
            f"Sprint status '{sprint_status}' maps to invalid ticket status "
            f"'{ticket_status}'"
        )


def test_sprint_pack_meta_title_and_description_format() -> None:
    """Ticket title と description の format 確認."""
    meta = SprintPackMeta(
        file_name="SP-013_multi_agent_orchestration.md",
        id="SP-013_multi_agent_orchestration",
        status="draft",
        sprint_no="13",
        target_days="5",
        max_days="7",
        objective="Multi-agent orchestration foundation prerequisite",
    )
    assert meta.title == "Sprint Pack: SP-013_multi_agent_orchestration"
    assert "[Sprint Pack]" in meta.description
    assert "sprint_no=13" in meta.description
    assert "target_days=5/max=7" in meta.description
    assert "## 目的" in meta.description
    assert "Multi-agent orchestration foundation prerequisite" in meta.description


def test_parse_sprint_pack_all_existing_files() -> None:
    """全 Sprint Pack ファイルが parse 成功 (frontmatter 不在 0 件)."""
    paths = discover_sprint_packs()
    parsed_count = 0
    failures: list[str] = []
    for path in paths:
        meta = parse_sprint_pack(path)
        if meta is None:
            failures.append(path.name)
        else:
            parsed_count += 1
            # 基本属性が空でないこと
            assert meta.id, f"{path.name}: id が空"
            assert meta.status, f"{path.name}: status が空"
            assert meta.ticket_status in {
                "open", "in_progress", "blocked", "review", "closed", "cancelled"
            }, f"{path.name}: ticket_status invalid: {meta.ticket_status}"

    assert not failures, f"frontmatter parse 失敗: {failures}"
    assert parsed_count == len(paths)


def test_discover_adrs_finds_at_least_25_files() -> None:
    """docs/adr/ には少なくとも 25 件 ADR が存在 (ADR-00001 〜 ADR-00029、README 除外)."""
    paths = discover_adrs()
    assert len(paths) >= 25, f"ADR 件数が少なすぎる: {len(paths)}"

    for path in paths:
        assert path.name != "README.md", f"README.md が discover に含まれる: {path.name}"
        assert not path.name.startswith("_template"), f"_template_* が含まれる: {path.name}"


def test_parse_adr_00014_accepted() -> None:
    """ADR-00014 (本日 accepted 化) の frontmatter parse."""
    paths = discover_adrs()
    target = next(
        (p for p in paths if "00014" in p.name),
        None,
    )
    assert target is not None
    meta = parse_adr(target)
    assert meta is not None
    assert meta.id == "ADR-00014"
    assert meta.status == "accepted"
    assert meta.ticket_status == "closed"  # accepted → closed
    assert meta.accepted_at == "2026-05-22"


def test_parse_adr_00013_proposed() -> None:
    """ADR-00013 (proposed のまま) の frontmatter parse."""
    paths = discover_adrs()
    target = next(
        (p for p in paths if "00013" in p.name),
        None,
    )
    assert target is not None
    meta = parse_adr(target)
    assert meta is not None
    assert meta.id == "ADR-00013"
    assert meta.status == "proposed"
    assert meta.ticket_status == "open"  # proposed → open


def test_adr_meta_slug_is_kebab_dogfooding_prefix() -> None:
    """AdrMeta.slug = `dogfooding-adr-<id-kebab>` format."""
    meta = AdrMeta(
        file_name="00014_multi_agent_orchestration.md",
        id="ADR-00014",
        title="Multi-Agent Orchestration Foundation",
        status="accepted",
        date="2026-05-10",
        accepted_at="2026-05-22",
    )
    assert meta.slug == "dogfooding-adr-adr-00014"
    assert meta.slug.startswith("dogfooding-adr-")
    import re
    assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", meta.slug)


def test_adr_status_mapping_covers_known_states() -> None:
    """全 known ADR status が ticket status enum (6 種) に map."""
    valid_ticket_statuses = {
        "open", "in_progress", "blocked", "review", "closed", "cancelled"
    }
    for adr_status, ticket_status in _ADR_STATUS_TO_TICKET_STATUS.items():
        assert ticket_status in valid_ticket_statuses, (
            f"ADR status '{adr_status}' maps to invalid ticket status '{ticket_status}'"
        )


def test_parse_adr_all_existing_files() -> None:
    """全 ADR ファイルが parse 成功 (frontmatter 不在 0 件)."""
    paths = discover_adrs()
    parsed_count = 0
    failures: list[str] = []
    for path in paths:
        meta = parse_adr(path)
        if meta is None:
            failures.append(path.name)
        else:
            parsed_count += 1
            assert meta.id.startswith("ADR-"), f"{path.name}: id format invalid: {meta.id}"
            assert meta.ticket_status in {
                "open", "in_progress", "blocked", "review", "closed", "cancelled"
            }, f"{path.name}: ticket_status invalid: {meta.ticket_status}"

    assert not failures, f"ADR parse 失敗: {failures}"
    assert parsed_count == len(paths)


def test_discover_bls_finds_at_least_150_rows() -> None:
    """docs/実装計画/P0_バックログ.md には少なくとも 150 件 BL row が存在."""
    bls = discover_bls()
    assert len(bls) >= 150, f"BL 件数が少なすぎる: {len(bls)}"
    # 主要 BL の存在確認
    bl_ids = {bl.id for bl in bls}
    assert "BL-0001" in bl_ids, "BL-0001 が discover に含まれない"


def test_bl_meta_basic_fields_parsed() -> None:
    """BL row の主要 fields (id, title, sprint_no, type, trace, priority, days) が抽出される."""
    bls = discover_bls()
    target = next((bl for bl in bls if bl.id == "BL-0001"), None)
    assert target is not None
    assert target.title  # title 空でない
    assert target.sprint_no == "0"  # Sprint 0
    assert target.bl_type == "doc"
    # trace は F-001 等を含むはず
    assert "F-" in target.trace or "NF-" in target.trace or "AC-" in target.trace
    assert target.priority.startswith("P0-") or target.priority == "P1"
    assert target.sprint_pack.startswith("SP-")


def test_bl_meta_slug_is_kebab_dogfooding_prefix() -> None:
    """BlMeta.slug = `dogfooding-bl-<id-kebab>` format."""
    meta = BlMeta(
        id="BL-0145",
        title="Test BL",
        sprint_no="12",
        bl_type="feature",
        trace="F-014",
        priority="P0-A",
        days="0.5",
        depends_on="-",
        sprint_pack="SP-012_p0_acceptance",
    )
    assert meta.slug == "dogfooding-bl-bl-0145"
    import re
    assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", meta.slug)


def test_bl_meta_metadata_includes_dogfooding_source() -> None:
    """BlMeta.metadata に dogfooding_source.type=bl + sprint_no / sprint_pack を含む."""
    meta = BlMeta(
        id="BL-0145",
        title="Test BL",
        sprint_no="12",
        bl_type="feature",
        trace="F-014",
        priority="P0-A",
        days="0.5",
        depends_on="-",
        sprint_pack="SP-012_p0_acceptance",
    )
    assert meta.metadata["dogfooding_source"]["type"] == "bl"
    assert meta.metadata["dogfooding_source"]["id"] == "BL-0145"
    assert meta.metadata["dogfooding_source"]["sprint_no"] == "12"
    assert meta.metadata["dogfooding_source"]["sprint_pack"] == "SP-012_p0_acceptance"
    assert meta.metadata["rls_ready"] is True


def test_parse_bl_all_rows_have_valid_id_format() -> None:
    """全 BL row が `BL-NNNN[a-z]?` id format に整合."""
    bls = discover_bls()
    import re
    bl_id_pattern = re.compile(r"^BL-\d{4}[a-z]?$")
    for bl in bls:
        assert bl_id_pattern.match(bl.id), f"BL id format invalid: {bl.id}"
        assert bl.ticket_status == "open"  # BL default は open
