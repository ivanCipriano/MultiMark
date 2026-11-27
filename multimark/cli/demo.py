"""Dimostratore da riga di comando (PIPELINE_metodo.md v1.3.18, P7.d; decisione N).

Tre sottocomandi su un file Python, con una delle tre configurazioni congelate in P6 come
preimpostazione (``--preset``):

- ``mark``: inserisce un messaggio di 24 bit e scrive il file marcato accanto all'originale
  (``<nome>.marked.py``, o ``--output``); non sovrascrive mai l'originale né un file esistente.
- ``verify``: rileva il marchio; con il messaggio atteso (``--message``) dà il punteggio
  principale (``N_reg = 1``), la soglia congelata della configurazione e del modello
  (``--model``) e la decisione ``score >= τ``; in ogni caso il messaggio della decodifica aperta,
  se c'è.
- ``show``: elenca i siti letti nel file marcato (funzione, canale, rango, bit) e stampa il diff
  fra originale e marcato.
- ``web``: avvia in locale (``127.0.0.1:8765``) la pagina Streamlit ``demo_web.py`` (extra
  ``[demo]``), con le stesse funzioni di calcolo (``mark_code``, ``verify_code``, ``side_by_side``).

I file si leggono in ``utf-8-sig``: il BOM che PowerShell scrive con ``Out-File -Encoding utf8``
non rende il codice illeggibile.

La chiave (intero di 64 bit, decimale o ``0x…``) si legge da un file (``--key-file``) o da una
variabile d'ambiente (``--key-env``, default ``MULTIMARK_KEY``), mai dalla riga di comando in
chiaro; un file di chiave dentro il repository viene rifiutato.

Il dimostratore usa solo l'API pubblica della libreria (``Config``, ``embed``, ``detect``): nessuna
logica del metodo è qui. Esempi d'uso in ``README.md`` (sezione «Dimostratore»).
"""

from __future__ import annotations

import argparse
import difflib
import html
import importlib.util
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from multimark.config import Config
from multimark.detect import detect
from multimark.embed import embed

DEFAULT_KEY_ENV = "MULTIMARK_KEY"
MESSAGE_BITS = 24
MARKED_SUFFIX = ".marked"
# Repository della libreria (radice con ``.git``): i file di chiave lì dentro sono rifiutati.
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Preset:
    """Configurazione congelata in P6 (wm-bench ``configs/freeze/posthoc.yaml``, libreria
    ``b2b6c18``) con le soglie congelate per modello (``docs/milestone_logs/P6_freeze_*.txt`` di
    wm-bench, punteggio principale ``N_reg = 1``, decisione ``score >= τ``)."""

    method: str
    config_hash: str
    hparams: dict[str, Any]
    thresholds: dict[str, float]

    def config(self) -> Config:
        return Config(**self.hparams)


# Iperparametri nativi (campi di ``Config``) dei tre punti congelati, come li passa l'adapter di
# wm-bench con libreria b2b6c18 (``message_bits`` = 24; ``registry_seed`` serve solo per le esche,
# che il dimostratore non usa).
_MCSS = {
    "t": 2,
    "message_bits": 24,
    "linking": "positional",
    "mask": "off",
    "canonical": "paper",
    "names_variant": "V1",
    "names_proposer": "static",
    "names_include_params": True,
    "channels": "mcss8",
    "names_module_level": True,
    "code_matrix": "random",
    "names_single_letter": "extend_except_loop",
    "names_bits_per_name": 1,
    "canonical_same_kind": "off",
    "voting": "simple",
    "channel_weights": None,
}
_MULTIMARK_BASE = {
    "t": 2,
    "message_bits": 24,
    "linking": "function_channel",
    "mask": "on",
    "canonical": "kind",
    "names_variant": "V2",
    "names_proposer": "static",
    "names_include_params": False,
    "channels": "extended",
    "names_module_level": True,
    "code_matrix": "dmin4",
    "names_single_letter": "exclude",
    "names_bits_per_name": 1,
    "canonical_same_kind": "off",
    "voting": "simple",
    "channel_weights": None,
}
_PRUDENT = {**_MULTIMARK_BASE, "names_bits_per_name": 2}
_HIGH_CAPACITY = {
    **_PRUDENT,
    "names_single_letter": "extend_except_loop",
    "canonical_same_kind": "binding_order",
    "names_include_params": True,
}

