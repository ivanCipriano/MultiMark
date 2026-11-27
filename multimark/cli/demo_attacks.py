"""Attacchi dimostrativi per la pagina web del dimostratore (P7.d), solo Python.

Sono copie della logica degli attacchi **deterministici** del benchmark ``wm-bench`` (commit
``8f5588a``, ``src/bench/attacks/``), senza importare niente da lì e senza dipendenze nuove: il
benchmark analizza il codice con tree-sitter, qui si usano ``ast`` e ``tokenize`` della libreria
standard (e ``libcst`` per le rinomine, come nel benchmark). Ogni attacco dice nel docstring da
quale file e funzione viene e in cosa differisce. Le posizioni dei nodi vengono da ``ast`` invece
che da tree-sitter: in casi limite (parentesi, commenti in coda ai blocchi) il testo prodotto può
differire da quello del benchmark. **I risultati della tesi vengono dal benchmark, non da qui.**

Le scelte casuali usano ``random.Random(seed)`` con il seme fisso ``DEMO_SEED``, mostrato nella
pagina (nel benchmark il seme è ``derive_seed(global_seed, "attack", attack_id, params_hash,
sample_id)``, SPEC §18). Stesso codice, stessi parametri e stesso seme danno lo stesso risultato.

T1.1 (``black``), T1.2 (``ruff --fix``) e T4.1 (``python-minifier``) usano gli strumenti del
benchmark, con le stesse versioni, dall'extra ``demo``; si importano o si lanciano solo qui e, se
mancano, l'attacco è disattivato (``unavailable``).

Non ci sono: T2.2 e T2.3, che usano un LLM; T4.2, solo JavaScript; T1.3 ``insert`` e T1.4
``natural``, che usano le raccolte di commenti e di nomi del benchmark (fase ``attack_pools``). Di
T2.1 c'è solo il catalogo AST (le regole Ruff mancano). T3.1 (ri-marcatura con una
seconda chiave) è ``remark``: per i metodi post-hoc il benchmark riapplica il metodo con la chiave
``k2``, senza LLM.
"""

# Origine: wm-bench@8f5588a:src/bench/attacks/{t1,t2,t3,t4}/*.py e attacks/tools.py (vedi
# PROVENANCE.md); modifiche:
# logica ricopiata con ast/tokenize al posto di tree-sitter, solo Python, seme fisso, differenze
# nel docstring di ogni attacco.

from __future__ import annotations

import ast
import builtins
import importlib.metadata
import importlib.util
import io
import keyword
import math
import random
import re
import string
import subprocess
import sys
import tempfile
import tokenize
import warnings
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

DEMO_SEED = 2026
APPLIED, UNCHANGED, NOT_APPLICABLE, TOOL_ERROR = (
    "APPLIED",
    "UNCHANGED",
    "NOT_APPLICABLE",
    "TOOL_ERROR",
)


# ============================================================================ tipi
@dataclass(frozen=True)
class ParamSpec:
    """Parametro di un attacco nella pagina: ``choices`` (menu) o testo libero."""

    name: str
    label: str
    default: Any
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class AttackSpec:
    attack_id: str
    label: str
    params: tuple[ParamSpec, ...]
    source: str


@dataclass(frozen=True)
class AttackResult:
    """Esito di un attacco (stati come ``AttackStatus`` del benchmark); con ``TOOL_ERROR`` e
    ``NOT_APPLICABLE`` il codice è quello di partenza."""

    attack_id: str
    params: dict[str, Any]
    seed: int
    status: str
    code: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def parses(self) -> bool:
        return parses(self.code)


def parses(code: str) -> bool:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return True


