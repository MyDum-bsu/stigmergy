from __future__ import annotations

from pathlib import Path

from conftest import SPEC_T1

from stigmergy.spec import Spec, SpecError


def test_parse_from_git(repo: Path) -> None:
    spec = Spec.from_git(repo, "dev", "specs/T1.md")
    assert spec.id == "T1"
    assert spec.risk == "medium"
    assert spec.dod == "python3 test_gate.py"
    assert spec.oracle_paths == ["test_gate.py"]
    assert spec.negative_corpus == "oracle/negative/T1/"
    assert not spec.validate()
    assert not spec.validate_against_repo(repo, "dev")
    assert len(spec.sha) == 64


def test_sha_is_stable_and_body_sensitive() -> None:
    a = Spec.from_text(SPEC_T1, "specs/T1.md")
    b = Spec.from_text(SPEC_T1, "specs/T1.md")
    c = Spec.from_text(SPEC_T1.replace("Add work.txt", "Add other.txt"), "specs/T1.md")
    assert a.sha == b.sha
    assert a.sha != c.sha


def test_invalid_specs() -> None:
    no_dod = SPEC_T1.replace("dod: python3 test_gate.py\n", "")
    errors = Spec.from_text(no_dod, "specs/T1.md").validate()
    assert any("dod" in e for e in errors)

    escape = SPEC_T1.replace("  - src.txt", "  - ../outside")
    errors = Spec.from_text(escape, "specs/T1.md").validate()
    assert any("unsafe path" in e for e in errors)

    no_control = SPEC_T1.replace("negative_control:\n  corpus: oracle/negative/T1/\n", "")
    errors = Spec.from_text(no_control, "specs/T1.md").validate()
    assert any("negative_control" in e for e in errors)


def test_missing_frontmatter() -> None:
    try:
        Spec.from_text("no frontmatter", "x.md")
    except SpecError:
        pass
    else:
        raise AssertionError("expected SpecError")
