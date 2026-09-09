"""L0 — the page record (Spec §5.3) and the `INDEXED` dict (§5.4, I6).

Two properties carry the weight. **Every `INDEXED` key is a flat payload key** — if one were
nested, a filter on it would run unindexed and return a smaller answer that looks complete (F10).
And **`is_current` defaults to False** — a run that has not passed its gates cannot answer (I7),
and a default of True would make that a matter of remembering.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from vsir.core import ids
from vsir.core.indexed import (
    DENSE_VECTOR,
    INDEXED,
    SPARSE_VECTORS,
    TEXT_FIELDS,
    reject_unknown_keys,
    scope_keys,
)
from vsir.core.record import (
    PAGE_KINDS,
    SCHEMA_VERSION,
    PageContent,
    PageRecord,
    Provenance,
    StoredSection,
    Summary,
)

PAGE_ID = ids.page_id("TC1E-SF", "1.3", 8)


def minimal() -> dict:
    """The least a record can be built from — everything else has a documented default."""
    return {
        "doc_id": "TC1E-SF",
        "revision": "1.3",
        "page_no": 8,
        "provenance": Provenance(page_id=PAGE_ID),
    }


# ── INDEXED — one dict, three jobs ──────────────────────────────────────────────────────────────

def test_indexed_has_exactly_the_sixteen_keys_of_the_spec():
    assert dict(INDEXED) == {
        "doc_id": "keyword", "revision": "keyword", "is_current": "bool", "doc_type": "keyword",
        "subjects": "keyword", "tags": "keyword", "page_kind": "keyword", "lang": "keyword",
        "page_no": "integer", "section_id": "keyword[]", "series_id": "keyword[]",
        "has_text": "bool", "text_trust": "keyword", "run_id": "keyword",
        "text": "text", "vlm_codes": "text",
    }
    assert len(INDEXED) == 16


def test_indexed_cannot_be_mutated_at_runtime():
    """A seventeenth key would be a field the creation loop never indexed (I6)."""
    with pytest.raises(TypeError):
        INDEXED["sneaky"] = "keyword"  # type: ignore[index]


def test_scope_keys_are_indexed_minus_the_two_text_surfaces():
    assert scope_keys() == set(INDEXED) - {"text", "vlm_codes"}
    assert set(TEXT_FIELDS) == {"text", "vlm_codes"}


@pytest.mark.parametrize("key", ["text", "vlm_codes"])
def test_a_text_surface_is_not_a_caller_filter(key):
    """§5.4 — those two are reachable only through `lookup` and `verify`."""
    assert reject_unknown_keys([key]) == [key]


def test_an_unknown_or_nested_key_is_rejected_not_degraded():
    """F10 — accepting it would run an unindexed scan and lose recall silently."""
    assert reject_unknown_keys(["content.units", "machine_models", "entity_keys"]) == [
        "content.units", "entity_keys", "machine_models",
    ]
    assert reject_unknown_keys(["doc_id", "page_no", "is_current"]) == []


# ── the record ──────────────────────────────────────────────────────────────────────────────────

def test_the_payload_round_trips_with_no_field_loss():
    record = PageRecord(**minimal())

    restored = PageRecord.from_payload(record.to_payload())

    assert restored == record


def test_a_fully_populated_payload_round_trips():
    record = PageRecord(
        doc_id="TC1E-SF", revision="1.3", is_current=True, doc_type="safety_function_list",
        subjects=["C24"], tags=["pilot"], page_kind="schematic", lang=["en", "it"], page_no=8,
        section_id=[ids.section_id("TC1E-SF", "1.3", 7), ids.section_id("TC1E-SF", "1.3", 8)],
        series_id=[ids.series_id("TC1E-SF", "Emergency Stop")],
        has_text=True, text_trust="ok", run_id="01J000000000000000000000",
        text="SF 1.1A emergency stop", vlm_codes="SF 1.1A K158",
        content=PageContent(
            printed_page_no="Page 8 of 55", label_verified=True, interpolated=False,
            summaries=[Summary(lang="en", text="Two sentences about this page.")],
            topics=["emergency stop"],
            sections=[StoredSection(section_id=ids.section_id("TC1E-SF", "1.3", 7),
                                    title="Emergency Stop", series_id="TC1E-SF#s:emergency-stop",
                                    page_range=(7, 9), is_start=True)],
            codes=["SF 1.1A", "K158"], codes_in_text=["sf 1.1a"], moved_from=[],
            grounded_rate=0.5, flags=["safety_flagged"],
        ),
        provenance=Provenance(
            page_id=PAGE_ID, run_id="01J000000000000000000000", release_id="dev-0",
            extract_key="abc", embed_key="def", read_keys=["ghi"], probe_version="1.28.2",
            vlm_model="gemini-3.8-flash-001", prompt_version="s2-v1", dpi=220,
        ),
    )

    assert PageRecord.from_payload(record.to_payload()) == record


def test_the_payload_has_no_image_path():
    """Register A5 — a stale `image_path` made `read()` 503 for every page. There is no field."""
    payload = PageRecord(**minimal()).to_payload()

    assert "image_path" not in payload
    assert "image_path" not in payload["content"]
    assert "image_path" not in payload["provenance"]


def test_every_indexed_key_is_a_flat_payload_key():
    """I6 — a nested key can be filtered, unindexed, which is a silent recall loss (F10)."""
    payload = PageRecord(**minimal()).to_payload()

    for key in INDEXED:
        assert key in payload, f"{key!r} is in INDEXED but not flat in the payload"
        assert not isinstance(payload[key], dict)


def test_the_flat_payload_is_exactly_the_indexed_keys():
    """Nothing filterable hides in `content`, and nothing unfilterable sits flat beside it."""
    payload = PageRecord(**minimal()).to_payload()
    flat = set(payload) - {"content", "provenance"}

    assert flat == set(INDEXED)


def test_a_record_is_not_current_until_something_publishes_it():
    """I7 — step 10 writes `is_current=False`; only the publish gates flip it."""
    assert PageRecord(**minimal()).is_current is False


def test_grounded_rate_is_none_by_default_not_zero():
    """§5.7 — 0.0 would mean "extraction is broken", `None` means "nothing to check against"."""
    assert PageRecord(**minimal()).content.grounded_rate is None


def test_a_page_with_no_text_layer_is_no_text_by_default():
    record = PageRecord(**minimal())

    assert record.has_text is False
    assert record.text_trust == "no_text"


def test_section_and_series_ids_are_arrays_so_a_straddling_page_carries_both():
    """§5.3, F8 — a scope matches if any element matches; a scalar here is how F8 happens."""
    record = PageRecord(
        **minimal() | {"section_id": ["D@1#s001", "D@1#s002"], "series_id": ["D#s:a", "D#s:b"]}
    )

    payload = record.to_payload()
    assert payload["section_id"] == ["D@1#s001", "D@1#s002"]
    assert payload["series_id"] == ["D#s:a", "D#s:b"]


def test_page_id_is_single_sourced_from_provenance():
    record = PageRecord(**minimal())

    assert record.page_id == PAGE_ID == record.provenance.page_id
    assert "page_id" not in record.to_payload()


def test_the_record_refuses_an_unknown_field():
    """No untyped dict passthrough: a typo'd field is a validation error, not a silent drop."""
    with pytest.raises(ValidationError):
        PageRecord(**minimal() | {"machine_models": ["C24"]})


