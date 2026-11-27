"""Pagina web del dimostratore (P7.d), con Streamlit (extra ``[demo]``).

Si avvia con ``multimark-demo web`` (``streamlit run`` su ``127.0.0.1:8765``). Tutto il calcolo è in
``multimark.cli.demo`` (``mark_code``, ``verify_code``, ``side_by_side``, ``diff_html``): qui c'è
solo la parte Streamlit. Streamlit si importa solo in questo file, quindi la libreria e wm-bench
non ne dipendono.

- La chiave si legge solo lato server, una volta (``st.cache_resource``), dal file indicato da
  ``multimark-demo web --key-file`` (variabile ``MULTIMARK_DEMO_KEY_FILE``) o dalla variabile
  d'ambiente della chiave (``MULTIMARK_KEY`` o ``--key-env``). Non va mai in ``st.session_state``,
  non si mostra e non si stampa: ``ServerKey`` la nasconde anche in ``repr``.
- ``st.session_state`` tiene solo codice originale, codice marcato e ultimi risultati (che non
  contengono la chiave).
- Nessuna risorsa esterna: niente font, immagini o icone da URL (niente emoji, che Streamlit
  scaricherebbe come favicon).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import streamlit as st

from multimark.cli import demo


@dataclass(frozen=True)
class ServerKey:
    """Chiave tenuta solo nella memoria del server; ``repr`` non la mostra."""

    value: int = field(repr=False)

    def __repr__(self) -> str:
        return "ServerKey(<hidden>)"

    __str__ = __repr__


@dataclass(frozen=True)
class Resources:
    presets: dict[str, demo.Preset]
    key: Optional[ServerKey]
    key_error: Optional[str]


@st.cache_resource(show_spinner=False)
def load_resources(key_file: Optional[str], key_env: str) -> Resources:
    """Preimpostazioni congelate e chiave, caricate una sola volta per processo."""
    try:
        key = demo.read_key(Path(key_file) if key_file else None, key_env)
    except demo.DemoError as exc:
        return Resources(dict(demo.PRESETS), None, str(exc))
    return Resources(dict(demo.PRESETS), ServerKey(key), None)


def _on_upload() -> None:
    up = st.session_state.get("upload")
    if up is not None:
        st.session_state["original_input"] = up.getvalue().decode("utf-8-sig", errors="replace")
        st.session_state["filename"] = up.name


def _sidebar(res: Resources) -> tuple[str, str, Optional[str]]:
    sb = st.sidebar
    sb.header("Configurazione")
    preset = sb.selectbox(
        "Preimpostazione (congelata in P6)",
        list(res.presets),
        index=list(res.presets).index("multimark_prudent"),
        key="preset",
    )
    p = res.presets[preset]
    sb.caption(f"metodo {p.method}, config_hash {p.config_hash}")
    model = sb.selectbox("Modello per la soglia", list(demo.MODELS), key="model")
    sb.caption(f"soglia congelata τ = {p.thresholds[model]:.4f}")
    sb.selectbox("Linguaggio", ["Python"], disabled=True, key="language",
                 help="Il metodo marca solo codice Python.")  # fmt: skip
    text = sb.text_input("Messaggio (esadecimale, 24 bit)", value="ABCDEF", key="message_hex")
    try:
        message: Optional[str] = demo.parse_hex_message(text)
        sb.caption(f"bit: {message}")
    except demo.DemoError as exc:
        sb.warning(f"Messaggio non valido: {exc}.")
        message = None
    return preset, model, message


def _show_mark(outcome: demo.MarkOutcome) -> None:
    if outcome.code is None:
        st.warning(demo.explain(outcome.reason))
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Siti trovati", outcome.n_sites)
    c2.metric("Bit inseriti", f"{outcome.n_sites} / {outcome.codeword_length}")
    c3.metric("Variabili rinominate", outcome.n_renamed)
    if outcome.status == "PARTIAL":
        st.info(
            f"Inserimento parziale: {outcome.n_sites} bit della parola di codice su "
            f"{outcome.codeword_length}. Il marchio si rileva lo stesso; la decodifica del "
            "messaggio può restare ambigua."
        )
    if outcome.by_channel:
        st.caption(
            "Siti per canale: " + ", ".join(f"{c} {n}" for c, n in outcome.by_channel.items())
        )
    rows = demo.side_by_side(st.session_state.get("original", ""), outcome.code)
    left, right = st.columns(2)
    left.markdown("**Originale**")
    left.markdown(demo.diff_html(rows, "left"), unsafe_allow_html=True)
    right.markdown("**Marcato**")
    right.markdown(demo.diff_html(rows, "right"), unsafe_allow_html=True)
    stem = Path(st.session_state.get("filename") or "codice.py").stem
    st.download_button(
        "Scarica il file marcato",
        data=outcome.code.encode("utf-8"),
        file_name=f"{stem}{demo.MARKED_SUFFIX}.py",
        mime="text/x-python",
        key="download",
    )


def _show_verify(outcome: demo.VerifyOutcome) -> None:
    if outcome.status != "OK":
        st.warning(demo.explain(outcome.reason))
        return
    if outcome.detected:
        st.success("Marchio rilevato.")
    else:
        st.error("Marchio non rilevato.")
    if outcome.score is not None and outcome.threshold is not None:
        c1, c2, c3 = st.columns(3)
        margin = outcome.score - outcome.threshold
        c1.metric("Punteggio", f"{outcome.score:.3f}", delta=f"{margin:+.3f} rispetto alla soglia")
        c2.metric(f"Soglia congelata ({outcome.model})", f"{outcome.threshold:.3f}")
        c3.metric("Siti letti", outcome.n_votes)
    expected = demo.bits_hex(outcome.expected) if outcome.expected else "—"
    decoded = demo.bits_hex(outcome.decoded) if outcome.decoded else "nessuno"
    st.markdown(
        f"- Messaggio atteso: `{expected}`\n"
        f"- Messaggio estratto: `{decoded}` (decodifica {outcome.decode_status}, "
        f"{outcome.n_erasures} bit cancellati)\n"
        f"- Bit del messaggio corretti: {outcome.bits_correct} / {demo.MESSAGE_BITS}"
    )


def page() -> None:
    st.set_page_config(page_title="MultiMark, dimostratore", layout="wide")
    res = load_resources(os.environ.get(demo.WEB_KEY_FILE_ENV),
                         os.environ.get(demo.WEB_KEY_ENV_ENV, demo.DEFAULT_KEY_ENV))  # fmt: skip
    st.title("MultiMark: watermark multi-bit post-hoc per codice Python")
    if res.key is None:
        st.warning(f"Chiave non disponibile sul server: {res.key_error}. Avvia la pagina con "
                   "`multimark-demo web --key-file FILE` o imposta MULTIMARK_KEY.")  # fmt: skip
        return
    key = res.key.value
    preset, model, message = _sidebar(res)

    st.file_uploader("Carica un file Python", type=["py"], key="upload", on_change=_on_upload)
    original = st.text_area("Codice originale", height=260, key="original_input")
    if st.button("Inserisci marchio", key="mark_btn", disabled=message is None, type="primary"):
        try:
            outcome = demo.mark_code(original, message or "", key, preset)
        except Exception as exc:  # avviso leggibile, mai una traccia
            st.session_state.pop("mark", None)
            st.warning(f"Inserimento non riuscito: {type(exc).__name__}: {exc}")
        else:
            st.session_state["original"] = demo.strip_bom(original)
            st.session_state["mark"] = outcome
            st.session_state["marked_edit"] = outcome.code or ""
            st.session_state.pop("verify", None)
    if "mark" in st.session_state:
        _show_mark(st.session_state["mark"])

    st.subheader("Verifica")
    marked = st.text_area("Codice da verificare (modificabile)", height=260, key="marked_edit")
    if st.button("Verifica", key="verify_btn", disabled=message is None):
        try:
            st.session_state["verify"] = demo.verify_code(marked, key, preset, model, message)
        except Exception as exc:
            st.session_state.pop("verify", None)
            st.warning(f"Verifica non riuscita: {type(exc).__name__}: {exc}")
    if "verify" in st.session_state:
        _show_verify(st.session_state["verify"])


page()