PRESETS: dict[str, Preset] = {
    "mcss_main": Preset(
        "mcss",
        "1d3087c73439",
        _MCSS,
        {"qwen25_coder_7b": 1.2621119296336116, "deepseek_coder_6p7b": 1.2621119296336116},
    ),
    "multimark_prudent": Preset(
        "multimark",
        "e52b040770df",
        _PRUDENT,
        {"qwen25_coder_7b": 1.2274243995713552, "deepseek_coder_6p7b": 1.3358981437945303},
    ),
    "multimark_high_capacity": Preset(
        "multimark",
        "3fed1f1c1e24",
        _HIGH_CAPACITY,
        {"qwen25_coder_7b": 1.5423220813600191, "deepseek_coder_6p7b": 1.6104640538603547},
    ),
}
MODELS = ("qwen25_coder_7b", "deepseek_coder_6p7b")


class DemoError(Exception):
    """Errore d'uso: messaggio su stderr e codice di uscita 2."""


# ---------------------------------------------------------------------------- chiave e messaggio
def parse_int(text: str, what: str) -> int:
    text = text.strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    except ValueError:
        raise DemoError(f"{what} is not an integer (decimal or 0x hex)") from None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def read_key(key_file: Optional[Path], key_env: str, repo_root: Path = REPO_ROOT) -> int:
    """Chiave dal file (se dato) o dalla variabile d'ambiente; mai stampata."""
    if key_file is not None:
        path = key_file.expanduser().resolve()
        if (repo_root / ".git").exists() and _inside(path, repo_root.resolve()):
            raise DemoError(f"refusing a key file inside the repository ({repo_root})")
        if not path.is_file():
            raise DemoError(f"key file not found: {key_file}")
        key = parse_int(path.read_text(encoding="utf-8"), "the key file content")
    else:
        value = os.environ.get(key_env)
        if not value:
            raise DemoError(f"no key: pass --key-file or set the environment variable {key_env}")
        key = parse_int(value, f"the environment variable {key_env}")
    if not 0 <= key < 2**64:
        raise DemoError("the key must be an unsigned 64-bit integer")
    return key


def parse_message(text: str) -> str:
    """Messaggio di 24 bit: stringa di 0/1 lunga 24, ``0x`` con al più 6 cifre esadecimali o
    intero decimale in ``[0, 2^24)``; restituisce la stringa di bit."""
    t = text.strip().replace("_", "")
    if len(t) == MESSAGE_BITS and set(t) <= {"0", "1"}:
        return t
    value = parse_int(t, "the message")
    if not 0 <= value < 2**MESSAGE_BITS:
        raise DemoError(f"the message must fit in {MESSAGE_BITS} bits")
    return format(value, f"0{MESSAGE_BITS}b")


def bits_hex(bits: str) -> str:
    return f"{bits} (0x{int(bits, 2):06x})"


# ---------------------------------------------------------------------------- calcolo
# Funzioni pure, senza I/O né Streamlit, usate dalla riga di comando e dalla pagina web
# (``demo_web.py``). I risultati non contengono mai la chiave.
BOM = "﻿"


def strip_bom(code: str) -> str:
    """Toglie il BOM iniziale (``Out-File -Encoding utf8`` su Windows lo scrive)."""
    return code[1:] if code.startswith(BOM) else code


@dataclass(frozen=True)
class MarkOutcome:
    """Esito di ``mark_code``: ``code`` è il codice marcato (``None`` se l'inserimento fallisce)."""

    preset: str
    message: str
    status: str
    reason: Optional[str]
    code: Optional[str]
    n_sites: int
    codeword_length: Optional[int]
    by_channel: dict[str, int]
    n_renamed: int
    skipped_sites: int