def test_the_record_refuses_an_unknown_text_trust_value():
    with pytest.raises(ValidationError):
        PageRecord(**minimal() | {"text_trust": "probably_fine"})


def test_the_record_requires_a_page_number_and_a_document():
    with pytest.raises(ValidationError):
        PageRecord(revision="1.3", page_no=1, provenance=Provenance(page_id=PAGE_ID))
    with pytest.raises(ValidationError):
        PageRecord(doc_id="D", revision="1.3", provenance=Provenance(page_id=PAGE_ID))


def test_the_page_kinds_of_the_extraction_schema_are_the_documented_eight():
    assert PAGE_KINDS == ("prose", "table", "schematic", "exploded", "cover", "toc", "index",
                          "blank")
    assert PageRecord(**minimal()).page_kind == "prose"


def test_the_schema_version_is_stamped_on_every_record():
    """§15 Factor V — an answer traces to the code and config that produced it."""
    assert PageRecord(**minimal()).provenance.schema_version == SCHEMA_VERSION


def test_the_vectors_are_not_part_of_the_payload():
    """A vector is not something a filter or a response ever reads; it travels in the upsert."""
    payload = PageRecord(**minimal()).to_payload()

    assert DENSE_VECTOR not in payload
    for name in SPARSE_VECTORS:
        assert name not in payload
