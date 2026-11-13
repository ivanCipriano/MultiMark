"""Inventario dei siti (PIPELINE_metodo.md §2 P0, §6.1).

Per campione (``inventory_code``):

- ``n_sites_<canale>`` per ciascuno dei 14 canali strutturali (0 per i canali non attivi:
  ``channels="mcss8"`` legge solo 1–8, ``"extended"`` 1–14);
- ``n_sites_structural``: somma dei canali;
- ``n_vars``: siti del canale dei nomi secondo la regola di §3.6.1;
- ``n_vars_module``: quanti di ``n_vars`` sono variabili di modulo (0 con ``module_level=False``;
  serve alla decisione O di §7);
- ``n_sites_total = n_sites_structural + n_vars`` (un bit per variabile, come la V2 della base:
  è la ``N`` di §3.9 confrontata con ``B = 32``; confermato da Ivan il 13 novembre 2026);
- ``n_bits_v1 = n_sites_structural + 2·n_vars``: capacità con il canale dei nomi V1 di ``mcss``
  (2 bit per variabile). Le variabili sono quelle delle opzioni dell'inventario: per il profilo
  ``mcss`` completo si lancia con ``--canonical paper --include-params``;
- ``n_functions``: unità di funzione di §3.2 (funzioni più esterne, ``MODULE`` escluso);
- ``n_duplicate_fids``: numero di ``fid`` distinti condivisi da almeno due funzioni del campione
  (i loro siti condividono le chiavi ``(fid, canale, rango)``, vedi ``sites.py``);
- ``loc``: righe di codice come ``bench.lang.line_counter`` (una riga conta se contiene un token
  che non è un commento; le stringhe su più righe contano per tutte le righe; docstring escluse).

Per dataset (``summarize``): media, mediana, P25, P75 (interpolazione lineare, come il default di
``numpy.percentile``) e frazione di campioni con ``n_sites_total ≥ 32``, ``≥ 20``, ``≥ 13``;
frazione di campioni con almeno un ``fid`` duplicato; canale più frequente (per numero totale di
siti). I campioni che non si analizzano sono contati a parte (``n_parse_errors``) e non entrano
nelle statistiche.
"""

from __future__ import annotations

import ast
import io
import math
import tokenize
from collections.abc import Iterable, Sequence
from typing import Any, Optional

from multimark._astindex import AstIndex, iter_preorder
from multimark.channels import CHANNELS, ReadContext, ReadOptions
from multimark.names import name_sites
from multimark.sites import count_by_channel, find_sites, loop_form_targets

THRESHOLDS = (32, 20, 13)
STAT_COLUMNS = (
    "n_sites_total",
    "n_sites_structural",
    "n_vars",
    "n_vars_module",
    "n_bits_v1",
    *(f"n_sites_{c}" for c in CHANNELS),
    "n_functions",
    "n_duplicate_fids",
    "loc",
)

_NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
)