@dataclass(frozen=True)
class VerifyOutcome:
    """Esito di ``verify_code``; punteggio, soglia e decisione solo con il messaggio atteso."""

    preset: str
    model: str
    status: str
    reason: Optional[str]
    n_sites: int
    n_votes: int
    decoded: Optional[str]
    decode_status: Optional[str]
    n_erasures: Optional[int]
    expected: Optional[str]
    agreement: Optional[float]
    bits_correct: Optional[int]
    score: Optional[float]
    threshold: Optional[float]
    detected: Optional[bool]


@dataclass(frozen=True)
class SiteRow:
    function: str
    channel: str
    rank: Optional[int]
    bit: Optional[int]


@dataclass(frozen=True)
class DiffRow:
    """Una riga del diff affiancato: numero e testo a sinistra (originale) e a destra (marcato);
    ``tag`` è ``equal``, ``replace``, ``delete`` o ``insert`` (``difflib.SequenceMatcher``)."""

    left_no: Optional[int]
    left: str
    right_no: Optional[int]
    right: str
    tag: str


def mark_code(code: str, message: str, key: int, preset_name: str) -> MarkOutcome:
    """Inserisce ``message`` (stringa di 24 bit) in ``code`` con la preimpostazione data."""
    code = strip_bom(code)
    if not code.strip():
        return MarkOutcome(preset_name, message, "FAILED", "empty", None, 0, None, {}, 0, 0)
    res = embed(code, message, key, PRESETS[preset_name].config())
    ex = res.extra
    return MarkOutcome(
        preset=preset_name,
        message=message,
        status=res.status,
        reason=res.reason,
        code=None if res.status == "FAILED" else res.code,
        n_sites=int(ex.get("n_sites") or 0),
        codeword_length=ex.get("codeword_length"),
        by_channel={c: n for c, n in (ex.get("n_sites_by_channel") or {}).items() if n},
        n_renamed=int(ex.get("n_renamed") or 0),
        skipped_sites=int(ex.get("skipped_sites") or 0),
    )


def _detect(code: str, key: int, preset: Preset, message: Optional[str]) -> Any:
    # Il messaggio atteso serve solo al punteggio: voti, siti e decodifica aperta non ne dipendono,
    # quindi senza messaggio si passa un messaggio qualsiasi e il punteggio non si mostra.
    expected = message if message is not None else "0" * MESSAGE_BITS
    return detect(code, expected, key, preset.config(), registry_sizes=(1,), method=preset.method)


def verify_code(
    code: str, key: int, preset_name: str, model: str, message: Optional[str] = None
) -> VerifyOutcome:
    """Rileva il marchio; con ``message`` (24 bit) punteggio contro la soglia congelata."""
    preset = PRESETS[preset_name]
    code = strip_bom(code)
    if not code.strip():
        no = False if message is not None else None
        return VerifyOutcome(preset_name, model, "FAILED", "empty", 0, 0, None, None, None,
                             message, None, None, None, None, no)  # fmt: skip
    res = _detect(code, key, preset, message)
    ex = res.extra
    ok = res.status == "OK"
    scored = ok and message is not None
    tau = preset.thresholds[model] if message is not None else None
    score = res.score if scored else None
    detected: Optional[bool] = None
    if message is not None:
        detected = score is not None and tau is not None and score >= tau
    return VerifyOutcome(
        preset=preset_name,
        model=model,
        status=res.status,
        reason=res.reason,
        n_sites=int(ex.get("n_sites") or 0),
        n_votes=int(ex.get("n_votes") or 0),
        decoded=res.decoded_message if ok else None,
        decode_status=ex.get("decode_status") if ok else None,
        n_erasures=ex.get("n_erasures") if ok else None,
        expected=message,
        agreement=ex.get("agreement") if scored else None,
        bits_correct=ex.get("bits_correct") if scored else None,
        score=score,
        threshold=tau,
        detected=detected,
    )


