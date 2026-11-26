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

La chiave (intero di 64 bit, decimale o ``0x…``) si legge da un file (``--key-file``) o da una
variabile d'ambiente (``--key-env``, default ``MULTIMARK_KEY``), mai dalla riga di comando in
chiaro; un file di chiave dentro il repository viene rifiutato.

Il dimostratore usa solo l'API pubblica della libreria (``Config``, ``embed``, ``detect``): nessuna
logica del metodo è qui. Esempi d'uso in ``README.md`` (sezione «Dimostratore»).
"""

from __future__ import annotations

import argparse
import difflib
import os
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


# ---------------------------------------------------------------------------- file
def marked_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{MARKED_SUFFIX}{source.suffix or '.py'}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
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
    res = embed(code, message, key, preset.config())
    ex = res.extra
    print(f"preset   {args.preset} ({preset.method}, config_hash {preset.config_hash})", file=out)
    print(f"message  {bits_hex(message)}", file=out)
    print(f"status   {res.status}" + (f" ({res.reason})" if res.reason else ""), file=out)
    if "n_sites" in ex:
        by = {c: n for c, n in ex["n_sites_by_channel"].items() if n}
        print(f"sites    {ex['n_sites']} bits written of {ex['codeword_length']} "
              f"(codeword); by channel {by}", file=out)  # fmt: skip
        print(f"renamed  {ex.get('n_renamed', 0)} variables; skipped sites "
              f"{ex.get('skipped_sites', 0)}", file=out)  # fmt: skip
    if res.status == "FAILED":
        print("nothing written: the code cannot carry the mark", file=out)
        return 1
    _write_new(target, res.code)
    print(f"written  {target}", file=out)
    return 0


def _detect(code: str, key: int, preset: Preset, message: Optional[str]) -> Any:
    # Il messaggio atteso serve solo al punteggio: voti, siti e decodifica aperta non ne dipendono,
    # quindi senza --message si passa un messaggio qualsiasi e il punteggio non si mostra.
    expected = message if message is not None else "0" * MESSAGE_BITS
    return detect(code, expected, key, preset.config(), registry_sizes=(1,), method=preset.method)


def cmd_verify(args: argparse.Namespace, out: Any) -> int:
    preset = PRESETS[args.preset]
    key = read_key(args.key_file, args.key_env)
    message = parse_message(args.message) if args.message is not None else None
    res = _detect(_read(args.file), key, preset, message)
    ex = res.extra
    print(f"preset    {args.preset} ({preset.method}, config_hash {preset.config_hash})", file=out)
    print(f"status    {res.status}" + (f" ({res.reason})" if res.reason else ""), file=out)
    if res.status != "OK":
        print("detected  no", file=out)
        return 1
    print(f"sites     {ex['n_sites']} ({ex['n_votes']} votes)", file=out)
    decoded = res.decoded_message
    print(f"decoded   {bits_hex(decoded) if decoded else 'none'} ({ex['decode_status']}, "
          f"{ex['n_erasures']} erased bits)", file=out)  # fmt: skip
    if message is None:
        print("score     needs the expected message (--message)", file=out)
        return 0
    tau = preset.thresholds[args.model]
    hit = res.score is not None and res.score >= tau
    print(f"expected  {bits_hex(message)}", file=out)
    print(f"agreement {ex['agreement']:g} of {ex['n_votes']}; bits correct {ex['bits_correct']}"
          f"/{MESSAGE_BITS}", file=out)  # fmt: skip
    print(f"score     {res.score:.4f} (-log10 P[Bin(N, 1/2) >= A])", file=out)
    print(f"threshold {tau:.4f} (frozen, {args.model})", file=out)
    print(f"detected  {'yes' if hit else 'no'}", file=out)
    return 0 if hit else 1


def cmd_show(args: argparse.Namespace, out: Any) -> int:
    preset = PRESETS[args.preset]
    key = read_key(args.key_file, args.key_env)
    marked_file = args.marked or marked_path(args.file)
    original, marked = _read(args.file), _read(marked_file)
    res = _detect(marked, key, preset, None)
    sites = res.extra.get("sites") or []
    print(f"preset {args.preset}; sites read in {marked_file}: {res.extra.get('n_sites', 0)}",
          file=out)  # fmt: skip
    print(f"{'function':<24} {'channel':<20} {'rank':>4} {'bit':>3}", file=out)
    for fid, _n_params, channel, rank, _value_read, vote in sites:
        bit = "-" if vote is None else str(vote)
        print(f"{str(fid):<24} {channel:<20} {rank!s:>4} {bit:>3}", file=out)
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        marked.splitlines(keepends=True),
        fromfile=str(args.file),
        tofile=str(marked_file),
    )
    print("", file=out)
    out.writelines(line if line.endswith("\n") else line + "\n" for line in diff)
    return 0


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="multimark-demo", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("file", type=Path, help="Python file (the original for mark and show)")
        sp.add_argument("--preset", choices=sorted(PRESETS), default="multimark_prudent")
        sp.add_argument("--key-file", type=Path, help="file with the key (outside the repository)")
        sp.add_argument(
            "--key-env",
            default=DEFAULT_KEY_ENV,
            help=f"environment variable with the key (default {DEFAULT_KEY_ENV})",
        )

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