def _outcome(original: str, new: str, detail: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """``outcome`` di ``attacks/base.py``: ``APPLIED`` se il codice cambia, altrimenti
    ``UNCHANGED``."""
    return (APPLIED if new != original else UNCHANGED), new, detail


def _tool_error(
    original: str, error: str, detail: dict[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    return TOOL_ERROR, original, {**detail, "error": error[:2000]}


# ============================================================================ strumenti comuni
class _Source:
    """Codice con la tabella degli inizi di riga: posizioni di ``ast`` (riga, colonna in byte
    UTF-8) e di ``tokenize`` (riga, colonna in caratteri) → offset in caratteri."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.lines = code.split("\n")
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line) + 1)

    def at(self, lineno: int, col_bytes: int) -> int:
        line = self.lines[lineno - 1]
        return self.starts[lineno - 1] + len(
            line.encode("utf-8")[:col_bytes].decode("utf-8", "replace")
        )

    def at_char(self, lineno: int, col: int) -> int:
        return self.starts[lineno - 1] + col

    def start(self, node: ast.AST) -> int:
        return self.at(node.lineno, node.col_offset)  # type: ignore[attr-defined]

    def end(self, node: ast.AST) -> int:
        return self.at(node.end_lineno, node.end_col_offset)  # type: ignore[attr-defined]

    def span(self, node: ast.AST) -> tuple[int, int]:
        return self.start(node), self.end(node)

    def text(self, node: ast.AST) -> str:
        s, e = self.span(node)
        return self.code[s:e]

    def row(self, offset: int) -> int:
        return self.code.count("\n", 0, offset)

    def column(self, offset: int) -> int:
        return offset - (self.code.rfind("\n", 0, offset) + 1)

    def indent(self, offset: int) -> str:
        """Spazi iniziali della riga che contiene ``offset`` (``_indent`` di T2.1)."""
        start = self.code.rfind("\n", 0, offset) + 1
        line = self.code[start:].split("\n", 1)[0]
        return line[: len(line) - len(line.lstrip(" \t"))]


_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# ``keyword.softkwlist`` di Python 3.11 (l'ambiente del benchmark): in 3.9 è vuoto.
_SOFT_KEYWORDS = ("_", "case", "match")
RESERVED = frozenset(keyword.kwlist) | frozenset(_SOFT_KEYWORDS) | frozenset(dir(builtins))
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def identifiers_in(code: str) -> set[str]:
    """``t1/common.py`` ``identifiers_in``: parole che potrebbero essere identificatori (anche in
    stringhe e commenti)."""
    return set(_IDENT.findall(code))


class NameFactory:
    """``t1/common.py`` ``NameFactory`` (solo nomi ``random``): lettera minuscola più 7 caratteri
    alfanumerici minuscoli, senza collisioni con parole riservate e nomi del file."""

    def __init__(self, rng: random.Random, taken: set[str]) -> None:
        self.rng = rng
        self.blocked = set(taken) | RESERVED

    def _free(self, name: str) -> bool:
        return name not in self.blocked and not (name.startswith("__") and name.endswith("__"))

    def random(self) -> str:
        alphabet = string.ascii_lowercase + string.digits
        while True:
            name = self.rng.choice(string.ascii_lowercase) + "".join(
                self.rng.choice(alphabet) for _ in range(7)
            )
            if self._free(name):
                self.blocked.add(name)
                return name


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and (
        (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str))
        or isinstance(stmt.value, ast.JoinedStr)
    )


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def _preorder(node: ast.AST) -> list[ast.AST]:
    """Visita in profondità in ordine di sorgente (come ``iter_nodes`` del benchmark)."""
    out: list[ast.AST] = []
    stack = [node]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(reversed(list(ast.iter_child_nodes(cur))))
    return out


# ============================================================================ T1.3
def remove_comments(code: str) -> tuple[str, int]:
    """T1.3 ``mode=remove``: ``t1/comments.py`` ``remove_comments``.

    Una riga con solo il commento sparisce; un commento a fine riga si toglie con gli spazi che lo
    precedono; le docstring restano. Differenza: i commenti si trovano con ``tokenize`` (token
    ``COMMENT``) invece che con i nodi commento di tree-sitter."""
    src = _Source(code)
    spans = []
    for tok in tokenize.generate_tokens(io.StringIO(code).readline):
        if tok.type == tokenize.COMMENT:
            spans.append((src.at_char(*tok.start), src.at_char(*tok.end)))
    out = code
    for start, end in sorted(spans, reverse=True):
        line_start = out.rfind("\n", 0, start) + 1
        line_end = out.find("\n", end)
        line_end = len(out) if line_end < 0 else line_end
        before, after = out[line_start:start], out[end:line_end]
        if not before.strip() and not after.strip():
            out = out[:line_start] + out[min(line_end + 1, len(out)) :]
        elif not after.strip():
            out = out[: line_start + len(before.rstrip())] + out[line_end:]
        else:
            pad = "" if (before.endswith((" ", "\t")) or after.startswith((" ", "\t"))) else " "
            out = out[:start] + pad + out[end:]
    return out, len(spans)


def _t1_3(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    try:
        new, n = remove_comments(code)
    except (tokenize.TokenError, SyntaxError) as exc:
        return _tool_error(code, f"tokenize: {exc}", {"n_removed": 0})
    detail = {"n_removed": n}
    if parses(code) and not parses(new):
        return _tool_error(code, "the attacked code no longer parses", detail)
    return _outcome(code, new, detail)


# ============================================================================ T1.4 e T1.6
@dataclass
class Candidate:
    """``t1/rename.py`` ``Candidate``: nome rinominabile e intervalli (in caratteri)."""

    name: str
    function: int
    spans: list[tuple[int, int]] = field(default_factory=list)

    @property
    def first(self) -> int:
        return min(s for s, _ in self.spans)


_PY_DYNAMIC_CALL = re.compile(r"\b(?:locals|vars|eval|exec)\s*\(")
_PY_DYNAMIC_MODULE = re.compile(r"\b(?:globals|locals|vars|eval|exec)\s*\(")


def _cst_spans(
    assignments: list[Any], span: Callable[[Any], tuple[int, int]]
) -> Optional[list[tuple[int, int]]]:
    """``t1/rename.py`` ``_python_spans``: intervalli di un gruppo di assegnazioni e dei loro usi;
    ``None`` se il gruppo contiene altro che nomi e parametri."""
    import libcst as cst

    spans: list[tuple[int, int]] = []
    for assignment in assignments:
        node = getattr(assignment, "node", None)
        if isinstance(node, cst.Param):
            spans.append(span(node.name))
        elif isinstance(node, cst.Name):
            spans.append(span(node))
        else:
            return None
        for access in assignment.references:
            if not isinstance(access.node, cst.Name):
                return None
            spans.append(span(access.node))
    return sorted(set(spans))


def _cst_context(code: str) -> tuple[Any, Any, Callable[[Any], tuple[int, int]]]:
    import libcst as cst
    from libcst.metadata import MetadataWrapper, PositionProvider, ScopeProvider

    wrapper = MetadataWrapper(cst.parse_module(code))
    scopes = wrapper.resolve(ScopeProvider)
    positions = wrapper.resolve(PositionProvider)
    line_starts = [0]
    for line in code.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    def span(node: Any) -> tuple[int, int]:
        rng = positions[node]
        return (
            line_starts[rng.start.line - 1] + rng.start.column,
            line_starts[rng.end.line - 1] + rng.end.column,
        )

    return wrapper, scopes, span


def _declared_outer(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
    return out


def python_candidates(code: str, entry_point: Optional[str] = None) -> list[Candidate]:
    """``t1/rename.py`` ``python_candidates``: gruppi rinominabili degli scope di funzione
    (``libcst`` con ``ScopeProvider``). Esclusi ``self``, ``cls``, dunder, nomi in
    ``global``/``nonlocal``, nomi usati come argomento con nome, funzioni con ``locals``,
    ``vars``, ``eval``, ``exec``. Nessuna differenza (nel dimostratore ``entry_point`` è
    ``None``: non c'è il problema)."""
    from libcst.metadata import FunctionScope

    tree = ast.parse(code)
    keyword_args = {kw.arg for kw in ast.walk(tree) if isinstance(kw, ast.keyword) and kw.arg}
    declared_outer = _declared_outer(tree)
    wrapper, scopes, span = _cst_context(code)
    seen: set[int] = set()
    out: list[Candidate] = []
    function_index = 0
    for scope in scopes.values():
        if not isinstance(scope, FunctionScope) or id(scope) in seen:
            continue
        seen.add(id(scope))
        function_index += 1
        if _PY_DYNAMIC_CALL.search(wrapper.module.code_for_node(scope.node)):
            continue
        groups: dict[str, list[Any]] = defaultdict(list)
        for assignment in scope.assignments:
            groups[assignment.name].append(assignment)
        for name, assignments in sorted(groups.items()):
            if (
                name in ("self", "cls")
                or name == entry_point
                or name in declared_outer
                or name in keyword_args
                or (name.startswith("__") and name.endswith("__"))
            ):
                continue
            spans = _cst_spans(assignments, span)
            if spans:
                out.append(Candidate(name, function_index, spans))
    return sorted(out, key=lambda c: (c.first, c.name))


def _rename_rewrite(code: str, renames: list[tuple[Candidate, str]]) -> str:
    """``t1/rename.py`` ``rewrite`` (dal fondo verso l'inizio)."""
    edits = [(s, e, new) for cand, new in renames for s, e in cand.spans]
    out = code
    for start, end, text in sorted(edits, reverse=True):
        out = out[:start] + text + out[end:]
    return out


def _t1_4(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T1.4 rinomina: ``t1/rename.py`` ``RenameAttack.apply`` (solo ``name_kind=random``, solo
    Python): si rinominano ``max(1, round(ratio × candidati))`` candidati scelti con il seme."""
    try:
        candidates = python_candidates(code)
    except SyntaxError as exc:
        return _tool_error(code, f"SyntaxError: {exc}", {"n_candidates": 0})
    n = len(candidates)
    k = max(1, round(float(params["ratio"]) * n)) if n else 0
    chosen = sorted(rng.sample(range(n), k))
    names = NameFactory(rng, identifiers_in(code))
    renames = [(candidates[i], names.random()) for i in chosen]
    new = _rename_rewrite(code, renames)
    detail = {
        "n_candidates": n,
        "n_renamed": k,
        "n_occurrences": sum(len(c.spans) for c, _ in renames),
    }
    try:
        ast.parse(new)
    except SyntaxError as exc:
        return _tool_error(code, f"renamed code does not parse: {exc}", detail)
    return _outcome(code, new, detail)


_SEGMENT = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+[0-9]*|[0-9]+")
_CORE = re.compile(r"^(_*)(.*?)(_*)$", re.DOTALL)
_ASCII_CORE = re.compile(r"[A-Za-z0-9_]+")


def norm(name: str) -> str:
    """``t1/snake_case.py`` ``norm`` (§3.6.2)."""
    out: list[str] = []
    for part in name.split("_"):
        out.extend(_SEGMENT.findall(part))
    return "_".join(s.lower() for s in out)


def snake_name(name: str) -> str:
    """``t1/snake_case.py`` ``snake_name``: nucleo in ``snake_case``, ``_`` ai bordi conservati."""
    match = _CORE.match(name)
    assert match is not None
    lead, core, trail = match.groups()
    if not core or not _ASCII_CORE.fullmatch(core):
        return name
    new = norm(core)
    return f"{lead}{new}{trail}" if new else name


def is_all_caps(name: str) -> bool:
    core = name.strip("_")
    return any(c.isalpha() for c in core) and not any(c.islower() for c in core)


def _all_names(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            value = getattr(node, "value", None)
            if value is not None:
                for sub in ast.walk(value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        out.add(sub.value)
    return out


def module_candidates(code: str, entry_point: Optional[str] = None) -> list[Candidate]:
    """``t1/snake_case.py`` ``module_candidates``: nomi di modulo rinominabili."""
    from libcst.metadata import GlobalScope

    if _PY_DYNAMIC_MODULE.search(code):
        return []
    tree = ast.parse(code)
    keyword_args = {kw.arg for kw in ast.walk(tree) if isinstance(kw, ast.keyword) and kw.arg}
    declared = _declared_outer(tree)
    exported = _all_names(tree)
    _wrapper, scopes, span = _cst_context(code)
    scope = next((s for s in scopes.values() if isinstance(s, GlobalScope)), None)
    if scope is None:
        return []
    groups: dict[str, list[Any]] = defaultdict(list)
    for assignment in scope.assignments:
        groups[assignment.name].append(assignment)
    out: list[Candidate] = []
    for name, assignments in sorted(groups.items()):
        if (
            name in ("self", "cls")
            or name == entry_point
            or name in declared
            or name in keyword_args
            or name in exported
            or (name.startswith("__") and name.endswith("__"))
        ):
            continue
        spans = _cst_spans(assignments, span)
        if spans:
            out.append(Candidate(name, 0, spans))
    return out


def _snake_rewrite(code: str, renames: list[tuple[Candidate, str]]) -> str:
    edits: dict[tuple[int, int], str] = {}
    for cand, new in renames:
        for s in cand.spans:
            if edits.setdefault(s, new) != new:
                raise ValueError(f"span {s} renamed twice ({edits[s]}, {new})")
    ordered = sorted(edits.items(), reverse=True)
    for ((start, end), _), ((after, _end), _t) in zip(ordered[1:], ordered):
        if end > after:
            raise ValueError(f"overlapping spans at {start}")
    out = code
    for (start, end), text in ordered:
        out = out[:start] + text + out[end:]
    return out


def _t1_6(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T1.6 ``snake_case``: ``t1/snake_case.py`` ``SnakeCaseAttack.apply``, senza differenze
    (deterministico, senza modello linguistico). ``caps=keep`` lascia i nomi di modulo in
    ``ALL_CAPS``."""
    try:
        local = python_candidates(code)
        module = module_candidates(code)
    except SyntaxError as exc:
        return _tool_error(code, f"SyntaxError: {exc}", {"n_candidates": 0})
    candidates = sorted([*local, *module], key=lambda c: (c.first, c.function, c.name))
    blocked = identifiers_in(code) | RESERVED
    given: dict[str, str] = {}
    renames: list[tuple[Candidate, str]] = []
    collisions = caps_kept = 0
    for cand in candidates:
        target = snake_name(cand.name)
        if target == cand.name:
            continue
        if cand.function == 0 and params["caps"] == "keep" and is_all_caps(cand.name):
            caps_kept += 1
            continue
        if cand.name not in given:
            new, i = target, 0
            while new in blocked or (new.startswith("__") and new.endswith("__")):
                i += 1
                new = f"{target}_{i}"
            collisions += i > 0
            blocked.add(new)
            given[cand.name] = new
        renames.append((cand, given[cand.name]))
    detail = {"n_candidates": len(candidates), "n_renamed": len(renames),
              "n_collisions": collisions, "n_caps_kept": caps_kept}  # fmt: skip
    try:
        new_code = _snake_rewrite(code, renames)
    except ValueError as exc:
        return _tool_error(code, str(exc), detail)
    try:
        ast.parse(new_code)
    except SyntaxError as exc:
        return _tool_error(code, f"renamed code does not parse: {exc}", detail)
    return _outcome(code, new_code, detail)


# ============================================================================ T1.5
@dataclass(frozen=True)
class _Site:
    """``t1/common.py`` ``Site``: punto prima di un'istruzione."""

    line_start: int
    indent: str
    statement: ast.stmt
    function: ast.AST  # funzione che contiene il blocco
    function_body: bool
    first: bool


_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _blocks(node: ast.AST) -> list[list[ast.stmt]]:
    out = [getattr(node, f) for f in _BLOCK_FIELDS if isinstance(getattr(node, f, None), list)]
    out = [b for b in out if b and isinstance(b[0], ast.stmt)]
    if isinstance(node, ast.Try):
        out += [h.body for h in node.handlers]
    match_cases = getattr(node, "cases", None)  # ast.Match (3.10+)
    if match_cases:
        out += [c.body for c in match_cases]
    return out


def statement_sites(code: str, tree: ast.Module) -> list[_Site]:
    """``t1/common.py`` ``statement_sites``: punti prima delle istruzioni dei blocchi dentro
    funzioni, quando l'istruzione apre la sua riga. Differenza: i blocchi sono le liste di
    istruzioni di ``ast`` (corpi, ``else``, ``finally``, ``except``, ``case``)."""
    src = _Source(code)
    sites: list[_Site] = []

    def visit(node: ast.AST, function: Optional[ast.AST]) -> None:
        inner = node if isinstance(node, FUNCTIONS) else function
        if inner is not None:
            for block in _blocks(node):
                is_body = isinstance(node, FUNCTIONS) and block is getattr(node, "body", None)
                for i, stmt in enumerate(block):
                    start = src.start(stmt)
                    line_start = code.rfind("\n", 0, start) + 1
                    prefix = code[line_start:start]
                    if prefix.strip():
                        continue
                    sites.append(_Site(line_start, prefix, stmt, inner, is_body, i == 0))
        for child in ast.iter_child_nodes(node):
            visit(child, inner)

    visit(tree, None)
    return sorted(sites, key=lambda s: s.line_start)


def _insert_line(code: str, site: _Site, text: str) -> str:
    return code[: site.line_start] + site.indent + text + "\n" + code[site.line_start :]


_FORBIDDEN_T15 = (ast.Call, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                  ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom, ast.AugAssign)  # fmt: skip
_BINARY_T15 = (ast.BinOp, ast.Compare, ast.BoolOp)


def _callee(node: ast.AST) -> Optional[str]:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _recursive(fn: ast.AST) -> bool:
    name = getattr(fn, "name", None)
    return name is not None and any(_callee(n) == name for n in ast.walk(fn))


def _statement_ok(stmt: ast.stmt) -> bool:
    """``_statement_ok`` di T1.5 per Python: espressione, assegnazione (un solo bersaglio) o
    ``return``, senza chiamate, lambda, comprehension, ``:=``, ``await``, ``yield``."""
    if not isinstance(stmt, (ast.Expr, ast.Return, ast.Assign, ast.AnnAssign)):
        return False
    if isinstance(stmt, ast.Assign) and len(stmt.targets) != 1:
        return False  # x = y = ...: assegnazione annidata
    return not any(isinstance(n, _FORBIDDEN_T15) for n in ast.walk(stmt))


def _excluded_expr(path: list[ast.AST]) -> bool:
    """``_excluded_expr`` di T1.5: ``path`` va dall'istruzione all'espressione. Esclusi il lato
    destro di ``and``/``or``, i rami di un'espressione condizionale e il lato sinistro di
    un'assegnazione."""
    for parent, child in zip(path, path[1:]):
        if isinstance(parent, ast.BoolOp) and child is not parent.values[0]:
            return True
        if isinstance(parent, ast.IfExp) and child is not parent.test:
            return True
        if isinstance(parent, ast.Assign) and child in parent.targets:
            return True
        if isinstance(parent, ast.AnnAssign) and child is parent.target:
            return True
    return False


def _extract_candidates(site: _Site) -> list[ast.AST]:
    stmt = site.statement
    if not _statement_ok(stmt):
        return []
    out: list[ast.AST] = []

    def visit(node: ast.AST, path: list[ast.AST]) -> None:
        here = [*path, node]
        if (
            isinstance(node, _BINARY_T15)
            and any(isinstance(n, (ast.Name, ast.Attribute)) for n in ast.walk(node))
            and not _excluded_expr(here)
        ):
            out.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child, here)

    visit(stmt, [])
    return out


def _t1_5(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T1.5 modifiche localizzate: ``t1/local_edits.py`` ``LocalEditsAttack.apply`` (Python).

    ``k`` modifiche, ognuna di un tipo scelto col seme fra ``unused_var`` (``x = 0``),
    ``stderr_log`` (``print(..., file=__import__("sys").stderr)`` nel corpo diretto di una
    funzione non ricorsiva) ed ``extract`` (un'espressione binaria senza effetti collaterali
    spostata in una temporanea). Differenze: l'analisi è con ``ast``; una catena ``a and b and c``
    è un solo nodo (in tree-sitter anche ``a and b`` è un candidato)."""
    if not parses(code):
        return _tool_error(code, "the code does not parse", {})
    names = NameFactory(rng, identifiers_in(code))
    new = code
    edits: list[str] = []
    for _ in range(int(params["k"])):
        tree = ast.parse(new)
        sites = [
            s
            for s in statement_sites(new, tree)
            if not (s.first and s.function_body and _is_docstring(s.statement))
        ]
        top = [s for s in sites if s.function_body and not _recursive(s.function)]
        extract = [(s, e) for s in sites for e in _extract_candidates(s)]
        options: dict[str, Callable[[str], str]] = {}
        if sites:
            options["unused_var"] = lambda c, s=sites: _insert_line(  # type: ignore[misc]
                c, rng.choice(s), f"{names.random()} = 0"
            )
        if top:
            options["stderr_log"] = lambda c, s=top: _add_log(c, rng, s)  # type: ignore[misc]
        if extract:
            options["extract"] = lambda c, e=extract: _add_extract(c, rng, e, names)  # type: ignore[misc]
        if not options:
            break
        kind = rng.choice(sorted(options))
        new = options[kind](new)
        edits.append(kind)
    detail = {"k": int(params["k"]), "n_edits": len(edits), "edits": edits}
    if not parses(new):
        return _tool_error(code, "the edited code no longer parses", detail)
    return _outcome(code, new, detail)


def _add_log(code: str, rng: random.Random, sites: list[_Site]) -> str:
    site = rng.choice(sites)
    message = f"trace {rng.randrange(16**6):06x}"
    return _insert_line(code, site, f'print("{message}", file=__import__("sys").stderr)')


def _add_extract(
    code: str, rng: random.Random, candidates: list[tuple[_Site, ast.AST]], names: NameFactory
) -> str:
    site, expr = rng.choice(candidates)
    start, end = _Source(code).span(expr)
    name = names.random()
    replaced = code[:start] + name + code[end:]
    return _insert_line(replaced, site, f"{name} = ({code[start:end]})")


# ============================================================================ T2.1 (catalogo AST)
_SKIP = (ast.expr_context, ast.boolop, ast.operator, ast.unaryop, ast.cmpop)


def _positioned(node: ast.AST) -> bool:
    return getattr(node, "end_lineno", None) is not None and hasattr(node, "col_offset")


def _children(node: ast.AST, src: _Source) -> list[ast.AST]:
    """Figli con posizione (quelli senza, come ``arguments``, si attraversano), in ordine di
    sorgente; le f-string sono foglie (posizioni interne inaffidabili prima di Python 3.12)."""
    if isinstance(node, ast.JoinedStr):
        return []
    out: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SKIP):
            continue
        if _positioned(child):
            out.append(child)
        else:
            out.extend(_children(child, src))
    return sorted(out, key=src.start)


class _Rule:
    """``t2/refactor.py`` ``Rule``: ``match`` sceglie i nodi, ``build`` il testo nuovo."""

    name = ""

    def __init__(self, src: _Source, tree: ast.Module, names: Optional[NameFactory]) -> None:
        self.src = src
        self.tree = tree
        self.names = names
        self.parents = _parents(tree)

    def match(self, node: ast.AST) -> bool:
        raise NotImplementedError

    def build(self, node: ast.AST, r: _Renderer) -> str:
        raise NotImplementedError


class _Renderer:
    """``t2/refactor.py`` ``rewrite``: testo di un nodo con la regola applicata in ogni nodo che la
    soddisfa, anche annidato (il testo di un nodo trasformato usa quello già trasformato dei
    figli)."""

    def __init__(self, src: _Source, rule: _Rule) -> None:
        self.src = src
        self.rule = rule
        self.count = 0

    def node(self, node: ast.AST) -> str:
        if self.rule.match(node):
            self.count += 1
            return self.rule.build(node, self)
        start, end = self.src.span(node)
        return self.span(start, end, _children(node, self.src))

    def block(self, stmts: Sequence[ast.stmt]) -> str:
        return self.span(self.src.start(stmts[0]), self.src.end(stmts[-1]), list(stmts))

    def span(self, start: int, end: int, children: Sequence[ast.AST]) -> str:
        code = self.src.code
        out: list[str] = []
        pos = start
        for child in children:
            cs, ce = self.src.span(child)
            if cs < pos or ce > end:
                continue  # es. decoratori, prima dell'inizio del nodo in ast
            out.append(code[pos:cs])
            out.append(self.node(child))
            pos = ce
        out.append(code[pos:end])
        return "".join(out)


def _numeric(node: Optional[ast.AST]) -> bool:
    """``NUMBERS`` di tree-sitter: letterali interi e decimali (non i booleani)."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float, complex))
        and not isinstance(node.value, bool)
    )


def _numeric_literal(node: Optional[ast.AST]) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _numeric_literal(node.operand)
    return _numeric(node)


def _bound_names(stmts: Sequence[ast.stmt]) -> set[str]:
    """``t2/refactor.py`` ``_bound_names``: identificatori nei bersagli di assegnazioni, ``for``,
    comprehension, ``:=``, ``with ... as``, ``except ... as``, ``del``, ``global``,
    ``nonlocal`` (tutti quelli del bersaglio, anche ``i`` in ``a[i] = ...``)."""

    def idents(node: Optional[ast.AST]) -> set[str]:
        out: set[str] = set()
        for n in ast.walk(node) if node is not None else []:
            if isinstance(n, ast.Name):
                out.add(n.id)
            elif isinstance(n, ast.Attribute):
                out.add(n.attr)
        return out

    out: set[str] = set()
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    out |= idents(t)
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor, ast.NamedExpr,
                                ast.comprehension)):  # fmt: skip
                out |= idents(n.target)
            elif isinstance(n, ast.withitem):
                out |= idents(n.optional_vars)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                out.add(n.name)
            elif isinstance(n, ast.Delete):
                for t in n.targets:
                    out |= idents(t)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                out.update(n.names)
    return out


def _has_own_continue(stmts: Sequence[ast.stmt]) -> bool:
    """Un ``continue`` che riguarda il ciclo (nessun ciclo, funzione o classe in mezzo)."""
    stack: list[ast.AST] = list(stmts)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Continue):
            return True
        if isinstance(n, (ast.For, ast.AsyncFor, ast.While, *FUNCTIONS, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return False


def _identifier_positions(scope: ast.AST, src: _Source) -> list[tuple[str, int]]:
    """Identificatori di uno scope con la loro posizione (gli ``identifier`` di tree-sitter: nomi,
    attributi, parametri, argomenti con nome, nomi di ``def``/``class``, ``import``, ``global``)."""
    out: list[tuple[str, int]] = []
    for n in ast.walk(scope):
        pos = src.start(n) if _positioned(n) else None
        if isinstance(n, ast.Name):
            out.append((n.id, src.start(n)))
        elif isinstance(n, ast.Attribute):
            out.append((n.attr, src.end(n) - len(n.attr)))
        elif isinstance(n, ast.arg) and pos is not None:
            out.append((n.arg, pos))
        elif isinstance(n, ast.keyword) and n.arg and pos is not None:
            out.append((n.arg, pos))
        elif isinstance(n, (*FUNCTIONS, ast.ClassDef)):
            out.append((n.name, src.start(n)))
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                for part in [*a.name.split("."), *([a.asname] if a.asname else [])]:
                    out.append((part, src.start(n)))
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.extend((name, src.start(n)) for name in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.append((n.name, src.start(n)))
    return out


class _ForToWhile(_Rule):
    """``t2/refactor.py`` ``ForToWhilePython``: ``for v in range(...)`` con passo letterale non
    nullo → ``v = start`` / ``while v < stop:`` / ``v += step``. Esclusi ``else`` del ciclo,
    ``continue`` che lo riguarda, ``v`` riassegnata nel corpo o nominata altrove nella funzione,
    corpo sulla riga del ``for``; ``stop`` in una temporanea se non è un letterale o un nome mai
    riassegnato nel corpo."""

    name = "for_to_while"

    def _range_args(self, node: ast.For) -> Optional[list[ast.expr]]:
        call = node.iter
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            return None
        if call.func.id != "range" or call.keywords or not 1 <= len(call.args) <= 3:
            return None
        if any(isinstance(a, ast.Starred) for a in call.args):
            return None
        return list(call.args)

    def _step(self, values: list[ast.expr]) -> Optional[int]:
        if len(values) < 3:
            return 1
        text = self.src.text(values[2]).replace(" ", "")
        if not re.fullmatch(r"-?\d+", text):
            return None
        return int(text) or None

    def _scope(self, node: ast.AST) -> ast.AST:
        cur = self.parents.get(id(node))
        while cur is not None:
            if isinstance(cur, (*FUNCTIONS, ast.Lambda)):
                return cur
            cur = self.parents.get(id(cur))
        return self.tree

    def match(self, node: ast.AST) -> bool:
        if type(node) is not ast.For or node.orelse or not isinstance(node.target, ast.Name):
            return False
        values = self._range_args(node)
        if values is None or self._step(values) is None:
            return False
        name = node.target.id
        if (
            self.src.row(self.src.start(node.body[0])) == self.src.row(self.src.start(node))
            or _has_own_continue(node.body)
            or name in _bound_names(node.body)
            or any(isinstance(n, ast.Name) and n.id == name for v in values for n in ast.walk(v))
        ):
            return False
        start, end = self.src.span(node)
        return not any(
            ident == name and not start <= pos < end
            for ident, pos in _identifier_positions(self._scope(node), self.src)
        )

    def build(self, node: ast.AST, r: _Renderer) -> str:
        assert isinstance(node, ast.For) and isinstance(node.target, ast.Name)
        values = self._range_args(node)
        assert values is not None
        name = node.target.id
        step = self._step(values) or 1
        texts = [r.node(v) for v in values]
        start, stop = ("0", texts[0]) if len(texts) == 1 else (texts[0], texts[1])
        stop_node = values[0] if len(values) == 1 else values[1]
        ind = self.src.indent(self.src.start(node))
        prefix = f"{name} = {start}\n{ind}"
        if not (
            _numeric(stop_node)
            or (isinstance(stop_node, ast.Name) and stop_node.id not in _bound_names(node.body))
        ):
            temp = self.names.random() if self.names else "_stop"
            prefix += f"{temp} = {stop}\n{ind}"
            stop = temp
        code = self.src.code
        colon = code.index(":", self.src.end(node.iter)) + 1
        body_start = self.src.start(node.body[0])
        cmp = " < " if step > 0 else " > "
        body_ind = self.src.indent(body_start)
        return (
            f"{prefix}while {name}{cmp}{stop}:{code[colon:body_start]}{r.block(node.body)}\n"
            f"{body_ind}{name} += {step}"
        )


class _IfElseInversion(_Rule):
    """``t2/refactor.py`` ``IfElseInversion`` (Python): ``if c: A else: B`` →
    ``if not (c): B else: A``. Escluse le catene ``elif``, i rami sulla riga di ``if``/``else`` e i
    due blocchi con indentazione diversa."""

    name = "if_else_inversion"
    _ELSE = re.compile(r"\belse\s*:")

    def _parts(self, node: ast.AST) -> Optional[tuple[int, int]]:
        """(inizio della parola ``else``, ``None`` se non applicabile)."""
        if not isinstance(node, ast.If) or not node.orelse:
            return None
        first_alt = node.orelse[0]
        if isinstance(first_alt, ast.If) and self.src.code.startswith(
            "elif", self.src.start(first_alt)
        ):
            return None
        gap_start, gap_end = self.src.end(node.body[-1]), self.src.start(first_alt)
        found = list(self._ELSE.finditer(self.src.code, gap_start, gap_end))
        if not found:
            return None
        else_at = found[-1].start()
        cons, body = self.src.start(node.body[0]), self.src.start(first_alt)
        if self.src.row(cons) == self.src.row(self.src.start(node)) or self.src.row(
            body
        ) == self.src.row(else_at):
            return None
        if self.src.column(cons) != self.src.column(body):
            return None
        return else_at, body

    def match(self, node: ast.AST) -> bool:
        return self._parts(node) is not None

    def build(self, node: ast.AST, r: _Renderer) -> str:
        assert isinstance(node, ast.If)
        code = self.src.code
        start = self.src.start(node)
        cs, ce = self.src.span(node.test)
        body_s, body_e = self.src.start(node.body[0]), self.src.end(node.body[-1])
        alt_s = self.src.start(node.orelse[0])
        return (
            code[start:cs] + "not (" + r.node(node.test) + ")" + code[ce:body_s]
            + r.block(node.orelse) + code[body_e:alt_s] + r.block(node.body)
        )  # fmt: skip


_PY_ALWAYS = frozenset({"/=", "//=", "%=", "**=", "<<=", ">>="})
_PY_LITERAL_ONLY = frozenset({"+=", "-="})


class _CompoundAssignment(_Rule):
    """``t2/refactor.py`` ``CompoundAssignment`` (Python): ``x op= e`` → ``x = x op (e)`` con
    ``x`` nome semplice; ``/=``, ``//=``, ``%=``, ``**=``, ``<<=``, ``>>=`` sempre, ``+=`` e ``-=``
    solo con ``e`` letterale numerico."""

    name = "compound_assignment"

    def _op(self, node: ast.AugAssign) -> str:
        return self.src.code[self.src.end(node.target) : self.src.start(node.value)].strip()

    def match(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.AugAssign) or not isinstance(node.target, ast.Name):
            return False
        op = self._op(node)
        return op in _PY_ALWAYS or (op in _PY_LITERAL_ONLY and _numeric_literal(node.value))

    def build(self, node: ast.AST, r: _Renderer) -> str:
        assert isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
        name = node.target.id
        return f"{name} = {name} {self._op(node)[:-1]} ({r.node(node.value)})"


def _binary_parts(node: ast.AST, src: _Source) -> Optional[tuple[ast.expr, ast.AST, ast.expr]]:
    op: ast.AST
    if isinstance(node, ast.BinOp):
        left, op, right = node.left, node.op, node.right
    elif isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, op, right = node.left, node.ops[0], node.comparators[0]
    else:
        return None
    # operandi fra parentesi: in tree-sitter sono ``parenthesized_expression``, non atomi
    if src.start(left) != src.start(node) or src.end(right) != src.end(node):
        return None
    return left, op, right


def _atoms_ok(left: ast.expr, right: ast.expr, src: _Source) -> bool:
    def atom(n: ast.expr) -> bool:
        return isinstance(n, ast.Name) or _numeric(n)

    if not (atom(left) and atom(right)):
        return False
    if not (isinstance(left, ast.Name) or isinstance(right, ast.Name)):
        return False
    return src.text(left) != src.text(right)


class _CommutativeSwap(_Rule):
    """``t2/refactor.py`` ``CommutativeSwap``: ``a * b``, ``a == b``, ``a != b`` con operandi
    nomi o numeri (almeno un nome) → operandi scambiati."""

    name = "commutative_swap"

    def match(self, node: ast.AST) -> bool:
        parts = _binary_parts(node, self.src)
        return (
            parts is not None
            and isinstance(parts[1], (ast.Mult, ast.Eq, ast.NotEq))
            and _atoms_ok(parts[0], parts[2], self.src)
        )

    def build(self, node: ast.AST, r: _Renderer) -> str:
        parts = _binary_parts(node, self.src)
        assert parts is not None
        left, _op, right = parts
        middle = self.src.code[self.src.end(left) : self.src.start(right)]
        return r.node(right) + middle + r.node(left)


_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}
_FLIP_OPS = {ast.Lt: "<", ast.Gt: ">", ast.LtE: "<=", ast.GtE: ">="}


class _ComparisonFlip(_Rule):
    """``t2/refactor.py`` ``ComparisonFlip``: ``a < b`` → ``b > a`` (e ``<=``/``>=``), stesse
    condizioni sugli operandi."""

    name = "comparison_flip"

    def match(self, node: ast.AST) -> bool:
        parts = _binary_parts(node, self.src)
        return (
            parts is not None
            and type(parts[1]) in _FLIP_OPS
            and isinstance(node, ast.Compare)
            and _atoms_ok(parts[0], parts[2], self.src)
        )

    def build(self, node: ast.AST, r: _Renderer) -> str:
        parts = _binary_parts(node, self.src)
        assert parts is not None
        left, op, right = parts
        text = _FLIP_OPS[type(op)]  # type: ignore[index]
        middle = self.src.code[self.src.end(left) : self.src.start(right)].replace(
            text, _FLIP[text], 1
        )
        return r.node(right) + middle + r.node(left)


# Ordine fisso di applicazione (``CATALOG`` di ``t2/refactor.py``, voci Python).
CATALOG: dict[str, type[_Rule]] = {
    "for_to_while": _ForToWhile,
    "if_else_inversion": _IfElseInversion,
    "compound_assignment": _CompoundAssignment,
    "commutative_swap": _CommutativeSwap,
    "comparison_flip": _ComparisonFlip,
}


def _rule_for(code: str, type_name: str, names: Optional[NameFactory]) -> tuple[_Source, _Rule]:
    src = _Source(code)
    tree = ast.parse(code)
    return src, CATALOG[type_name](src, tree, names)


def ast_applicable(code: str) -> dict[str, int]:
    """``ast_applicable``: punti di ogni tipo del catalogo (solo i tipi con almeno un punto)."""
    out = {}
    for type_name in CATALOG:
        _src, rule = _rule_for(code, type_name, None)
        n = sum(1 for node in ast.walk(rule.tree) if rule.match(node))
        if n:
            out[type_name] = n
    return out


def apply_ast_type(
    code: str, type_name: str, names: Optional[NameFactory]
) -> Optional[tuple[str, int]]:
    """``apply_ast_type``: un tipo in tutti i suoi punti; ``None`` se il risultato non si analizza
    più."""
    src, rule = _rule_for(code, type_name, names)
    renderer = _Renderer(src, rule)
    new = renderer.span(0, len(code), _children(rule.tree, src))
    if not renderer.count:
        return code, 0
    if not parses(new):
        return None
    return new, renderer.count


def _t2_1(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T2.1 refactoring a regole: ``t2/refactor.py`` ``RefactorAttack.apply_types`` e
    ``_finish``, **solo il catalogo AST** per Python (``for_to_while``, ``if_else_inversion``,
    ``compound_assignment``, ``commutative_swap``, ``comparison_flip``). Differenza: le regole
    Ruff del benchmark (``ruff check --fix`` con 15 tipi di regola equivalenti ad ACW) mancano,
    quindi i ``b`` tipi si estraggono fra i soli tipi AST applicabili."""
    if not code.strip():
        return UNCHANGED, code, {"empty": True}
    if not parses(code):
        return _tool_error(code, "the code does not parse", {})
    applicable = ast_applicable(code)
    types = sorted(applicable)
    b = params["b"]
    chosen = types if b == "all" or len(types) <= int(b) else sorted(rng.sample(types, int(b)))
    names = NameFactory(rng, identifiers_in(code))
    points: dict[str, int] = {}
    rejected: list[str] = []
    current = code
    for type_name in CATALOG:
        if type_name not in chosen:
            continue
        result = apply_ast_type(current, type_name, names)
        if result is None:
            rejected.append(type_name)
            continue
        current, n = result
        if n:
            points[type_name] = n
    detail = {"n_types_applicable": len(applicable), "chosen": chosen, "applied": sorted(points),
              "points": points, "rejected": rejected}  # fmt: skip
    return _outcome(code, current, detail)


# ============================================================================ T2.4 e T2.4k
def _all_functions(tree: ast.AST) -> list[ast.AST]:
    return [n for n in _preorder(tree) if isinstance(n, FUNCTIONS)]


def _outermost_functions(tree: ast.AST) -> list[ast.AST]:
    found: list[ast.AST] = []
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, FUNCTIONS):
            found.append(node)
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return found


def _line_start(code: str, offset: int) -> int:
    start = code.rfind("\n", 0, offset) + 1
    return start if not code[start:offset].strip() else offset


def _line_end(code: str, offset: int) -> int:
    end = code.find("\n", offset)
    end = len(code) if end < 0 else end
    return end + 1 if not code[offset:end].strip() and end < len(code) else offset


def _top_level(tree: ast.Module) -> list[ast.stmt]:
    out = []
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom, *FUNCTIONS)):
            continue
        if isinstance(node, ast.ClassDef) and node.decorator_list:
            continue  # ``decorated_definition`` di tree-sitter
        if i == 0 and _is_docstring(node):
            continue
        out.append(node)
    return out


def _t2_4(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T2.4 troncamento: ``t2/truncate.py`` ``TruncateAttack.apply``: si tengono le prime
    ``max(1, ⌊p·n⌋)`` istruzioni del corpo bersaglio (docstring esclusa). Differenza: il
    bersaglio è la funzione ``target`` (vuoto = la prima funzione del file) invece della funzione
    d'ingresso del problema; con ``target`` = ``-`` vale la regola senza funzione d'ingresso
    (``main`` se c'è, altrimenti le istruzioni di primo livello)."""
    if not code.strip():
        return NOT_APPLICABLE, code, {"reason": "extraction_failed"}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return _tool_error(code, f"SyntaxError: {exc}", {})
    src = _Source(code)
    functions = _all_functions(tree)
    wanted = str(params.get("target") or "").strip()
    if not wanted and functions:
        wanted = str(getattr(functions[0], "name", ""))
    if wanted == "-":
        wanted = ""
    kind: str
    if wanted:
        fn = next((f for f in functions if getattr(f, "name", None) == wanted), None)
        if fn is None:
            return NOT_APPLICABLE, code, {"reason": "entry_not_found"}
        kind, body = "entry", list(fn.body)  # type: ignore[attr-defined]
    else:
        fn = next((f for f in functions if getattr(f, "name", None) == "main"), None)
        kind, body = ("main", list(fn.body)) if fn is not None else ("top_level", [])  # type: ignore[attr-defined]
    statements = _top_level(tree) if kind == "top_level" else body
    if kind != "top_level" and statements and _is_docstring(statements[0]):
        statements = statements[1:]
    n = len(statements)
    keep = max(1, math.floor(float(params["p"]) * n)) if n else 0
    detail: dict[str, Any] = {"p": params["p"], "target": kind, "function": wanted or None,
                              "n": n, "kept": keep}  # fmt: skip
    if keep >= n:
        return UNCHANGED, code, {**detail, "removed": 0}
    dropped = statements[keep:]
    if kind == "top_level":
        spans = [(_line_start(code, src.start(s)), _line_end(code, src.end(s))) for s in dropped]
    else:
        spans = [(src.end(statements[keep - 1]), src.end(statements[-1]))]
    new = code
    for start, end in sorted(spans, reverse=True):
        new = new[:start] + new[end:]
    detail.update(removed=n - keep, parses=parses(new))
    return _outcome(code, new, detail)


def _t2_4k(
    code: str, params: dict[str, Any], rng: random.Random
) -> tuple[str, str, dict[str, Any]]:
    """T2.4 in k funzioni: ``t2/truncate_k.py`` ``TruncateKAttack.apply``: si tengono ``k``
    funzioni più esterne scelte col seme (con i loro decoratori) e si tolgono le altre; con meno
    di 2 funzioni l'attacco non si applica. Nessuna differenza oltre all'analisi con ``ast``."""
    if not code.strip():
        return NOT_APPLICABLE, code, {"reason": "extraction_failed"}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return _tool_error(code, f"SyntaxError: {exc}", {})
    src = _Source(code)
    functions = sorted(_outermost_functions(tree), key=src.start)
    n, k = len(functions), int(params["k"])
    detail: dict[str, Any] = {"k": k, "n": n}
    if n < 2:
        return NOT_APPLICABLE, code, {**detail, "reason": "single_function"}
    names = [str(getattr(f, "name", "?")) for f in functions]
    if k >= n:
        return UNCHANGED, code, {**detail, "kept": names, "removed": 0}
    keep = sorted(rng.sample(range(n), k))
    spans = []
    for i, fn in enumerate(functions):
        if i in keep:
            continue
        start = min([src.start(fn), *(src.start(d) - 1 for d in fn.decorator_list)])  # type: ignore[attr-defined]
        end = src.end(fn)
        line_start = code.rfind("\n", 0, start) + 1
        if not code[line_start:start].strip():
            start = line_start
        line_end = code.find("\n", end)
        line_end = len(code) if line_end < 0 else line_end
        if not code[end:line_end].strip():
            end = min(len(code), line_end + 1)
        spans.append((start, end))
    new = code
    for start, end in sorted(spans, reverse=True):
        new = new[:start] + new[end:]
    detail.update(kept=[names[i] for i in keep], removed=n - k, parses=parses(new))
    return _outcome(code, new, detail)


# ============================================================================ T2.5
# Funzioni umane per la diluizione: MBPP ``task_id`` 2, 5, 8, 9 (campo ``code``), dalla fixture
# ``tests/fixtures/tiny_functions.jsonl`` (PROVENANCE.md; licenza CC BY 4.0). Il benchmark usa la
# raccolta della fase ``function_pools``.
FUNCTION_POOL: tuple[str, ...] = (
    "def similar_elements(test_tup1, test_tup2):\n  res = tuple(set(test_tup1) & set(test_tup2))\n"
    "  return (res) ",
    "def count_ways(n): \n\tA = [0] * (n + 1) \n\tB = [0] * (n + 1) \n\tA[0] = 1\n\tA[1] = 0\n"
    "\tB[0] = 0\n\tB[1] = 1\n\tfor i in range(2, n+1): \n\t\tA[i] = A[i - 2] + 2 * B[i - 1] \n"
    "\t\tB[i] = A[i - 1] + B[i - 2] \n\treturn A[n] ",
    "def square_nums(nums):\n square_nums = list(map(lambda x: x ** 2, nums))\n return square_nums",
    "def find_Rotations(str): \n    tmp = str + str\n    n = len(str) \n"
    "    for i in range(1,n + 1): \n        substring = tmp[i: i+n] \n"
    "        if (str == substring): \n            return i \n    return n ",
)
POSITIONS = ("before", "after", "around")
_DEF_NAME = re.compile(r"^(\s*(?:async\s+)?def\s+)([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def _insertion_line(tree: ast.Module) -> int:
    end = 0
    for i, stmt in enumerate(tree.body):
        docstring = i == 0 and _is_docstring(stmt)
        if not (docstring or isinstance(stmt, (ast.Import, ast.ImportFrom))):
            break
        end = stmt.end_lineno or stmt.lineno
    return end


def dilute(code: str, functions: list[str], position: str, tree: ast.Module) -> str:
    """``t2/dilution.py`` ``dilute``."""
    n_before = {"before": len(functions), "after": 0}.get(position, math.ceil(len(functions) / 2))
    head, tail = functions[:n_before], functions[n_before:]
    lines = code.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    cut = _insertion_line(tree)
    top, rest = "".join(lines[:cut]), "".join(lines[cut:])

    def block(fs: list[str]) -> str:
        return "\n\n".join(f.rstrip("\n") + "\n" for f in fs)

    out = top
    if head:
        if top.strip():
            out = top.rstrip("\n") + "\n\n\n"
        out += block(head)
        out += "\n\n" + rest.lstrip("\n") if rest.strip() else rest.lstrip("\n")
    else:
        out += rest
    if tail:
        out = out.rstrip("\n") + "\n\n\n" + block(tail)
    return out


def _t2_5(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T2.5 diluizione: ``t2/dilution.py`` ``DilutionAttack.apply``: ``n`` funzioni umane
    scelte col seme, aggiunte a livello di modulo (``before``, ``after``, ``around``) e mai
    chiamate; una ``def`` che collide con un nome del file diventa ``<nome>_ext<k>``. Differenza:
    la raccolta è ``FUNCTION_POOL`` (4 funzioni di MBPP) invece della fase ``function_pools``."""
    n, position = int(params["n"]), str(params["position"])
    if not code.strip():
        return NOT_APPLICABLE, code, {"reason": "empty_code"}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return _tool_error(code, f"SyntaxError: {exc}", {"n_inserted": 0})
    ids = rng.sample(range(len(FUNCTION_POOL)), min(n, len(FUNCTION_POOL)))
    blocked = identifiers_in(code) | RESERVED
    chosen, names = [], []
    renamed = 0
    for i in ids:
        fn = FUNCTION_POOL[i]
        name = ast.parse(fn).body[0].name  # type: ignore[attr-defined]
        new, k = name, 0
        while new in blocked:
            k += 1
            new = f"{name}_ext{k}"
        if k:
            fn = _DEF_NAME.sub(lambda m, new=new: m.group(1) + new, fn, count=1)  # type: ignore[misc]
            renamed += 1
        blocked.add(new)
        names.append(new)
        chosen.append(fn)
    detail = {"n_inserted": len(ids), "names": names, "position": position, "n_renamed": renamed}
    new_code = dilute(code, chosen, position, tree)
    if not parses(new_code):
        return _tool_error(code, "diluted code does not parse", detail)
    return APPLIED, new_code, detail


# ============================================================================ T1.1, T1.2, T4.1
# Strumenti esterni dell'extra ``demo``, con le versioni fissate nel benchmark
# (``requirements-bench-core.lock`` di wm-bench@8f5588a). Si importano o si lanciano solo qui.
DEMO_EXTRA_HINT = "richiede pip install multimark[demo]"
TOOL_PINS = {"black": "24.10.0", "ruff": "0.7.4", "python-minifier": "2.11.3"}
_TOOL_MODULE = {"black": "black", "ruff": "ruff", "python-minifier": "python_minifier"}
_ATTACK_TOOL = {"T1.1": "black", "T1.2": "ruff", "T4.1": "python-minifier"}
RUFF_TIMEOUT_S = 60


def _have_module(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def tool_version(tool: str) -> Optional[str]:
    """Versione installata del pacchetto ``tool`` (``None`` se manca)."""
    try:
        return importlib.metadata.version(tool)
    except importlib.metadata.PackageNotFoundError:
        return None


def unavailable(attack_id: str) -> Optional[str]:
    """``None`` se l'attacco si può applicare, altrimenti la scritta per la pagina
    (``DEMO_EXTRA_HINT``): solo T1.1, T1.2 e T4.1 dipendono da pacchetti dell'extra ``demo``."""
    tool = _ATTACK_TOOL.get(attack_id)
    if tool is None or _have_module(_TOOL_MODULE[tool]):
        return None
    return DEMO_EXTRA_HINT


def _tool_detail(tool: str) -> dict[str, Any]:
    return {"tool": tool, "version": tool_version(tool), "pinned": TOOL_PINS[tool]}


def _with_tool(
    attack_id: str, code: str, run: Callable[[], str]
) -> tuple[str, str, dict[str, Any]]:
    """``ToolAttack.apply_many`` e ``ToolAttack._python`` di ``t1/tooling.py``: codice vuoto
    ``UNCHANGED``, eccezione del tool ``TOOL_ERROR`` con il codice originale, altrimenti
    ``outcome``. In più: se il pacchetto manca, ``NOT_APPLICABLE`` con ``DEMO_EXTRA_HINT``."""
    tool = _ATTACK_TOOL[attack_id]
    hint = unavailable(attack_id)
    if hint is not None:
        return NOT_APPLICABLE, code, {"tool": tool, "reason": hint}
    detail = _tool_detail(tool)
    if not code.strip():
        return UNCHANGED, code, {**detail, "empty": True}
    try:
        new = run()
    except Exception as exc:  # i tool sollevano errori diversi per codice non valido
        return _tool_error(code, f"{type(exc).__name__}: {exc}", detail)
    return _outcome(code, new, detail)


def _t1_1(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T1.1 formattazione: ``t1/tooling.py`` ``FormatAttack.apply_python`` (Python in processo):
    ``black.format_str(code, mode=black.Mode())``. Differenze: nessuna, con black 24.10.0
    dell'extra ``demo``."""

    def run() -> str:
        import black

        return str(black.format_str(code, mode=black.Mode()))

    return _with_tool("T1.1", code, run)


def _ruff_fix(code: str) -> str:
    """``attacks/tools.py`` ``ToolRunner._ruff`` e ``_run_chunk`` su un solo file: ``ruff check
    --fix --isolated --no-cache --quiet`` (regole di default) con l'interprete corrente; codici
    di uscita 0 e 1 accettati (1 = restano violazioni non correggibili)."""
    with tempfile.TemporaryDirectory(prefix="ruff_") as tmp:
        path = Path(tmp) / "f00000.py"
        path.write_bytes(code.encode("utf-8"))  # come write_text(newline=""): a capo invariati
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--fix", "--isolated", "--no-cache",
             "--quiet", path.name],
            cwd=tmp, capture_output=True, text=True, timeout=RUFF_TIMEOUT_S, check=False,
        )  # fmt: skip
        if proc.returncode not in (0, 1):
            raise RuntimeError((proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}")
        return path.read_text(encoding="utf-8")


def _t1_2(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T1.2 lint con correzione automatica: ``t1/tooling.py`` ``LintAttack`` (Python: tool
    ``ruff``) e ``attacks/tools.py`` ``ToolRunner._ruff``. Differenze: un file alla volta invece
    dei lotti del benchmark, nessun ambiente dei tool separato (``ruff`` 0.7.4 dell'extra
    ``demo``, lanciato con l'interprete corrente). Come nel benchmark, un file con errori di
    sintassi resta com'è (``UNCHANGED``)."""
    return _with_tool("T1.2", code, lambda: _ruff_fix(code))


def _t4_1(code: str, params: dict[str, Any], rng: random.Random) -> tuple[str, str, dict[str, Any]]:
    """T4.1 minificazione: ``t4/minify.py`` ``MinifyAttack.apply_python``:
    ``python_minifier.minify(code, rename_locals=rename, rename_globals=False)`` con le altre
    trasformazioni di default. Differenze: nessuna, con python-minifier 2.11.3 dell'extra
    ``demo``."""
    rename = bool(params["rename"])

    def run() -> str:
        import python_minifier

        return str(python_minifier.minify(code, rename_locals=rename, rename_globals=False))

    return _with_tool("T4.1", code, run)


# ============================================================================ elenco
_Apply = Callable[[str, dict[str, Any], random.Random], tuple[str, str, dict[str, Any]]]
_FUNCS: dict[str, _Apply] = {
    "T1.1": _t1_1, "T1.2": _t1_2, "T1.3": _t1_3, "T1.4": _t1_4, "T1.5": _t1_5, "T1.6": _t1_6,
    "T2.1": _t2_1, "T2.4": _t2_4, "T2.4k": _t2_4k, "T2.5": _t2_5, "T4.1": _t4_1,
}  # fmt: skip
REMARK_ID = "T3.1"
# Nota fissa della pagina (elenco degli esclusi dal punto 1 di P7.d, vedi il docstring del modulo).
ATTACK_NOTE = (
    "Attacchi dimostrativi ricopiati dal benchmark; quelli basati su LLM (T2.2, T2.3) non sono "
    "disponibili qui, e nemmeno T4.2 (solo JavaScript), le regole Ruff di T2.1 o le raccolte di "
    "dati del benchmark (T1.3 insert, T1.4 natural). I risultati della tesi vengono dal "
    "benchmark."
)
ATTACKS: dict[str, AttackSpec] = {
    "T1.1": AttackSpec("T1.1", "T1.1 formattazione (black)", (), "t1/tooling.py"),
    "T1.2": AttackSpec("T1.2", "T1.2 lint con correzione automatica (ruff --fix)", (),
                       "t1/tooling.py"),
    "T1.3": AttackSpec("T1.3", "T1.3 rimozione dei commenti",
                       (ParamSpec("mode", "modo", "remove", ("remove",)),), "t1/comments.py"),
    "T1.4": AttackSpec("T1.4", "T1.4 rinomina di variabili locali e parametri",
                       (ParamSpec("ratio", "frazione rinominata", 0.5, (0.25, 0.5, 0.75, 1.0)),
                        ParamSpec("name_kind", "nomi nuovi", "random", ("random",))),
                       "t1/rename.py"),
    "T1.5": AttackSpec("T1.5", "T1.5 modifiche localizzate senza effetto",
                       (ParamSpec("k", "modifiche", 3, (1, 3, 5)),), "t1/local_edits.py"),
    "T1.6": AttackSpec("T1.6", "T1.6 nomi in snake_case",
                       (ParamSpec("caps", "costanti di modulo", "convert", ("convert", "keep")),),
                       "t1/snake_case.py"),
    "T2.1": AttackSpec("T2.1", "T2.1 refactoring a regole (catalogo AST)",
                       (ParamSpec("b", "tipi di regola", "all", (1, 2, 3, "all")),),
                       "t2/refactor.py"),
    "T2.4": AttackSpec("T2.4", "T2.4 troncamento del corpo",
                       (ParamSpec("p", "frazione tenuta", 0.5, (0.75, 0.5)),
                        ParamSpec("target", "funzione (vuoto = la prima)", "")),
                       "t2/truncate.py"),
    "T2.4k": AttackSpec("T2.4k", "T2.4k tiene k funzioni",
                        (ParamSpec("k", "funzioni tenute", 1, tuple(range(1, 11))),),
                        "t2/truncate_k.py"),
    "T2.5": AttackSpec("T2.5", "T2.5 diluizione con funzioni umane",
                       (ParamSpec("n", "funzioni aggiunte", 2, (1, 2, 3, 4)),
                        ParamSpec("position", "posizione", "around", POSITIONS)),
                       "t2/dilution.py"),
    "T4.1": AttackSpec("T4.1", "T4.1 minificazione (python-minifier)",
                       (ParamSpec("rename", "rinomina le variabili locali", True, (False, True)),),
                       "t4/minify.py"),
    REMARK_ID: AttackSpec(REMARK_ID, "T3.1 ri-marcatura con una seconda chiave",
                          (ParamSpec("message_hex", "messaggio (esadecimale)", "123456"),),
                          "t3/remark.py"),
}  # fmt: skip


def apply_attack(
    attack_id: str, code: str, params: dict[str, Any], seed: int = DEMO_SEED
) -> AttackResult:
    """Applica un attacco deterministico (non T3.1, vedi ``remark``) con ``random.Random(seed)``."""
    spec = ATTACKS[attack_id]
    full = {p.name: params.get(p.name, p.default) for p in spec.params}
    status, new, detail = _FUNCS[attack_id](code, full, random.Random(seed))
    return AttackResult(attack_id, full, seed, status, new, detail)


def remark(code: str, message_bits: str, key2: int, preset_name: str) -> AttackResult:
    """T3.1 per i metodi post-hoc: ``t3/remark.py`` ``RemarkAttack`` (``_post_hoc_multibit``): il
    metodo, con la stessa configurazione, riapplicato al codice marcato con una seconda chiave.
    ``PARTIAL`` è un inserimento riuscito, ``FAILED`` con ``no_sites`` è ``UNCHANGED``.
    Differenza: la seconda chiave è casuale e resta in memoria (nel benchmark è ``k2``). Il
    risultato non contiene la chiave."""
    from multimark.cli.demo import mark_code

    m = mark_code(code, message_bits, key2, preset_name)
    detail = {"embed_status": m.status, "n_sites": m.n_sites, "message": message_bits}
    if m.code is None:
        if m.reason == "no_sites":
            return AttackResult(REMARK_ID, {"message": message_bits}, 0, UNCHANGED, code, detail)
        return AttackResult(REMARK_ID, {"message": message_bits}, 0, TOOL_ERROR, code,
                            {**detail, "error": m.reason})  # fmt: skip
    status = APPLIED if m.code != code else UNCHANGED
    return AttackResult(REMARK_ID, {"message": message_bits}, 0, status, m.code, detail)


__all__ = ["ATTACKS", "AttackResult", "AttackSpec", "DEMO_EXTRA_HINT", "DEMO_SEED", "ParamSpec",
           "TOOL_PINS", "apply_attack", "parses", "remark", "tool_version",
           "unavailable"]  # fmt: skip
