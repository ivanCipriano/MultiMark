"""Funzioni di calcolo del dimostratore (``mark_code``, ``verify_code``, ``site_rows``,
``side_by_side``, ``diff_html``), file con BOM e avvio della pagina web, senza Streamlit.

Nessuna chiave è scritta qui: ogni test ne genera una a caso."""

from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import secrets
from pathlib import Path
from typing import Any

import pytest

from multimark.cli import demo

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_functions.jsonl"
BITS = format(0xABCDEF, "024b")


def _code() -> str:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    return str(rows[0]["code"]) + "\n\n" + str(rows[1]["code"])


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> int:
    value = secrets.randbits(64)
    monkeypatch.setenv(demo.DEFAULT_KEY_ENV, str(value))
    return value


def _key_forms(key: int) -> list[str]:
    return [str(key), hex(key), f"{key:x}", f"{key:016x}", format(key, "b")]


def _assert_no_key(obj: Any, key: int) -> None:
    text = repr(dataclasses.asdict(obj))
    for form in _key_forms(key):
        assert form not in text


# ---------------------------------------------------------------------------- BOM
def test_bom_file_is_marked_and_verified(key: int, tmp_path: Path) -> None:
    """``Out-File -Encoding utf8`` di Windows PowerShell scrive il BOM: in 19eef36
    ``mark`` rispondeva FAILED (syntax_error)."""
    src = tmp_path / "bom.py"
    src.write_bytes(b"\xef\xbb\xbf" + _code().replace("\n", "\r\n").encode("utf-8"))
    out = io.StringIO()
    assert demo.main(["mark", str(src), "--message", "0xabcdef"], out=out) == 0, out.getvalue()
    marked = tmp_path / "bom.marked.py"
    assert not marked.read_bytes().startswith(b"\xef\xbb\xbf")
    out = io.StringIO()
    assert demo.main(["verify", str(marked), "--message", "0xabcdef"], out=out) == 0
    assert "detected  yes" in out.getvalue()
    bom_marked = tmp_path / "bom_marked_again.py"
    bom_marked.write_bytes(b"\xef\xbb\xbf" + marked.read_bytes())
    out = io.StringIO()
    assert demo.main(["show", str(src), "--marked", str(bom_marked)], out=out) == 0
    assert "names" in out.getvalue()


def test_bom_string_is_stripped(key: int) -> None:
    res = demo.mark_code("﻿" + _code(), BITS, key, "multimark_prudent")
    assert res.status in ("OK", "PARTIAL") and res.code is not None
    assert not res.code.startswith("﻿")
    assert demo.verify_code("﻿" + res.code, key, "multimark_prudent", demo.MODELS[0],
                            BITS).detected  # fmt: skip


# ---------------------------------------------------------------------------- calcolo
@pytest.mark.parametrize("preset", sorted(demo.PRESETS))
def test_mark_and_verify_code(preset: str, key: int) -> None:
    m = demo.mark_code(_code(), BITS, key, preset)
    assert m.code is not None and m.n_sites > 0 and m.codeword_length == 32
    v = demo.verify_code(m.code, key, preset, "deepseek_coder_6p7b", BITS)
    assert v.status == "OK" and v.detected is True
    assert v.score is not None and v.threshold == demo.PRESETS[preset].thresholds[v.model]
    assert v.score >= v.threshold and v.agreement == v.n_votes
    rows = demo.site_rows(m.code, key, preset)
    assert len(rows) == v.n_votes
    _assert_no_key(m, key)
    _assert_no_key(v, key)
    for r in rows:
        _assert_no_key(r, key)


def test_verify_without_message_has_no_score(key: int) -> None:
    m = demo.mark_code(_code(), BITS, key, "mcss_main")
    assert m.code is not None
    v = demo.verify_code(m.code, key, "mcss_main", demo.MODELS[0])
    assert v.status == "OK" and v.score is None and v.detected is None and v.threshold is None


@pytest.mark.parametrize(
    "code, reason",
    [("def f(:\n    pass\n", "syntax_error"), ("import os\n", "no_sites"), ("  \n", "empty")],
)
def test_failures_have_readable_reasons(code: str, reason: str, key: int) -> None:
    m = demo.mark_code(code, BITS, key, "multimark_prudent")
    assert (m.status, m.reason, m.code) == ("FAILED", reason, None)
    v = demo.verify_code(code, key, "multimark_prudent", demo.MODELS[0], BITS)
    assert (v.status, v.reason, v.detected) == ("FAILED", reason, False)
    assert demo.explain(reason) == demo.REASON_TEXT[reason]
    _assert_no_key(m, key)
    _assert_no_key(v, key)


def test_parse_hex_message() -> None:
    assert demo.parse_hex_message("ABCDEF") == BITS
    assert demo.parse_hex_message("0xabcdef") == BITS
    assert demo.parse_hex_message("1") == "0" * 23 + "1"
    for bad in ("", "1234567", "xyz", "0x"):
        with pytest.raises(demo.DemoError):
            demo.parse_hex_message(bad)


def test_side_by_side_aligns_and_marks_changes() -> None:
    a = "x = 1\ny = 2\nz = 3\n"
    b = "x = 1\ny = 20\nw = 0\nz = 3\n"
    rows = demo.side_by_side(a, b)
    assert [(r.left_no, r.right_no, r.tag) for r in rows] == [
        (1, 1, "equal"), (2, 2, "replace"), (None, 3, "replace"), (3, 4, "equal")
    ]  # fmt: skip
    left, right = demo.diff_html(rows, "left"), demo.diff_html(rows, "right")
    assert left.count('<div style="background:') == right.count('<div style="background:') == 4
    assert demo.DIFF_BG["left"] in left and demo.DIFF_BG["right"] in right
    assert "http" not in left + right  # nessuna risorsa esterna


def test_diff_html_escapes_code() -> None:
    rows = demo.side_by_side("a = '<b>'\n", "a = '<i>'\n")
    assert "&lt;i&gt;" in demo.diff_html(rows, "right") and "<i>" not in demo.diff_html(
        rows, "right"
    )


# ---------------------------------------------------------------------------- avvio della pagina
def test_web_without_streamlit_prints_how_to_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], key: int
) -> None:
    real = importlib.util.find_spec

    def fake(name: str, *a: Any) -> Any:
        return None if name == "streamlit" else real(name, *a)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    assert demo.main(["web"]) == 2
    assert 'pip install "multimark[demo]"' in capsys.readouterr().err


def test_web_command_is_local_and_keyless(key: int, tmp_path: Path) -> None:
    cmd = demo.web_command("127.0.0.1", 8765)
    assert cmd[1:4] == ["-m", "streamlit", "run"] and cmd[4].endswith("demo_web.py")
    joined = " ".join(cmd)
    assert "--server.address 127.0.0.1" in joined and "--server.port 8765" in joined
    assert "--browser.gatherUsageStats false" in joined
    f = tmp_path / "k.txt"
    f.write_text(str(key), encoding="utf-8")
    env = demo.web_env(f, demo.DEFAULT_KEY_ENV)
    assert env[demo.WEB_KEY_FILE_ENV] == str(f.resolve())
    for name, value in env.items():
        if name != demo.DEFAULT_KEY_ENV:  # la variabile della chiave è già nell'ambiente
            assert str(key) not in value
    for form in _key_forms(key):
        assert form not in joined


def test_web_defaults() -> None:
    args = demo.build_parser().parse_args(["web"])
    assert (args.host, args.port) == ("127.0.0.1", 8765)