def site_rows(code: str, key: int, preset_name: str) -> list[SiteRow]:
    """Siti letti in ``code``: funzione, canale (``names_b1`` = secondo bit di un nome), rango,
    bit votato (``None`` se il nome non si legge)."""
    res = _detect(strip_bom(code), key, PRESETS[preset_name], None)
    return [
        SiteRow(str(fid), str(channel), rank, vote)
        for fid, _n_params, channel, rank, _value_read, vote in res.extra.get("sites") or []
    ]


def side_by_side(original: str, marked: str) -> list[DiffRow]:
    """Diff riga per riga allineato per due colonne (righe mancanti come stringa vuota)."""
    a, b = original.splitlines(), marked.splitlines()
    rows: list[DiffRow] = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        for k in range(max(i2 - i1, j2 - j1)):
            i, j = i1 + k, j1 + k
            left_no, left = (i + 1, a[i]) if i < i2 else (None, "")
            right_no, right = (j + 1, b[j]) if j < j2 else (None, "")
            rows.append(DiffRow(left_no, left, right_no, right, tag))
    return rows


def unified_diff(original: str, marked: str, from_name: str, to_name: str) -> str:
    lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        marked.splitlines(keepends=True),
        fromfile=from_name,
        tofile=to_name,
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


# ---------------------------------------------------------------------------- testi della pagina
# Spiegazioni leggibili dei motivi di fallimento della libreria (pagina web: avvisi, non tracce).
REASON_TEXT: dict[str, str] = {
    "empty": "Il codice è vuoto: incolla del codice Python o carica un file.",
    "syntax_error": "Il codice non è Python valido (errore di sintassi): correggilo e riprova.",
    "no_sites": "Nel codice non c'è nessun sito su cui scrivere o leggere bit: è troppo corto o "
    "non ha costrutti marcabili (servono funzioni con variabili, confronti, assegnamenti).",
    "rewrite_mismatch": "La riscrittura non si rilegge in modo coerente: il codice non può "
    "portare il marchio con questa configurazione.",
}
MESSAGE_HEX_DIGITS = 6


def explain(reason: Optional[str]) -> str:
    return REASON_TEXT.get(reason or "", f"Operazione non riuscita ({reason}).")


def parse_hex_message(text: str) -> str:
    """Messaggio esadecimale della pagina (al più 6 cifre, ``0x`` facoltativo) → 24 bit."""
    t = text.strip().replace("_", "").replace(" ", "")
    t = t[2:] if t.lower().startswith("0x") else t
    if not t or len(t) > MESSAGE_HEX_DIGITS or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise DemoError(f"il messaggio deve avere da 1 a {MESSAGE_HEX_DIGITS} cifre esadecimali")
    return format(int(t, 16), f"0{MESSAGE_BITS}b")


DIFF_CSS = (
    "font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace; "
    "font-size: 0.82rem; line-height: 1.45; overflow-x: auto; white-space: pre; "
    "border: 1px solid rgba(128,128,128,0.35); border-radius: 6px; padding: 6px 0;"
)
DIFF_BG = {"left": "rgba(220, 70, 70, 0.22)", "right": "rgba(40, 170, 90, 0.22)"}


def diff_html(rows: Sequence[DiffRow], side: str) -> str:
    """Una colonna del diff affiancato in HTML (testo con escape, nessuna risorsa esterna): le
    righe cambiate hanno lo sfondo rosso a sinistra e verde a destra, le righe mancanti sono
    vuote così le due colonne restano allineate."""
    out = [f'<div style="{DIFF_CSS}">']
    for r in rows:
        no, text = (r.left_no, r.left) if side == "left" else (r.right_no, r.right)
        bg = DIFF_BG[side] if r.tag != "equal" and no is not None else "transparent"
        if r.tag != "equal" and no is None:
            bg = "rgba(128,128,128,0.10)"
        num = "" if no is None else str(no)
        out.append(
            f'<div style="background:{bg}; padding:0 8px;">'
            f'<span style="opacity:0.5; display:inline-block; width:3.2em; user-select:none;">'
            f"{num}</span>{html.escape(text) or '&nbsp;'}</div>"
        )
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------------------- file
def marked_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{MARKED_SUFFIX}{source.suffix or '.py'}")


