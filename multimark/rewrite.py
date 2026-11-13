"""Scrittura con LibCST (PIPELINE_metodo.md §3.3.3, §3.6.4): forme dei siti strutturali e rinomina
delle variabili.

**Lettura e scrittura.** Quali siti esistono e che valore hanno lo decide solo l'``ast``
(``sites.py``, ``names.py``). LibCST serve solo a scrivere: il resto del file resta identico,
commenti compresi. Dopo la scrittura il chiamante (``embed.py``) rilegge con ``ast`` e annulla i
siti il cui valore non coincide.

**Dal sito ``ast`` al nodo CST.** Il nodo CST corrispondente è quello dello stesso tipo con la
stessa posizione d'inizio (§3.3.3). In LibCST la posizione di un nodo esclude le sue parentesi,
come nell'``ast``; le colonne ``ast`` sono in byte UTF-8 e si convertono in caratteri. Per i nodi
annidati dello stesso tipo con la stessa posizione (``a + 1 + 2``) decide l'ordine di visita: i
nodi di ciascun tipo si ordinano per (posizione, ordine di visita) in entrambi gli alberi e si
associano uno a uno; se i conteggi o le posizioni non coincidono, ``RewriteError``. I nodi dentro
le f-string sono esclusi da entrambe le parti (MD15).

**Forme non scrivibili.** Se la forma CST non è quella semplice attesa (es. ``L = []`` sulla
stessa riga di un'altra istruzione, il ramo di un ``if`` scritto sulla riga dell'``if``), il sito
resta com'è e la sua chiave torna in ``unwritable``: ``embed`` lo conta fra gli ``skipped_sites``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Optional

import libcst as cst
from libcst.metadata import (
    FunctionScope,
    GlobalScope,
    MetadataWrapper,
    PositionProvider,
    ScopeProvider,
)

from multimark._astindex import FUNCTION_TYPES, AstIndex, iter_preorder
from multimark.names import NameSite
from multimark.sites import Site


class RewriteError(RuntimeError):
    """Gli alberi ``ast`` e CST non si corrispondono (conteggi o posizioni diversi)."""


# ---------------------------------------------------------------------- corrispondenza ast → CST

_AST_TO_CST: dict[type, type] = {
    ast.Assign: cst.Assign,
    ast.AugAssign: cst.AugAssign,
    ast.Compare: cst.Comparison,
    ast.If: cst.If,
    ast.BinOp: cst.BinaryOperation,
    ast.List: cst.List,
    ast.Dict: cst.Dict,
    ast.Call: cst.Call,
    ast.Subscript: cst.Subscript,
    ast.Return: cst.Return,
    ast.For: cst.For,
    ast.FunctionDef: cst.FunctionDef,
    ast.AsyncFunctionDef: cst.FunctionDef,
}


class _Collector(cst.CSTVisitor):
    """Nodi CST dei tipi che servono, in ordine di visita, fuori dalle f-string."""

    def __init__(self) -> None:
        self.nodes: dict[type, list[cst.CSTNode]] = {t: [] for t in set(_AST_TO_CST.values())}
        self._fstring = 0

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, cst.FormattedString):
            self._fstring += 1
        elif self._fstring == 0 and type(node) in self.nodes:
            if not (isinstance(node, cst.For) and node.asynchronous is not None):
                self.nodes[type(node)].append(node)
        return True

    def on_leave(self, original_node: cst.CSTNode) -> None:
        if isinstance(original_node, cst.FormattedString):
            self._fstring -= 1


def _char_col(lines: list[str], lineno: int, col_bytes: int) -> int:
    line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
    return len(line.encode("utf-8")[:col_bytes].decode("utf-8", errors="replace"))


class CstMap:
    """Corrispondenza nodo ``ast`` → nodo CST per un modulo (stesso sorgente)."""

    def __init__(self, code: str, index: AstIndex, wrapper: MetadataWrapper) -> None:
        self.code = code
        self.index = index
        self.wrapper = wrapper
        positions = wrapper.resolve(PositionProvider)
        collector = _Collector()
        wrapper.module.visit(collector)
        lines = code.splitlines(keepends=True)
        in_fstring: set[int] = set()
        for node in index.order:
            if isinstance(node, ast.JoinedStr):
                in_fstring.update(id(n) for n in iter_preorder(node))
        self._map: dict[int, cst.CSTNode] = {}
        for ast_type, cst_type in _AST_TO_CST.items():
            if ast_type is ast.AsyncFunctionDef:
                continue
            a_nodes: list[Any]
            if ast_type is ast.FunctionDef:
                a_nodes = [n for n in index.order if isinstance(n, FUNCTION_TYPES)]
            else:
                a_nodes = [n for n in index.order if type(n) is ast_type]
            a_nodes = [n for n in a_nodes if id(n) not in in_fstring]
            c_nodes = collector.nodes[cst_type]
            if len(a_nodes) != len(c_nodes):
                raise RewriteError(
                    f"{ast_type.__name__}: {len(a_nodes)} ast nodes vs {len(c_nodes)} cst nodes"
                )
            a_sorted = sorted(
                a_nodes,
                key=lambda n: (n.lineno, n.col_offset, index.position[id(n)]),
            )
            order = {id(n): i for i, n in enumerate(c_nodes)}
            c_sorted = sorted(
                c_nodes,
                key=lambda n: (positions[n].start.line, positions[n].start.column, order[id(n)]),
            )
            for a, c in zip(a_sorted, c_sorted):
                if isinstance(a, FUNCTION_TYPES):
                    # In LibCST la posizione di una funzione parte dai decoratori, nell'ast dalla
                    # riga ``def``: per le funzioni si controlla il nome.
                    assert isinstance(c, cst.FunctionDef)
                    if c.name.value != a.name:
                        raise RewriteError(f"function {a.name} vs cst {c.name.value}")
                else:
                    start = positions[c].start
                    line, col = a.lineno, a.col_offset
                    if (start.line, start.column) != (line, _char_col(lines, line, col)):
                        raise RewriteError(
                            f"{ast_type.__name__} at {line}:{col} vs cst at "
                            f"{start.line}:{start.column}"
                        )
                self._map[id(a)] = c

    def cst_of(self, node: ast.AST) -> cst.CSTNode:
        return self._map[id(node)]


# ---------------------------------------------------------------------- utilità CST

_SPACE = cst.SimpleWhitespace(" ")


def _paren(e: Any) -> Any:
    if getattr(e, "lpar", None):
        return e
    return e.with_changes(lpar=[cst.LeftParen()], rpar=[cst.RightParen()])


def _paren_if(e: Any, kinds: tuple) -> Any:
    return _paren(e) if isinstance(e, kinds) and not e.lpar else e


_NON_ATOMS = (
    cst.BinaryOperation,
    cst.BooleanOperation,
    cst.Comparison,
    cst.UnaryOperation,
    cst.IfExp,
    cst.Lambda,
    cst.NamedExpr,
    cst.Await,
    cst.Yield,
)


def _ws(w: Any) -> Any:
    """Spazio intorno a una parola chiave (``is``): mai vuoto."""
    if isinstance(w, cst.SimpleWhitespace) and w.value == "":
        return _SPACE
    return w


_BIN_TO_AUG: dict[type, type] = {
    cst.Add: cst.AddAssign,
    cst.Subtract: cst.SubtractAssign,
    cst.Multiply: cst.MultiplyAssign,
    cst.Divide: cst.DivideAssign,
    cst.FloorDivide: cst.FloorDivideAssign,
    cst.Modulo: cst.ModuloAssign,
    cst.Power: cst.PowerAssign,
    cst.MatrixMultiply: cst.MatrixMultiplyAssign,
    cst.BitAnd: cst.BitAndAssign,
    cst.BitOr: cst.BitOrAssign,
    cst.BitXor: cst.BitXorAssign,
    cst.LeftShift: cst.LeftShiftAssign,
    cst.RightShift: cst.RightShiftAssign,
}
_AUG_TO_BIN = {v: k for k, v in _BIN_TO_AUG.items()}

_MIRROR: dict[type, type] = {
    cst.LessThan: cst.GreaterThan,
    cst.GreaterThan: cst.LessThan,
    cst.LessThanEqual: cst.GreaterThanEqual,
    cst.GreaterThanEqual: cst.LessThanEqual,
    cst.Equal: cst.Equal,
    cst.NotEqual: cst.NotEqual,
}


def _block_statements(body: Any) -> Optional[list]:
    """Istruzioni di un corpo come lista di istruzioni di blocco (``SimpleStatementSuite`` →
    una ``SimpleStatementLine``)."""
    if isinstance(body, cst.IndentedBlock):
        return list(body.body)
    if isinstance(body, cst.SimpleStatementSuite):
        return [cst.SimpleStatementLine(body=list(body.body))]
    return None


def _single_small(stmt: Any, kind: type) -> Optional[Any]:
    """La sola istruzione semplice di una ``SimpleStatementLine``, se è di tipo ``kind``."""
    if isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1:
        small = stmt.body[0]
        if isinstance(small, kind):
            return small
    return None


def _flatten_and(e: Any) -> list:
    if isinstance(e, cst.BooleanOperation) and isinstance(e.operator, cst.And) and not e.lpar:
        return _flatten_and(e.left) + _flatten_and(e.right)
    return [e]


def _and_chain(parts: list) -> Any:
    expr = parts[0]
    for p in parts[1:]:
        expr = cst.BooleanOperation(left=expr, operator=cst.And(), right=p)
    return expr


_AND_OPERAND_PARENS = (cst.IfExp, cst.Lambda, cst.NamedExpr)


def _and_operand(e: Any) -> Any:
    if isinstance(e, cst.BooleanOperation) and isinstance(e.operator, cst.Or) and not e.lpar:
        return _paren(e)
    return _paren_if(e, _AND_OPERAND_PARENS)


# ---------------------------------------------------------------------- scrittura dei siti


@dataclass(frozen=True)
class WriteRequest:
    """Sito ``ast`` da scrivere nella forma ``target`` (0 o 1)."""

    site: Site
    target: int


_STATEMENT_CHANNELS = ("list_comp", "ternary", "else_return")


class _Writer(cst.CSTTransformer):
    """Applica le forme richieste ai nodi CST pianificati (``id(nodo originale)`` → piano)."""

    def __init__(self, plan: dict[int, tuple[WriteRequest, dict]]) -> None:
        super().__init__()
        self.plan = plan
        self.unwritable: set[tuple] = set()

    # -- utilità
    def _get(self, node: cst.CSTNode, *channels: str) -> Optional[tuple[WriteRequest, dict]]:
        entry = self.plan.get(id(node))
        if entry is None or entry[0].site.channel not in channels:
            return None
        return entry

    def _fail(self, req: WriteRequest) -> None:
        self.unwritable.add(req.site.key)

    # -- canale 1
    def leave_Assign(self, original_node: cst.Assign, updated_node: cst.Assign) -> Any:
        entry = self._get(original_node, "aug_assign")
        if entry is None:
            return updated_node
        target = updated_node.targets[0]
        value = updated_node.value
        if not isinstance(value, cst.BinaryOperation) or value.lpar:
            self._fail(entry[0])
            return updated_node
        aug_op = _BIN_TO_AUG[type(value.operator)](
            whitespace_before=target.whitespace_before_equal,
            whitespace_after=target.whitespace_after_equal,
        )
        return cst.AugAssign(
            target=target.target,
            operator=aug_op,
            value=value.right,
            semicolon=updated_node.semicolon,
        )

    def leave_AugAssign(self, original_node: cst.AugAssign, updated_node: cst.AugAssign) -> Any:
        entry = self._get(original_node, "aug_assign")
        if entry is None:
            return updated_node
        aug: Any = updated_node.operator
        op = _AUG_TO_BIN[type(aug)](whitespace_before=_SPACE, whitespace_after=_SPACE)
        value = cst.BinaryOperation(
            left=updated_node.target.deep_clone(),
            operator=op,
            right=_paren_if(updated_node.value, _NON_ATOMS),
        )
        target = cst.AssignTarget(
            target=updated_node.target,
            whitespace_before_equal=aug.whitespace_before,
            whitespace_after_equal=aug.whitespace_after,
        )
        return cst.Assign(targets=[target], value=value, semicolon=updated_node.semicolon)

    # -- canali 2, 3, 8
    def leave_Comparison(self, original_node: cst.Comparison, updated_node: cst.Comparison) -> Any:
        entry = self._get(original_node, "compare_dir", "equality_dir", "none_check")
        if entry is None:
            return updated_node
        req = entry[0]
        target = updated_node.comparisons[0]
        op: Any = target.operator
        if req.site.channel == "none_check":
            before, after = _ws(op.whitespace_before), _ws(op.whitespace_after)
            new_op: Any
            if req.target == 1:
                kind = cst.Equal if isinstance(op, cst.Is) else cst.NotEqual
                new_op = kind(whitespace_before=before, whitespace_after=after)
            elif isinstance(op, cst.Equal):
                new_op = cst.Is(whitespace_before=before, whitespace_after=after)
            else:
                new_op = cst.IsNot(whitespace_before=before, whitespace_between=_SPACE,
                                   whitespace_after=after)  # fmt: skip
            return updated_node.with_changes(comparisons=[target.with_changes(operator=new_op)])
        mirrored = _MIRROR[type(op)](
            whitespace_before=op.whitespace_before, whitespace_after=op.whitespace_after
        )
        return updated_node.with_changes(
            left=target.comparator,
            comparisons=[target.with_changes(operator=mirrored, comparator=updated_node.left)],
        )

    # -- canali 6, 13
    def leave_BinaryOperation(
        self, original_node: cst.BinaryOperation, updated_node: cst.BinaryOperation
    ) -> Any:
        entry = self._get(original_node, "operand_order", "square")
        if entry is None:
            return updated_node
        req, info = entry
        if req.site.channel == "operand_order":
            return updated_node.with_changes(left=updated_node.right, right=updated_node.left)
        op: Any = updated_node.operator
        if req.target == 1:  # x * x → x ** 2
            power = cst.Power(
                whitespace_before=op.whitespace_before, whitespace_after=op.whitespace_after
            )
            return updated_node.with_changes(operator=power, right=cst.Integer("2"))
        mult = cst.Multiply(
            whitespace_before=op.whitespace_before, whitespace_after=op.whitespace_after
        )
        new = updated_node.with_changes(operator=mult, right=updated_node.left.deep_clone())
        return _paren(new) if info.get("parens") else new

    # -- canali 7, 9
    def leave_List(self, original_node: cst.List, updated_node: cst.List) -> Any:
        if self._get(original_node, "empty_coll") is None:
            return updated_node
        return cst.Call(func=cst.Name("list"), lpar=updated_node.lpar, rpar=updated_node.rpar)

    def leave_Dict(self, original_node: cst.Dict, updated_node: cst.Dict) -> Any:
        if self._get(original_node, "empty_coll") is None:
            return updated_node
        return cst.Call(func=cst.Name("dict"), lpar=updated_node.lpar, rpar=updated_node.rpar)

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> Any:
        entry = self._get(original_node, "empty_coll", "range_zero")
        if entry is None:
            return updated_node
        req = entry[0]
        if req.site.channel == "empty_coll":
            func = updated_node.func
            assert isinstance(func, cst.Name)
            if func.value == "list":
                return cst.List(elements=[], lpar=updated_node.lpar, rpar=updated_node.rpar)
            return cst.Dict(elements=[], lpar=updated_node.lpar, rpar=updated_node.rpar)
        args = list(updated_node.args)
        if req.target == 1:  # range(0, n) → range(n)
            return updated_node.with_changes(args=[args[1]])
        zero = cst.Arg(cst.Integer("0"), comma=cst.Comma(whitespace_after=_SPACE))
        return updated_node.with_changes(args=[zero, args[0]])

    # -- canale 10
    def leave_Subscript(self, original_node: cst.Subscript, updated_node: cst.Subscript) -> Any:
        entry = self._get(original_node, "slice_lower")
        if entry is None:
            return updated_node
        element = updated_node.slice[0]
        sl = element.slice
        if len(updated_node.slice) != 1 or not isinstance(sl, cst.Slice):
            self._fail(entry[0])
            return updated_node
        lower = cst.Integer("0") if entry[0].target == 0 else None
        return updated_node.with_changes(
            slice=[element.with_changes(slice=sl.with_changes(lower=lower))]
        )

    # -- canale 14
    def leave_Return(self, original_node: cst.Return, updated_node: cst.Return) -> Any:
        entry = self._get(original_node, "return_none")
        if entry is None:
            return updated_node
        if entry[0].target == 1:
            return updated_node.with_changes(
                value=None, whitespace_after_return=cst.MaybeSentinel.DEFAULT
            )
        return updated_node.with_changes(value=cst.Name("None"), whitespace_after_return=_SPACE)

    # -- canale 12
    def leave_If(self, original_node: cst.If, updated_node: cst.If) -> Any:
        entry = self._get(original_node, "nested_if")
        if entry is None:
            return updated_node
        req = entry[0]
        if req.target == 1:  # if a: if b: … → if a and b: …
            outer_body = updated_node.body
            inner = outer_body.body[0] if isinstance(outer_body, cst.IndentedBlock) else None
            if not isinstance(inner, cst.If) or len(outer_body.body) != 1:
                self._fail(req)
                return updated_node
            test = _and_chain([_and_operand(updated_node.test), _and_operand(inner.test)])
            body = inner.body
            if inner.leading_lines and isinstance(body, cst.IndentedBlock) and body.body:
                first: Any = body.body[0]
                body = body.with_changes(
                    body=[first.with_changes(leading_lines=[*inner.leading_lines,
                                                            *first.leading_lines]),
                          *body.body[1:]]
                )  # fmt: skip
            return updated_node.with_changes(test=test, body=body)
        test = updated_node.test
        if getattr(test, "lpar", None):
            test = test.with_changes(lpar=[], rpar=[])
        parts = _flatten_and(test)
        if len(parts) < 2:
            self._fail(req)
            return updated_node
        inner_if = cst.If(test=_and_chain(parts[1:]), body=updated_node.body)
        return updated_node.with_changes(test=parts[0], body=cst.IndentedBlock(body=[inner_if]))

    # -- canali 4, 5, 11: liste di istruzioni
    def leave_IndentedBlock(
        self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock
    ) -> Any:
        return updated_node.with_changes(
            body=self._rewrite_block(list(original_node.body), list(updated_node.body))
        )

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> Any:
        return updated_node.with_changes(
            body=self._rewrite_block(list(original_node.body), list(updated_node.body))
        )

    def _statement_entry(self, stmt: cst.CSTNode) -> Optional[tuple[WriteRequest, dict]]:
        """Piano di un'istruzione radice di un sito di canale 4, 5 o 11."""
        if isinstance(stmt, cst.SimpleStatementLine):
            for small in stmt.body:
                entry = self._get(small, "list_comp", "ternary")
                if entry is not None:
                    return entry
            return None
        return self._get(stmt, *_STATEMENT_CHANNELS)

    def _rewrite_block(self, orig: list, upd: list) -> list:
        new: list = []
        origin: list = []
        i = 0
        while i < len(orig):
            entry = self._statement_entry(orig[i])
            if entry is None or entry[0].site.channel == "else_return":
                new.append(upd[i])
                origin.append(orig[i])
                i += 1
                continue
            req = entry[0]
            out: Optional[list] = None
            consumed = 1
            if req.site.channel == "list_comp":
                if req.site.value == 0:
                    if i + 1 < len(upd):
                        out = self._loop_to_comp(upd[i], upd[i + 1])
                        consumed = 2
                else:
                    out = self._comp_to_loop(upd[i])
            else:  # ternary
                out = (
                    self._if_to_ifexp(upd[i]) if req.site.value == 0 else self._ifexp_to_if(upd[i])
                )
            if out is None:
                self._fail(req)
                new.append(upd[i])
                origin.append(orig[i])
                i += 1
                continue
            new.extend(out)
            origin.extend([None] * len(out))
            i += consumed
        # else_return, da destra verso sinistra (§3.3.1b riga 11)
        for j in range(len(new) - 1, -1, -1):
            o = origin[j]
            entry = self._get(o, "else_return") if o is not None else None
            if entry is None:
                continue
            req = entry[0]
            stmt = new[j]
            if req.site.value == 0:  # else: Y → Y dopo l'if
                moved = (
                    _block_statements(stmt.orelse.body)
                    if isinstance(stmt.orelse, cst.Else)
                    else None
                )
                if moved is None or j != len(new) - 1:
                    self._fail(req)
                    continue
                if stmt.orelse.leading_lines and moved:
                    moved[0] = moved[0].with_changes(
                        leading_lines=[*stmt.orelse.leading_lines, *moved[0].leading_lines]
                    )
                new[j : j + 1] = [stmt.with_changes(orelse=None), *moved]
                origin[j : j + 1] = [o, *([None] * len(moved))]
            else:  # Y dopo l'if → else: Y
                rest = new[j + 1 :]
                if not rest:
                    self._fail(req)
                    continue
                orelse = cst.Else(body=cst.IndentedBlock(body=rest))
                new[j:] = [stmt.with_changes(orelse=orelse)]
                origin[j:] = [o]
        return new

    def _loop_to_comp(self, assign_line: Any, loop: Any) -> Optional[list]:
        assign = _single_small(assign_line, cst.Assign)
        if assign is None or not isinstance(loop, cst.For) or loop.orelse is not None:
            return None
        body = _block_statements(loop.body)
        if body is None or len(body) != 1:
            return None
        expr_stmt = _single_small(body[0], cst.Expr)
        call = expr_stmt.value if expr_stmt is not None else None
        if not isinstance(call, cst.Call) or len(call.args) != 1:
            return None
        elt = _paren_if(call.args[0].value, (cst.NamedExpr,))
        it = loop.iter
        if isinstance(it, cst.Tuple) and not it.lpar:
            it = _paren(it)
        it = _paren_if(it, (cst.IfExp, cst.Lambda, cst.NamedExpr, cst.Yield))
        comp = cst.ListComp(elt=elt, for_in=cst.CompFor(target=loop.target, iter=it))
        line = assign_line.with_changes(body=[assign.with_changes(value=comp)])
        return [line]

    def _comp_to_loop(self, line: Any) -> Optional[list]:
        assign = _single_small(line, cst.Assign)
        comp = assign.value if assign is not None else None
        if not isinstance(comp, cst.ListComp) or comp.lpar:
            return None
        assert assign is not None
        target = assign.targets[0].target
        if not isinstance(target, cst.Name):
            return None
        first = line.with_changes(body=[assign.with_changes(value=cst.List(elements=[]))])
        append = cst.Expr(
            cst.Call(
                func=cst.Attribute(value=cst.Name(target.value), attr=cst.Name("append")),
                args=[cst.Arg(comp.elt)],
            )
        )
        loop = cst.For(
            target=comp.for_in.target,
            iter=comp.for_in.iter,
            body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[append])]),
        )
        return [first, loop]

    def _if_to_ifexp(self, stmt: Any) -> Optional[list]:
        if not isinstance(stmt, cst.If) or not isinstance(stmt.orelse, cst.Else):
            return None
        body, other = _block_statements(stmt.body), _block_statements(stmt.orelse.body)
        if body is None or other is None or len(body) != 1 or len(other) != 1:
            return None
        a, b = _single_small(body[0], cst.Assign), _single_small(other[0], cst.Assign)
        if a is None or b is None:
            return None
        branch = (cst.Lambda, cst.IfExp, cst.NamedExpr)

        def wrap(e: Any) -> Any:
            if isinstance(e, cst.Tuple) and not e.lpar:
                return _paren(e)
            return _paren_if(e, branch)

        value = cst.IfExp(test=wrap(stmt.test), body=wrap(a.value), orelse=wrap(b.value))
        line = cst.SimpleStatementLine(
            body=[a.with_changes(value=value, semicolon=cst.MaybeSentinel.DEFAULT)],
            leading_lines=stmt.leading_lines,
        )
        return [line]

    def _ifexp_to_if(self, line: Any) -> Optional[list]:
        assign = _single_small(line, cst.Assign)
        exp = assign.value if assign is not None else None
        if not isinstance(exp, cst.IfExp) or exp.lpar:
            return None
        assert assign is not None
        semicolon = cst.MaybeSentinel.DEFAULT
        a = assign.with_changes(value=exp.body, semicolon=semicolon)
        b = assign.with_changes(
            targets=[t.deep_clone() for t in assign.targets], value=exp.orelse, semicolon=semicolon
        )
        new_if = cst.If(
            test=exp.test,
            body=cst.IndentedBlock(
                body=[cst.SimpleStatementLine(body=[a])], header=line.trailing_whitespace
            ),
            orelse=cst.Else(body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[b])])),
            leading_lines=line.leading_lines,
        )
        return [new_if]


