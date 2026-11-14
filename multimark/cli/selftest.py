"""Autovalidazione di P1 (PIPELINE_metodo.md §2 P1 passo 6, §4.4 punto 1).

Per ``--fragments`` frammenti sintetici (``multimark.synthetic``) e ``--keys`` chiavi, per i profili
``multimark`` e ``mcss``: inserimento, rilevazione e controlli.

- **Confronto**: ogni voto concorda con il messaggio, salvo le variabili senza candidato
  (``n_names_wrong``); quindi ``A = N`` e punteggio massimo ``N·log10 2``.
- **Decodifica**: con ``N ≥ B`` restituisce il messaggio quando tutte le ``B`` posizioni hanno un
  voto (con ``linking=positional`` è garantito; con il legame per funzione no, e allora le
  posizioni senza voto sono cancellazioni recuperabili fino a ``4t``); non restituisce **mai** un
  messaggio sbagliato. Con ``N < B`` dichiara cancellazioni.
- **Copertura**: frazione media di posizioni della parola di codice con almeno un voto, in
  funzione di ``N`` (``COVERAGE_N``: casi con ``N`` esatto e con ``|N − n| ≤ 2``), accanto al
  riferimento ``1 − (1 − 1/B)^N`` di posizioni scelte a caso in modo uniforme e indipendente.
- **Formattazione** (un frammento su cinque, prima chiave): ``black``, ``ruff format``,
  ``ruff check --fix``, aggiunta e rimozione di commenti; le letture devono restare identiche.
- **Tempo** di inserimento + rilevazione (registro 1, 16, 1024) su un file da ~100 righe.

Uso::

    python -m multimark.cli.selftest --fragments 500 --keys 100 \
        --workers 4 --log docs/milestone_logs/P1_selftest.txt
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import random
import shutil
import subprocess
import sys
import time
import tokenize
from collections import Counter
from collections.abc import Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Optional

from multimark import __version__
from multimark._astindex import AstIndex
from multimark.codec import ERASURE, encode
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import _majority, detect
from multimark.embed import embed
from multimark.layout import build_layout, read_votes
from multimark.prf import derive_seed
from multimark.synthetic import generate

PROFILES = {"multimark": multimark_base(), "mcss": mcss_profile()}
COVERAGE_N = (8, 13, 20, 32, 40, 56)
COVERAGE_WINDOW = 2


def fragment(seed: int) -> str:
    """Frammento ``seed``: metà grandi (≥ 32 siti attesi), metà piccoli; 1–3 funzioni."""
    rng = random.Random(derive_seed("p1-selftest-fragment", seed))
    big = seed % 2 == 0
    n_functions = rng.choice([1, 1, 2, 3])
    n_statements = rng.randint(28, 45) if big else rng.randint(3, 12)
    return generate(seed, n_statements, n_functions)


def readings(code: str, cfg: Config, key: int) -> list[tuple]:
    layout = build_layout(AstIndex.from_code(code), cfg, key)
    return [(v.slot.key, v.index, v.value) for v in read_votes(layout, key, cfg)]


def add_comments(code: str) -> str:
    lines = code.splitlines()
    out = ["# commento iniziale"]
    for i, line in enumerate(lines):
        out.append(f"{line}  # c{i}" if line.strip() else line)
    return "\n".join(out) + "\n"


def strip_comments(code: str) -> str:
    tokens = [t for t in tokenize.generate_tokens(io.StringIO(code).readline)
              if t.type != tokenize.COMMENT]  # fmt: skip
    return tokenize.untokenize(tokens)


def _ruff(args: list[str], code: str) -> Optional[str]:
    exe = os.environ.get("MULTIMARK_RUFF") or shutil.which("ruff")
    if exe is None:
        return None
    proc = subprocess.run(
        [exe, *args, "--stdin-filename", "frag.py", "-"],
        input=code, capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    return proc.stdout if proc.stdout.strip() else None


def formatters() -> dict[str, Any]:
    out: dict[str, Any] = {"add_comments": add_comments,
                           "strip_comments": lambda c: strip_comments(add_comments(c))}  # fmt: skip
    try:
        import black

        out["black"] = lambda c: black.format_str(c, mode=black.Mode())
    except ImportError:
        pass
    if (os.environ.get("MULTIMARK_RUFF") or shutil.which("ruff")) is not None:
        out["ruff_format"] = lambda c: _ruff(["format"], c)
        out["ruff_check_fix"] = lambda c: _ruff(["check", "--fix", "--exit-zero", "-q"], c)
    return out


def run_case(task: tuple[str, int, int]) -> dict[str, Any]:
    profile, frag_seed, key_index = task
    cfg = PROFILES[profile]
    method = "mcss" if profile == "mcss" else "multimark"
    code = fragment(frag_seed)
    rng = random.Random(derive_seed("p1-selftest-key", frag_seed, key_index))
    key = rng.getrandbits(31)
    msg = [rng.getrandbits(1) for _ in range(cfg.message_bits)]
    r = embed(code, msg, key, cfg)
    out: dict[str, Any] = {"profile": profile, "status": r.status, "reason": r.reason}
    if r.status == "FAILED":
        return out
    d = detect(r.code, msg, key, cfg, registry_sizes=(1,), method=method)
    n_votes = d.extra["n_votes"]
    wrong = r.extra["n_names_wrong"]
    layout = build_layout(AstIndex.from_code(r.code), cfg, key)
    tally = _majority(read_votes(layout, key, cfg), cfg.codeword_length)
    cw = encode(msg, cfg.t)
    n_erased = sum(v == ERASURE for v in tally)
    n_errors = sum(v != ERASURE and v != c for v, c in zip(tally, cw))
    n_covered = len({i for s in layout.slots for i in s.indices})
    covered = n_covered == cfg.codeword_length
    decoded = d.decoded_message
    expected = "".join(map(str, msg))
    out.update(
        n_sites=r.extra["n_sites"],
        n_votes=n_votes,
        skipped=r.extra["skipped_sites"],
        wrong_names=wrong,
        no_candidate=r.extra["n_names_no_candidate"],
        n_erased=n_erased,
        n_errors=n_errors,
        within_limit=2 * n_errors + n_erased <= 2 * cfg.t,
        agreement_ok=d.extra["agreement"] == n_votes - wrong,
        big=r.extra["n_sites"] >= cfg.codeword_length,
        covered=covered,
        coverage=n_covered / cfg.codeword_length,
        decode_status=d.extra["decode_status"],
        decoded_ok=decoded == expected,
        decoded_wrong=decoded is not None and decoded != expected,
        erasures=d.extra["n_erasures"],
    )
    if key_index == 0 and frag_seed % 5 == 0:
        base = readings(r.code, cfg, key)
        inv: dict[str, Optional[bool]] = {}
        for name, fmt in formatters().items():
            new = fmt(r.code)
            inv[name] = None if new is None else readings(new, cfg, key) == base
        out["invariance"] = inv
    return out


def timing(repeats: int = 5) -> dict[str, float]:
    code = generate(424242, 60, 1)
    out: dict[str, float] = {"lines": float(len(code.splitlines()))}
    for profile, cfg in PROFILES.items():
        method = "mcss" if profile == "mcss" else "multimark"
        t0 = time.perf_counter()
        for k in range(repeats):
            msg = [(k >> i) & 1 for i in range(24)]
            r = embed(code, msg, 1000 + k, cfg)
            detect(r.code, msg, 1000 + k, cfg, registry_seed=1, method=method)
        out[profile] = (time.perf_counter() - t0) / repeats
    return out


def limit_lines(ok: list[dict[str, Any]], t: int) -> list[str]:
    """Messaggi sbagliati rispetto al limite ``2e + f <= 2t`` (``e`` bit sbagliati, ``f`` bit
    cancellati all'ingresso del decodificatore)."""
    inside = [r for r in ok if r["within_limit"]]
    outside = [r for r in ok if not r["within_limit"]]
    out = []
    for label, rs in ((f"2e + f <= 2t = {2 * t}", inside), (f"2e + f > {2 * t}", outside)):
        bad = sum(r["decoded_wrong"] for r in rs)
        with_e = [r for r in rs if r["n_errors"] > 0]
        rate = f"{bad / len(rs):.4f}" if rs else "n/a"
        out.append(f"  {label}: {len(rs)} cases ({len(with_e)} with e > 0); wrong decoded "
                   f"{bad} (rate {rate})")  # fmt: skip
    return out


def coverage_lines(ok: list[dict[str, Any]], b: int) -> list[str]:
    """Curva di copertura: frazione media di posizioni con almeno un voto in funzione di ``N``."""
    out = [f"coverage of the B = {b} positions vs N (mean fraction covered; reference = "
           f"1 - (1 - 1/B)^N; window = |N - n| <= {COVERAGE_WINDOW}):"]  # fmt: skip
    for n in COVERAGE_N:
        exact = [r["coverage"] for r in ok if r["n_sites"] == n]
        near = [r["coverage"] for r in ok if abs(r["n_sites"] - n) <= COVERAGE_WINDOW]

        def fmt(xs: list[float]) -> str:
            return f"{sum(xs) / len(xs):.3f} ({len(xs)} cases)" if xs else "n/a (0 cases)"

        ref = 1 - (1 - 1 / b) ** n
        out.append(f"  N = {n:>2}: exact {fmt(exact)}; window {fmt(near)}; reference {ref:.3f}")
    return out


def summarize(results: list[dict[str, Any]], args: argparse.Namespace, secs: float) -> str:
    lines = [
        "P1 self-test of multimark (python -m multimark.cli.selftest)",
        f"library {__version__}; python {platform.python_version()}; "
        f"fragments={args.fragments} keys={args.keys}; wall time {secs:.0f} s",
        "",
    ]
    for profile in PROFILES:
        rs = [r for r in results if r["profile"] == profile]
        ok = [r for r in rs if r["status"] != "FAILED"]
        big = [r for r in ok if r["big"]]
        small = [r for r in ok if not r["big"]]
        big_cov = [r for r in big if r["covered"]]
        lines += [
            f"== profile {profile}: {len(rs)} cases",
            f"embed status: {dict(Counter(r['status'] for r in rs))}; "
            f"failed reasons: {dict(Counter(r['reason'] for r in rs if r['status'] == 'FAILED'))}",
            f"skipped sites (total): {sum(r['skipped'] for r in ok)}; "
            f"name sites without candidate (total): {sum(r['no_candidate'] for r in ok)} "
            f"in {sum(r['no_candidate'] > 0 for r in ok)} cases; wrong name votes (total): "
            f"{sum(r['wrong_names'] for r in ok)}",
            f"comparison: agreement == N - wrong_names in {sum(r['agreement_ok'] for r in ok)}"
            f"/{len(ok)}",
            f"N >= B: {len(big)} cases; all B positions covered: {len(big_cov)}; decoded == m: "
            f"{sum(r['decoded_ok'] for r in big)} (covered: {sum(r['decoded_ok'] for r in big_cov)}"
            f"/{len(big_cov)}); decode status {dict(Counter(r['decode_status'] for r in big))}",
            f"N < B: {len(small)} cases; with erasures: {sum(r['erasures'] > 0 for r in small)}; "
            f"decode status {dict(Counter(r['decode_status'] for r in small))}",
            f"wrong decoded messages: {sum(r['decoded_wrong'] for r in ok)} "
            f"(with no wrong name vote: "
            f"{sum(r['decoded_wrong'] for r in ok if r['wrong_names'] == 0)}; with wrong name "
            f"votes: {sum(r['decoded_wrong'] for r in ok if r['wrong_names'] > 0)})",
            *limit_lines(ok, PROFILES[profile].t),
        ]
        lines += coverage_lines(ok, PROFILES[profile].codeword_length)
        inv: dict[str, Counter] = {}
        for r in ok:
            for name, res in r.get("invariance", {}).items():
                inv.setdefault(name, Counter())[str(res)] += 1
        for name, c in sorted(inv.items()):
            lines.append(f"formatting invariance {name}: identical readings {c.get('True', 0)}"
                         f"/{sum(c.values())} (not available: {c.get('None', 0)})")  # fmt: skip
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="multimark-selftest", description=__doc__.splitlines()[0])
    p.add_argument("--fragments", type=int, default=500)
    p.add_argument("--keys", type=int, default=100)
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    p.add_argument("--log", type=Path)
    args = p.parse_args(argv)
    tasks = [(prof, f, k) for prof in PROFILES for f in range(args.fragments)
             for k in range(args.keys)]  # fmt: skip
    t0 = time.perf_counter()
    if args.workers > 1:
        with Pool(args.workers) as pool:
            results = pool.map(run_case, tasks, chunksize=20)
    else:
        results = [run_case(t) for t in tasks]
    text = summarize(results, args, time.perf_counter() - t0)
    tm = timing()
    text += (
        f"timing: file of {tm['lines']:.0f} lines, embed + detect (registry 1/16/1024): "
        f"multimark {tm['multimark']:.3f} s, mcss {tm['mcss']:.3f} s (criterion < 1 s)\n"
    )
    if args.log:
        if args.log.exists():
            raise SystemExit(f"{args.log} already exists (logs are never overwritten)")
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