def _read(path: Path) -> str:
    """Legge un file di codice; ``utf-8-sig`` toglie il BOM che PowerShell scrive con
    ``Out-File -Encoding utf8``."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise DemoError(f"file not found: {path}") from None


def _write_new(path: Path, text: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="") as f:
            f.write(text)
    except FileExistsError:
        raise DemoError(f"{path} exists: remove it or pass another --output") from None


# ---------------------------------------------------------------------------- sottocomandi
def cmd_mark(args: argparse.Namespace, out: Any) -> int:
    preset = PRESETS[args.preset]
    key = read_key(args.key_file, args.key_env)
    message = parse_message(args.message)
    code = _read(args.file)
    target = args.output or marked_path(args.file)
    if target.resolve() == args.file.resolve():
        raise DemoError("the marked file must not overwrite the original")
    res = mark_code(code, message, key, args.preset)
    print(f"preset   {args.preset} ({preset.method}, config_hash {preset.config_hash})", file=out)
    print(f"message  {bits_hex(message)}", file=out)
    print(f"status   {res.status}" + (f" ({res.reason})" if res.reason else ""), file=out)
    if res.codeword_length is not None:
        print(f"sites    {res.n_sites} bits written of {res.codeword_length} "
              f"(codeword); by channel {res.by_channel}", file=out)  # fmt: skip
        print(f"renamed  {res.n_renamed} variables; skipped sites {res.skipped_sites}", file=out)
    if res.code is None:
        print("nothing written: the code cannot carry the mark", file=out)
        return 1
    _write_new(target, res.code)
    print(f"written  {target}", file=out)
    return 0


def cmd_verify(args: argparse.Namespace, out: Any) -> int:
    preset = PRESETS[args.preset]
    key = read_key(args.key_file, args.key_env)
    message = parse_message(args.message) if args.message is not None else None
    res = verify_code(_read(args.file), key, args.preset, args.model, message)
    print(f"preset    {args.preset} ({preset.method}, config_hash {preset.config_hash})", file=out)
    print(f"status    {res.status}" + (f" ({res.reason})" if res.reason else ""), file=out)
    if res.status != "OK":
        print("detected  no", file=out)
        return 1
    print(f"sites     {res.n_sites} ({res.n_votes} votes)", file=out)
    decoded = bits_hex(res.decoded) if res.decoded else "none"
    print(f"decoded   {decoded} ({res.decode_status}, {res.n_erasures} erased bits)", file=out)
    if message is None or res.score is None or res.threshold is None:
        print("score     needs the expected message (--message)", file=out)
        return 0
    print(f"expected  {bits_hex(message)}", file=out)
    print(f"agreement {res.agreement:g} of {res.n_votes}; bits correct {res.bits_correct}"
          f"/{MESSAGE_BITS}", file=out)  # fmt: skip
    print(f"score     {res.score:.4f} (-log10 P[Bin(N, 1/2) >= A])", file=out)
    print(f"threshold {res.threshold:.4f} (frozen, {args.model})", file=out)
    print(f"detected  {'yes' if res.detected else 'no'}", file=out)
    return 0 if res.detected else 1


def cmd_show(args: argparse.Namespace, out: Any) -> int:
    key = read_key(args.key_file, args.key_env)
    marked_file = args.marked or marked_path(args.file)
    original, marked = _read(args.file), _read(marked_file)
    rows = site_rows(marked, key, args.preset)
    print(f"preset {args.preset}; sites read in {marked_file}: {len(rows)}", file=out)
    print(f"{'function':<24} {'channel':<20} {'rank':>4} {'bit':>3}", file=out)
    for r in rows:
        bit = "-" if r.bit is None else str(r.bit)
        print(f"{r.function:<24} {r.channel:<20} {r.rank!s:>4} {bit:>3}", file=out)
    print("", file=out)
    out.write(unified_diff(original, marked, str(args.file), str(marked_file)))
    return 0


# ---------------------------------------------------------------------------- pagina web
WEB_SCRIPT = Path(__file__).with_name("demo_web.py")
# Variabili d'ambiente con cui ``web`` dice alla pagina dove sta la chiave (mai la chiave stessa).
WEB_KEY_FILE_ENV = "MULTIMARK_DEMO_KEY_FILE"
WEB_KEY_ENV_ENV = "MULTIMARK_DEMO_KEY_ENV"
INSTALL_HINT = 'pip install "multimark[demo]"   (from a checkout: pip install -e ".[demo]")'


def web_command(host: str, port: int) -> list[str]:
    """``streamlit run`` della pagina, solo in locale e senza statistiche d'uso inviate fuori."""
    return [
        sys.executable, "-m", "streamlit", "run", str(WEB_SCRIPT),
        "--server.address", host,
        "--server.port", str(port),
        "--server.fileWatcherType", "none",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
        "--client.toolbarMode", "minimal",
    ]  # fmt: skip