def _needs_mult_parens(site: Site, index: AstIndex) -> bool:
    """``x ** 2`` → ``x * x`` richiede parentesi se il genitore lega più di ``*``."""
    parent = index.parent_of(site.node)
    if isinstance(parent, (ast.UnaryOp, ast.Await)):
        return True
    return isinstance(parent, ast.BinOp) and not isinstance(parent.op, (ast.Add, ast.Sub))


def write_structural(
    code: str, index: AstIndex, requests: list[WriteRequest]
) -> tuple[str, set[tuple]]:
    """Scrive le forme richieste. Restituisce il codice e le chiavi dei siti non scrivibili."""
    todo = [r for r in requests if r.target != r.site.value]
    if not todo:
        return code, set()
    wrapper = MetadataWrapper(cst.parse_module(code))
    mapping = CstMap(code, index, wrapper)
    plan: dict[int, tuple[WriteRequest, dict]] = {}
    for req in todo:
        info: dict = {}
        if req.site.channel == "square":
            info["parens"] = _needs_mult_parens(req.site, index)
        plan[id(mapping.cst_of(req.site.node))] = (req, info)
    writer = _Writer(plan)
    new_module = wrapper.module.visit(writer)
    return new_module.code, writer.unwritable


# ---------------------------------------------------------------------- rinomina (§3.6.4)


