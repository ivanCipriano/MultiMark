"""Dimostratore ``multimark.cli.demo`` (P7.d): preimpostazioni uguali alle configurazioni congelate,
chiave solo da file o variabile d'ambiente, ``mark``/``verify``/``show`` su un esempio piccolo.

Nessuna chiave è scritta qui: ogni test ne genera una a caso (``secrets``) e la passa per variabile
d'ambiente o per un file temporaneo."""

from __future__ import annotations

import ast
import io
import json
import secrets
from pathlib import Path
from typing import Any

import pytest

from multimark.cli import demo
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_functions.jsonl"
MESSAGE = "0xabcdef"
BITS = format(0xABCDEF, "024b")

# Iperparametri dei tre punti come nel registro di congelamento di wm-bench
# (docs/milestone_logs/P6_freeze_*.txt), con i nomi del protocollo (§3.11).
FROZEN: dict[str, dict[str, Any]] = {
    "mcss_main": {"t": 2, "linking": "positional", "mask": "off", "canonical": "paper",
                  "names.variant": "V1", "names.proposer": "static",
                  "names.include_params": True, "channels": "mcss8", "names.module_level": True,
                  "code.matrix": "random", "names.single_letter": "extend_except_loop",
                  "names.bits_per_name": 1, "canonical.same_kind": "off",
                  "canonical.natural_forms": "off", "names.suffix_by_type": "off",
                  "voting": "simple", "channel_weights": None},
    "multimark_prudent": {"names.bits_per_name": 2},
    "multimark_high_capacity": {"names.single_letter": "extend_except_loop",
                                "canonical.same_kind": "binding_order", "names.bits_per_name": 2,
                                "names.include_params": True},
}  # fmt: skip


def _native(hp: dict[str, Any]) -> dict[str, Any]:
    return {k.replace(".", "_"): v for k, v in hp.items()}


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> int:
    value = secrets.randbits(64)
    monkeypatch.setenv(demo.DEFAULT_KEY_ENV, str(value))
    return value


@pytest.fixture
def source(tmp_path: Path) -> Path:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    path = tmp_path / "example.py"
    path.write_text(rows[0]["code"] + "\n\n" + rows[1]["code"], encoding="utf-8")
    return path


def _run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = demo.main(list(argv), out=out)
    return code, out.getvalue()


# ---------------------------------------------------------------------------- preimpostazioni
def test_presets_are_the_frozen_configurations() -> None:
    assert set(demo.PRESETS) == set(FROZEN)
    hashes = {name: p.config_hash for name, p in demo.PRESETS.items()}
    assert hashes == {"mcss_main": "1d3087c73439", "multimark_prudent": "e52b040770df",
                      "multimark_high_capacity": "3fed1f1c1e24"}  # fmt: skip
    assert demo.PRESETS["mcss_main"].config() == Config(**_native(FROZEN["mcss_main"]))
    assert demo.PRESETS["mcss_main"].config() == mcss_profile()
    for name in ("multimark_prudent", "multimark_high_capacity"):
        expected = multimark_base().with_(**_native(FROZEN[name]))
        assert demo.PRESETS[name].config() == expected
        assert demo.PRESETS[name].method == "multimark"


def test_every_preset_has_a_frozen_threshold_per_model() -> None:
    for p in demo.PRESETS.values():
        assert set(p.thresholds) == set(demo.MODELS)
        assert all(1.0 < tau < 2.0 for tau in p.thresholds.values())