def web_env(key_file: Optional[Path], key_env: str) -> dict[str, str]:
    """Ambiente del processo Streamlit: dove leggere la chiave, non la chiave."""
    env = dict(os.environ)
    env[WEB_KEY_ENV_ENV] = key_env
    env.pop(WEB_KEY_FILE_ENV, None)
    if key_file is not None:
        env[WEB_KEY_FILE_ENV] = str(key_file.expanduser().resolve())
    return env


def cmd_web(args: argparse.Namespace, out: Any) -> int:
    if importlib.util.find_spec("streamlit") is None:
        print(f"streamlit is not installed: {INSTALL_HINT}", file=sys.stderr)
        return 2
    read_key(args.key_file, args.key_env)  # errore subito se la chiave manca o non è valida
    print(f"page on http://{args.host}:{args.port} (Ctrl+C to stop)", file=out, flush=True)
    try:
        return subprocess.call(
            web_command(args.host, args.port), env=web_env(args.key_file, args.key_env)
        )
    except KeyboardInterrupt:
        return 0


# ---------------------------------------------------------------------------- parser
def _key_options(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--key-file", type=Path, help="file with the key (outside the repository)")
    sp.add_argument(
        "--key-env",
        default=DEFAULT_KEY_ENV,
        help=f"environment variable with the key (default {DEFAULT_KEY_ENV})",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="multimark-demo", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("file", type=Path, help="Python file (the original for mark and show)")
        sp.add_argument("--preset", choices=sorted(PRESETS), default="multimark_prudent")
        _key_options(sp)

    m = sub.add_parser("mark", help="embed a 24-bit message")
    common(m)
    m.add_argument("--message", required=True, help="24 bits of 0/1, 0x hex or decimal")
    m.add_argument("--output", type=Path, help=f"default: <name>{MARKED_SUFFIX}.py")
    m.set_defaults(func=cmd_mark)

    v = sub.add_parser("verify", help="detect the mark")
    common(v)
    v.add_argument("--message", help="expected message (needed for the score)")
    v.add_argument("--model", choices=MODELS, default=MODELS[0],
                   help="model whose frozen threshold is used")  # fmt: skip
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("show", help="list the sites and print the diff")
    common(s)
    s.add_argument("--marked", type=Path, help=f"default: <name>{MARKED_SUFFIX}.py")
    s.set_defaults(func=cmd_show)

    w = sub.add_parser("web", help="local web page (Streamlit, extra [demo])")
    _key_options(w)
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
    w.set_defaults(func=cmd_web)
    return p


def main(argv: Optional[Sequence[str]] = None, out: Any = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args, out or sys.stdout))
    except DemoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