class _Renamer(cst.CSTTransformer):
    def __init__(self, names: dict[int, str]) -> None:
        super().__init__()
        self.names = names

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> Any:
        new = self.names.get(id(original_node))
        return updated_node.with_changes(value=new) if new is not None else updated_node


def _subtree_ids(node: cst.CSTNode) -> set[int]:
    out: set[int] = set()

    class _V(cst.CSTVisitor):
        def on_visit(self, n: cst.CSTNode) -> bool:
            out.add(id(n))
            return True

    node.visit(_V())
    return out


def rename_variables(
    code: str, index: AstIndex, renames: list[tuple[NameSite, str]]
) -> tuple[str, set[tuple]]:
    """Rinomina le variabili sito (tutte le occorrenze del binding nella funzione, o nello scope
    del modulo, con ``ScopeProvider``). Restituisce il codice e le chiavi dei siti non
    rinominabili (accessi che non sono ``Name``, es. annotazioni in stringa)."""
    if not renames:
        return code, set()
    wrapper = MetadataWrapper(cst.parse_module(code))
    mapping = CstMap(code, index, wrapper)
    scopes = {id(s): s for s in wrapper.resolve(ScopeProvider).values() if s is not None}
    global_scope = next((s for s in scopes.values() if isinstance(s, GlobalScope)), None)
    targets: dict[int, str] = {}
    failed: set[tuple] = set()
    for site, new in renames:
        chosen: list[Any]
        if site.unit.is_module:
            chosen = [global_scope] if global_scope is not None else []
        else:
            assert site.unit.node is not None
            func = mapping.cst_of(site.unit.node)
            inside = _subtree_ids(func)
            chosen = [
                s
                for s in scopes.values()
                if isinstance(s, FunctionScope) and getattr(s, "node", None) is not None
                and id(s.node) in inside
            ]  # fmt: skip
        nodes: list[cst.Name] = []
        ok = True
        for scope in chosen:
            for assignment in scope.assignments[site.name]:
                node = getattr(assignment, "node", None)
                if isinstance(node, cst.Param):
                    node = node.name
                if not isinstance(node, cst.Name):
                    ok = False
                    break
                nodes.append(node)
                for access in assignment.references:
                    if not isinstance(access.node, cst.Name):
                        ok = False
                        break
                    nodes.append(access.node)
            if not ok:
                break
        if not ok or not nodes:
            failed.add(site.key)
            continue
        for node in nodes:
            targets[id(node)] = new
    new_module = wrapper.module.visit(_Renamer(targets))
    return new_module.code, failed