def _docstring_rows(tree: ast.Module) -> set:
    rows: set = set()
    for node in iter_preorder(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc = body[0]
                rows.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return rows


def count_loc(code: str, tree: Optional[ast.Module] = None) -> int:
    """Righe di codice (vedi docstring del modulo)."""
    tree = tree if tree is not None else ast.parse(code)
    rows: set = set()
    for tok in tokenize.generate_tokens(io.StringIO(code).readline):
        if tok.type in _NON_CODE_TOKENS:
            continue
        rows.update(range(tok.start[0], tok.end[0] + 1))
    return len(rows - _docstring_rows(tree))


def inventory_code(
    code: str,
    canonical: str = "kind",
    guards: bool = True,
    include_params: bool = False,
    module_level: bool = False,
    channels: str = "extended",
) -> dict[str, Any]:
    """Riga dell'inventario per un campione. ``parse_ok=False`` se ``ast.parse`` fallisce."""
    try:
        index = AstIndex.from_code(code)
    except (SyntaxError, ValueError) as exc:
        return {"parse_ok": False, "error": f"{type(exc).__name__}: {exc}"}
    ctx = ReadContext(index, ReadOptions(canonical=canonical, guards=guards, channels=channels))
    sites = find_sites(index, ctx=ctx)
    names = name_sites(
        index,
        include_params=include_params,
        excluded_binding_ids=loop_form_targets(sites, index),
        module_level=module_level,
    )
    counts = count_by_channel(sites)
    row: dict[str, Any] = {"parse_ok": True, "error": None}
    row["n_sites_total"] = len(sites) + len(names)
    row["n_sites_structural"] = len(sites)
    row["n_vars"] = len(names)
    row["n_vars_module"] = sum(1 for n in names if n.unit.is_module)
    row["n_bits_v1"] = len(sites) + 2 * len(names)
    for channel in CHANNELS:
        row[f"n_sites_{channel}"] = counts[channel]
    row["n_functions"] = len(index.functions)
    row["n_duplicate_fids"] = index.n_duplicate_fids
    row["loc"] = count_loc(code, index.tree)
    return row


def quantile(values: Sequence[float], q: float) -> float:
    """Quantile con interpolazione lineare (default di ``numpy.percentile``)."""
    if not values:
        return math.nan
    data = sorted(values)
    pos = (len(data) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Riepilogo per dataset (vedi docstring del modulo)."""
    all_rows = list(rows)
    ok = [r for r in all_rows if r.get("parse_ok")]
    out: dict[str, Any] = {
        "n_samples": len(all_rows),
        "n_parsed": len(ok),
        "n_parse_errors": len(all_rows) - len(ok),
        "stats": {},
    }
    for col in STAT_COLUMNS:
        vals = [float(r[col]) for r in ok]
        out["stats"][col] = {
            "mean": sum(vals) / len(vals) if vals else math.nan,
            "median": quantile(vals, 0.5),
            "p25": quantile(vals, 0.25),
            "p75": quantile(vals, 0.75),
        }
    totals = [r["n_sites_total"] for r in ok]
    for th in THRESHOLDS:
        out[f"frac_total_ge_{th}"] = (
            sum(1 for v in totals if v >= th) / len(totals) if totals else math.nan
        )
    out["frac_with_duplicate_fids"] = (
        sum(1 for r in ok if r["n_duplicate_fids"] > 0) / len(ok) if ok else math.nan
    )
    channel_totals = {c: sum(r[f"n_sites_{c}"] for r in ok) for c in CHANNELS}
    channel_totals["names"] = sum(r["n_vars"] for r in ok)
    out["sites_by_channel"] = channel_totals
    structural = {c: channel_totals[c] for c in CHANNELS}
    out["most_frequent_structural_channel"] = (
        max(CHANNELS, key=lambda c: (structural[c], -CHANNELS.index(c)))
        if any(structural.values())
        else None
    )
    out["most_frequent_channel"] = (
        max(channel_totals, key=lambda c: channel_totals[c])
        if any(channel_totals.values())
        else None
    )
    return out


def format_summary(summary: dict[str, Any], label: str = "") -> str:
    """Testo del riepilogo (per ``docs/milestone_logs/P0_inventory.txt``)."""
    lines: list[str] = []
    title = f"Inventory {label}".strip()
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(
        f"samples={summary['n_samples']} parsed={summary['n_parsed']} "
        f"parse_errors={summary['n_parse_errors']}"
    )
    for th in THRESHOLDS:
        lines.append(f"frac n_sites_total >= {th}: {summary[f'frac_total_ge_{th}']:.4f}")
    lines.append(f"frac with duplicate fids: {summary['frac_with_duplicate_fids']:.4f}")
    lines.append(f"most frequent structural channel: {summary['most_frequent_structural_channel']}")
    lines.append(f"most frequent channel (names included): {summary['most_frequent_channel']}")
    lines.append("")
    lines.append(f"{'column':<26}{'mean':>10}{'median':>10}{'p25':>10}{'p75':>10}")
    for col, st in summary["stats"].items():
        lines.append(
            f"{col:<26}{st['mean']:>10.3f}{st['median']:>10.3f}{st['p25']:>10.3f}{st['p75']:>10.3f}"
        )
    lines.append("")
    lines.append("total sites by channel:")
    for channel, total in summary["sites_by_channel"].items():
        lines.append(f"  {channel:<16}{total:>10}")
    return "\n".join(lines) + "\n"
