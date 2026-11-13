"""Inventario dei siti da riga di comando (PIPELINE_metodo.md §2 P0).

Legge un JSONL di codici (un oggetto per riga, con il codice nel campo ``--code-field``), scrive la
tabella per campione (CSV o JSONL secondo l'estensione di ``--output``) e il riepilogo in testo
(``--summary``, default: standard output) e, se richiesto, in JSON (``--summary-json``).

Esempio::

    python -m multimark.cli.inventory --input codes.jsonl --output rows.csv \\
        --summary summary.txt --label "L1 dev baseline qwen" --id-field sample_id
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Optional

from multimark.channels import CANONICAL_MODES
from multimark.inventory import STAT_COLUMNS, format_summary, inventory_code, summarize


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise SystemExit(f"{path}:{lineno}: expected a JSON object")
            yield obj


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="multimark-inventory", description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True, type=Path, help="JSONL file of code samples")
    p.add_argument("--output", type=Path, help="per-sample table (.csv or .jsonl)")
    p.add_argument("--summary", type=Path, help="text summary (default: stdout)")
    p.add_argument("--summary-json", type=Path, help="summary as JSON")
    p.add_argument("--code-field", default="code", help="field holding the code (default: code)")
    p.add_argument("--id-field", help="field copied to the table as sample id")
    p.add_argument("--label", default="", help="dataset label in the summary title")
    p.add_argument("--canonical", choices=CANONICAL_MODES, default="kind")
    p.add_argument("--no-guards", action="store_true", help="drop semantic channel conditions")
    p.add_argument("--include-params", action="store_true", help="count parameters as names")
    return p


def _columns(id_field: Optional[str]) -> list[str]:
    head = [id_field] if id_field else []
    return [*head, "parse_ok", "error", *STAT_COLUMNS]


def _write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl":
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps({c: row.get(c) for c in columns}, ensure_ascii=False) + "\n")
    elif path.suffix == ".csv":
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise SystemExit(f"unsupported output extension: {path.suffix} (use .csv or .jsonl)")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    rows: list[dict[str, Any]] = []
    for obj in _read_jsonl(args.input):
        code = obj.get(args.code_field)
        if not isinstance(code, str):
            raise SystemExit(f"missing string field {args.code_field!r} in input record")
        row = inventory_code(
            code,
            canonical=args.canonical,
            guards=not args.no_guards,
            include_params=args.include_params,
        )
        if args.id_field:
            row = {args.id_field: obj.get(args.id_field), **row}
        rows.append(row)
    if args.output:
        _write_rows(args.output, rows, _columns(args.id_field))
    summary = summarize(rows)
    summary["options"] = {
        "canonical": args.canonical,
        "guards": not args.no_guards,
        "include_params": args.include_params,
    }
    text = format_summary(summary, args.label)
    text += (
        f"\noptions: canonical={args.canonical} guards={not args.no_guards} "
        f"include_params={args.include_params}\n"
    )
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
