"""Pagina Streamlit del dimostratore (``multimark/cli/demo_web.py``) con ``streamlit.testing``:
inserimento, verifica, errore di sintassi come avviso, chiave mai nella pagina né in
``st.session_state``. Saltati se Streamlit non c'è (extra ``[demo]``).

Nessuna chiave è scritta qui: ogni test ne genera una a caso."""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from multimark.cli import demo  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_functions.jsonl"
TIMEOUT = 60


def _code() -> str:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    return str(rows[0]["code"]) + "\n\n" + str(rows[1]["code"])


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    value = secrets.randbits(64)
    monkeypatch.setenv(demo.DEFAULT_KEY_ENV, str(value))
    monkeypatch.delenv(demo.WEB_KEY_FILE_ENV, raising=False)
    monkeypatch.delenv(demo.WEB_KEY_ENV_ENV, raising=False)
    st.cache_resource.clear()  # la chiave cambia a ogni test
    yield value
    st.cache_resource.clear()


def _app() -> AppTest:
    at = AppTest.from_file(str(demo.WEB_SCRIPT), default_timeout=TIMEOUT)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at: AppTest) -> str:
    """Tutto ciò che la pagina mostra, più lo stato di sessione."""
    parts: list[Any] = []
    for kind in ("markdown", "caption", "metric", "success", "error", "warning", "info",
                 "text_area", "text_input", "title", "subheader", "header"):  # fmt: skip
        for el in getattr(at, kind):
            parts.append(getattr(el, "value", None))
            parts.append(getattr(el, "label", None))
            parts.append(getattr(el, "delta", None))
    for k in at.session_state.filtered_state:
        parts.append(k)
        parts.append(repr(at.session_state[k]))
    return "\n".join(str(p) for p in parts)


def _assert_no_key(at: AppTest, key: int) -> None:
    text = _texts(at)
    for form in (str(key), hex(key), f"{key:x}", f"{key:016x}"):
        assert form not in text


def test_mark_then_verify(key: int) -> None:
    at = _app()
    at.text_area(key="original_input").input(_code())
    at.button(key="mark_btn").click()
    at.run()
    assert not at.exception and not at.warning
    outcome = at.session_state["mark"]
    assert isinstance(outcome, demo.MarkOutcome) and outcome.code is not None
    assert at.text_area(key="marked_edit").value == outcome.code
    labels = {m.label: m.value for m in at.metric}
    assert labels["Siti trovati"] == str(outcome.n_sites)
    diff = [m.value for m in at.markdown if demo.DIFF_BG["right"] in m.value]
    assert len(diff) == 1

    at.button(key="verify_btn").click()
    at.run()
    assert not at.exception
    assert [s.value for s in at.success] == ["Marchio rilevato."]
    labels = {m.label: m.value for m in at.metric}
    tau = demo.PRESETS["multimark_prudent"].thresholds[demo.MODELS[0]]
    assert labels[f"Soglia congelata ({demo.MODELS[0]})"] == f"{tau:.3f}"
    assert float(labels["Punteggio"]) >= tau
    _assert_no_key(at, key)


def test_edited_code_is_not_detected(key: int) -> None:
    at = _app()
    at.text_area(key="original_input").input(_code())
    at.button(key="mark_btn").click()
    at.run()
    at.text_area(key="marked_edit").input(_code())  # di nuovo l'originale, non marcato
    at.button(key="verify_btn").click()
    at.run()
    v = at.session_state["verify"]
    assert isinstance(v, demo.VerifyOutcome)
    if v.detected:
        assert [s.value for s in at.success] == ["Marchio rilevato."]
    else:
        assert [e.value for e in at.error] == ["Marchio non rilevato."]
    _assert_no_key(at, key)


def test_syntax_error_is_a_warning(key: int) -> None:
    at = _app()
    at.text_area(key="original_input").input("def f(:\n    return 1\n")
    at.button(key="mark_btn").click()
    at.run()
    assert not at.exception
    assert [w.value for w in at.warning] == [demo.REASON_TEXT["syntax_error"]]
    at.text_area(key="marked_edit").input("x = (\n")
    at.button(key="verify_btn").click()
    at.run()
    assert not at.exception
    assert demo.REASON_TEXT["syntax_error"] in [w.value for w in at.warning]
    _assert_no_key(at, key)


def test_no_sites_is_a_warning(key: int) -> None:
    at = _app()
    at.text_area(key="original_input").input("import os\n")
    at.button(key="mark_btn").click()
    at.run()
    assert [w.value for w in at.warning] == [demo.REASON_TEXT["no_sites"]]


def test_bad_message_disables_the_buttons(key: int) -> None:
    at = _app()
    at.text_input(key="message_hex").input("XYZ")
    at.run()
    assert at.button(key="mark_btn").disabled and at.button(key="verify_btn").disabled
    assert at.sidebar.warning


def test_missing_key_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(demo.DEFAULT_KEY_ENV, raising=False)
    monkeypatch.delenv(demo.WEB_KEY_FILE_ENV, raising=False)
    st.cache_resource.clear()
    try:
        at = _app()
        assert at.warning and "Chiave non disponibile" in at.warning[0].value
        assert not at.button
    finally:
        st.cache_resource.clear()


def test_key_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = secrets.randbits(64)
    f = tmp_path / "k.txt"
    f.write_text(str(value), encoding="utf-8")
    monkeypatch.delenv(demo.DEFAULT_KEY_ENV, raising=False)
    monkeypatch.setenv(demo.WEB_KEY_FILE_ENV, str(f))
    st.cache_resource.clear()
    try:
        at = _app()
        at.text_area(key="original_input").input(_code())
        at.button(key="mark_btn").click()
        at.run()
        outcome = at.session_state["mark"]
        assert outcome.code == demo.mark_code(_code(), outcome.message, value, outcome.preset).code
        _assert_no_key(at, value)
    finally:
        st.cache_resource.clear()
