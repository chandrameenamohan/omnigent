"""Regression guard for the debby-native example's two native-terminal heads.

debby-native is the sibling of ``examples/debby`` whose two responder heads run
on the *native* terminal harnesses (the real ``claude`` / ``codex`` CLIs) rather
than in-process. These parse-only checks pin the harness + per-harness bypass
flag for each head so the example can't silently drift back to the in-process
config:

- the Claude head must be ``claude-native`` with ``permission_mode: auto``
  (headless workers can't answer ApprovalCards), and
- the GPT head must be ``codex-native`` with ``yolo: true`` (full bypass for a
  headless worker).

Non-live parse-only check so it runs in the default suite (the dir-shaped
example's own e2e coverage lives under ``tests/e2e``, ignored by default).
"""

from __future__ import annotations

from pathlib import Path

from omnigent.spec.parser import parse

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEBBY_NATIVE_DIR = _REPO_ROOT / "examples" / "debby-native"
_PACKAGED_DIR = _REPO_ROOT / "omnigent" / "resources" / "examples" / "debby-native"


def test_debby_native_heads_run_on_native_harnesses() -> None:
    """Claude head -> claude-native/auto; GPT head -> codex-native/yolo."""
    spec = parse(_DEBBY_NATIVE_DIR)
    by_name = {sub.name: sub for sub in spec.sub_agents}

    assert {"claude", "gpt"} <= set(by_name), (
        f"debby-native should declare 'claude' and 'gpt' sub-agents; got {sorted(by_name)}."
    )

    claude = by_name["claude"]
    assert claude.executor.harness_kind == "claude-native", (
        f"debby-native's Claude head must run on 'claude-native'; got "
        f"{claude.executor.harness_kind!r}."
    )
    assert claude.executor.config.get("permission_mode") == "auto", (
        "debby-native's Claude head must set permission_mode: auto so the "
        "headless worker auto-approves without prompting."
    )

    gpt = by_name["gpt"]
    assert gpt.executor.harness_kind == "codex-native", (
        f"debby-native's GPT head must run on 'codex-native'; got "
        f"{gpt.executor.harness_kind!r}."
    )
    # The spec parser stringifies non-structured config values, so ``yolo: true``
    # arrives as the string ``"True"`` — compare case-insensitively.
    assert str(gpt.executor.config.get("yolo")).lower() == "true", (
        "debby-native's GPT head must set yolo: true so the headless worker "
        "runs with full bypass."
    )


def test_packaged_debby_native_resource_stays_in_sync() -> None:
    """The bundled debby-native resource resolves to the source example."""
    assert _PACKAGED_DIR.exists(), "debby-native's packaged resource should exist."
    assert _PACKAGED_DIR.resolve() == _DEBBY_NATIVE_DIR.resolve(), (
        "debby-native's packaged resource must resolve to examples/debby-native."
    )
