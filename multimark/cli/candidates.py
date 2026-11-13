"""Inventario dei canali candidati da riga di comando (passo P0-bis).

Legge gli stessi JSONL dell'inventario (un oggetto per riga, codice in ``--code-field``), uno per
gruppo (``--input ETICHETTA=PERCORSO``, ripetibile). Stampa, per gruppo, per ogni pattern e forma:
occorrenze totali, media per campione, frazione di campioni con almeno un'occorrenza. Poi la stima
di capacità: classifica dei pattern per frequenza sui gruppi di ``--estimate-groups`` (default:
tutti, insieme) e, per ciascuno di quei gruppi, la frazione di campioni con ``≥ 8`` e ``≥ 13`` siti
sommando a ``n_sites_total`` i primi 3, 5 e 8 pattern, nelle tre varianti di
``multimark.candidates``: ``prudent``, ``all_forms`` e ``no_overlap`` (senza sovrapposizioni).

Esempio (L1 dev)::

    python -m multimark.cli.candidates \\
        --input canonical=l1_dev_canonical.jsonl --input qwen=l1_dev_qwen.jsonl \\
        --input deepseek=l1_dev_deepseek.jsonl --summary candidates.txt --summary-json c.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from multimark.candidates import (
    COUNTERS,
    ESTIMATE_KS,
    ESTIMATE_THRESHOLDS,
    PATTERNS,
    VARIANTS,
    estimate,
    estimate_counters,
    rank_patterns,
    sample_row,
    summarize_candidates,
)
from multimark.cli.inventory import _read_jsonl


def _parse_input(text: str) -> tuple[str, Path]:
    label, sep, path = text.partition("=")
    if not sep or not label or not path:
        raise argparse.ArgumentTypeError(f"expected LABEL=PATH, got {text!r}")
    return label, Path(path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="multimark-candidates", description=__doc__.splitlines()[0])
    p.add_argument("--input", action="append", required=True, type=_parse_input,
                   help="LABEL=PATH of a JSONL file (repeatable, one per group)")  # fmt: skip
    p.add_argument("--code-field", default="code")
    p.add_argument("--id-field", help="field copied to the per-sample table")
    p.add_argument("--estimate-groups", help="comma-separated labels (default: all groups)")
    p.add_argument("--output", type=Path, help="per-sample table (.csv or .jsonl)")
    p.add_argument("--summary", type=Path, help="text summary (default: stdout)")
    p.add_argument("--summary-json", type=Path)
    return p


def _fmt(x: float) -> str:
    return f"{x:.4f}" if x == x else "nan"


def format_group(label: str, summary: dict) -> list:
    lines = [f"== group {label}: samples={summary['n_samples']} parsed={summary['n_parsed']}"]
    lines.append(
        f"{'':2}{'pattern':<16}{'form':<6}{'total':>8}{'mean':>10}{'frac>=1':>10}  est.  form"
    )
    for pattern in PATTERNS:
        prudent = estimate_counters(pattern)
        for i, counter in enumerate(pattern.counters):
            st = summary["counters"][counter]
            mark = "*" if counter in prudent else " "
            lines.append(
                f"{pattern.letter:<2}{pattern.name:<16}{'f' + str(i):<6}{st['total']:>8}"
                f"{_fmt(st['mean']):>10}{_fmt(st['frac_ge_1']):>10}   {mark}   {pattern.forms[i]}"
            )
    return lines


def format_estimate(label: str, est: dict, variant: str) -> list:
    lines = [f"-- estimate {variant}, group {label}"]
    head = "".join(f"{'frac>=' + str(t):>12}" for t in ESTIMATE_THRESHOLDS)
    lines.append(f"{'k':>3}{head}  patterns")
    for k, row in est.items():
        vals = "".join(f"{_fmt(row[f'frac_ge_{t}']):>12}" for t in ESTIMATE_THRESHOLDS)
        lines.append(f"{k:>3}{vals}  {', '.join(row['patterns']) or '(current sites)'}")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    groups: dict = {}
    for label, path in args.input:
        if label in groups:
            raise SystemExit(f"duplicate group label: {label}")
        rows = []
        for obj in _read_jsonl(path):
            code = obj.get(args.code_field)
            if not isinstance(code, str):
                raise SystemExit(f"missing string field {args.code_field!r} in {path}")
            row = {"group": label, **sample_row(code)}
            if args.id_field:
                row[args.id_field] = obj.get(args.id_field)
            rows.append(row)
        groups[label] = rows
    est_groups = args.estimate_groups.split(",") if args.estimate_groups else list(groups)
    unknown = [g for g in est_groups if g not in groups]
    if unknown:
        raise SystemExit(f"unknown estimate groups: {unknown}")

    lines: list = []
    result: dict = {"groups": {}, "estimate": {}}
    for label, rows in groups.items():
        summary = summarize_candidates(rows)
        result["groups"][label] = summary
        lines.extend(format_group(label, summary))
        lines.append("")
    pooled = [r for g in est_groups for r in groups[g]]
    lines.append(f"Estimate: ranking on groups {', '.join(est_groups)}; k in {ESTIMATE_KS}; "
                 "prudent/all_forms are upper bounds (overlaps counted twice); "
                 "no_overlap assigns each node to at most one site")  # fmt: skip
    for variant in VARIANTS:
        ranking = rank_patterns(pooled, variant)
        lines.append(f"ranking {variant}: " + ", ".join(f"{n} ({t})" for n, t in ranking))
        result["estimate"][variant] = {"ranking": ranking, "groups": {}}
        for label in est_groups:
            est = estimate(groups[label], ranking, variant=variant)
            result["estimate"][variant]["groups"][label] = est
            lines.extend(format_estimate(label, est, variant))
        lines.append("")
    text = "\n".join(lines) + "\n"
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.output:
        columns = ["group", *([args.id_field] if args.id_field else []), "parse_ok",
                   "n_sites_total", *COUNTERS]  # fmt: skip
        all_rows = [r for rows in groups.values() for r in rows]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.suffix == ".jsonl":
            with args.output.open("w", encoding="utf-8", newline="\n") as fh:
                for r in all_rows:
                    fh.write(json.dumps({c: r.get(c) for c in columns}) + "\n")
        elif args.output.suffix == ".csv":
            with args.output.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(all_rows)
        else:
            raise SystemExit(f"unsupported output extension: {args.output.suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