def test_demo_uses_only_the_public_api() -> None:
    tree = ast.parse(Path(demo.__file__).read_text(encoding="utf-8"))
    imported = {
        (n.module, a.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("multimark")
        for a in n.names
    }
    assert imported == {("multimark.config", "Config"), ("multimark.detect", "detect"),
                        ("multimark.embed", "embed")}  # fmt: skip


# ---------------------------------------------------------------------------- chiave e messaggio
def test_key_from_env_and_from_file(key: int, tmp_path: Path) -> None:
    assert demo.read_key(None, demo.DEFAULT_KEY_ENV) == key
    other = secrets.randbits(64)
    f = tmp_path / "k.txt"
    f.write_text(hex(other) + "\n", encoding="utf-8")
    assert demo.read_key(f, demo.DEFAULT_KEY_ENV, repo_root=tmp_path / "repo") == other


def test_key_file_inside_the_repository_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    f = repo / "sub" / "k.txt"
    f.parent.mkdir()
    f.write_text(str(secrets.randbits(64)), encoding="utf-8")
    with pytest.raises(demo.DemoError, match="inside the repository"):
        demo.read_key(f, demo.DEFAULT_KEY_ENV, repo_root=repo)


def test_missing_or_bad_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MM_DEMO_TEST_KEY", raising=False)
    with pytest.raises(demo.DemoError, match="no key"):
        demo.read_key(None, "MM_DEMO_TEST_KEY")
    monkeypatch.setenv("MM_DEMO_TEST_KEY", str(2**64))
    with pytest.raises(demo.DemoError, match="64-bit"):
        demo.read_key(None, "MM_DEMO_TEST_KEY")
    monkeypatch.setenv("MM_DEMO_TEST_KEY", "not-a-number")
    with pytest.raises(demo.DemoError, match="not an integer"):
        demo.read_key(None, "MM_DEMO_TEST_KEY")


def test_no_key_on_the_command_line(source: Path) -> None:
    with pytest.raises(SystemExit):
        demo.build_parser().parse_args(["mark", str(source), "--message", "1", "--key", "5"])


def test_parse_message() -> None:
    assert demo.parse_message(BITS) == BITS
    assert demo.parse_message("0xABCDEF") == BITS
    assert demo.parse_message(str(0xABCDEF)) == BITS
    assert demo.parse_message("1") == "0" * 23 + "1"
    for bad in ("0x1000000", "-1", "abc"):
        with pytest.raises(demo.DemoError):
            demo.parse_message(bad)


# ---------------------------------------------------------------------------- sottocomandi
@pytest.mark.parametrize("preset", sorted(demo.PRESETS))
def test_mark_then_verify(preset: str, key: int, source: Path) -> None:
    original = source.read_text(encoding="utf-8")
    code, out = _run("mark", str(source), "--preset", preset, "--message", MESSAGE)
    assert code == 0, out
    marked = source.with_name("example.marked.py")
    assert source.read_text(encoding="utf-8") == original
    p = demo.PRESETS[preset]
    assert marked.read_text(encoding="utf-8") == embed(original, BITS, key, p.config()).code
    assert str(key) not in out

    code, out = _run("verify", str(marked), "--preset", preset, "--message", MESSAGE)
    res = detect(marked.read_text(encoding="utf-8"), BITS, key, p.config(), registry_sizes=(1,),
                 method=p.method)  # fmt: skip
    assert res.score is not None and res.score >= p.thresholds["qwen25_coder_7b"]
    assert code == 0 and "detected  yes" in out
    assert f"score     {res.score:.4f}" in out
    assert f"threshold {p.thresholds['qwen25_coder_7b']:.4f}" in out


def test_verify_scores_like_the_library_on_unmarked_code(key: int, source: Path) -> None:
    p = demo.PRESETS["multimark_high_capacity"]
    code, out = _run("verify", str(source), "--preset", "multimark_high_capacity",
                     "--message", MESSAGE, "--model", "deepseek_coder_6p7b")  # fmt: skip
    res = detect(source.read_text(encoding="utf-8"), BITS, key, p.config(), registry_sizes=(1,))
    assert res.score is not None
    hit = res.score >= p.thresholds["deepseek_coder_6p7b"]
    assert code == (0 if hit else 1)
    assert f"score     {res.score:.4f}" in out


def test_verify_without_message_gives_the_open_decoding(key: int, source: Path) -> None:
    assert _run("mark", str(source), "--preset", "mcss_main", "--message", MESSAGE)[0] == 0
    code, out = _run("verify", str(source.with_name("example.marked.py")), "--preset", "mcss_main")
    assert code == 0
    assert "decoded   " in out and "needs the expected message" in out


def test_mark_never_overwrites(key: int, source: Path) -> None:
    assert _run("mark", str(source), "--message", MESSAGE)[0] == 0
    marked = source.with_name("example.marked.py")
    before = marked.read_text(encoding="utf-8")
    assert _run("mark", str(source), "--message", "0x000001")[0] == 2
    assert marked.read_text(encoding="utf-8") == before
    assert _run("mark", str(source), "--message", MESSAGE, "--output", str(source))[0] == 2


def test_mark_without_sites_writes_nothing(key: int, tmp_path: Path) -> None:
    src = tmp_path / "empty.py"
    src.write_text("import os\n", encoding="utf-8")
    code, out = _run("mark", str(src), "--message", MESSAGE)
    assert code == 1 and "FAILED" in out
    assert not (tmp_path / "empty.marked.py").exists()


def test_show_lists_sites_and_diff(key: int, source: Path) -> None:
    preset = "multimark_high_capacity"
    assert _run("mark", str(source), "--preset", preset, "--message", MESSAGE)[0] == 0
    code, out = _run("show", str(source), "--preset", preset)
    assert code == 0
    marked = source.with_name("example.marked.py").read_text(encoding="utf-8")
    res = detect(marked, BITS, key, demo.PRESETS[preset].config(), registry_sizes=(1,))
    rows = [line.split() for line in out.splitlines()
            if line.split()[:1] in (["has_close_elements"], ["separate_paren_groups"])]  # fmt: skip
    assert len(rows) == len(res.extra["sites"]) == res.extra["n_votes"]
    assert [r[1:] for r in rows] == [[c, str(rank), str(v)]
                                     for _f, _n, c, rank, _r, v in res.extra["sites"]]  # fmt: skip
    assert "--- " in out and "+++ " in out and "\n-def has_close_elements" in out


def test_errors_exit_with_2(key: int, tmp_path: Path) -> None:
    assert _run("verify", str(tmp_path / "missing.py"), "--message", MESSAGE)[0] == 2
