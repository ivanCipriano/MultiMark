"""Controllo in sola lettura della rinomina: dati il codice originale e quello marcato, verifica che
ogni variabile di ogni scope dell'originale corrisponda a una sola variabile del marcato e viceversa
(biiezione fra variabili, non fra testi).

Si usa solo l'``ast`` della libreria standard (§0.1). Passi:

1. su ciascun lato, ogni occorrenza di nome (``Name`` in ogni contesto, parametri ``arg``) è
   risolta alla sua variabile con le regole di Python (``multimark.scopes``, più ``global`` e
   ``nonlocal`` per scope e i bersagli di ``NamedExpr``): l'identità è (scope, nome), oppure
   ``<free>`` per builtin e nomi non definiti;
2. le occorrenze dei due lati sono appaiate camminando i due alberi in parallelo: nodi dello stesso
   tipo si appaiano campo per campo; le liste di lunghezza diversa si allineano con ``difflib``
   sulla forma dei nodi con i nomi mascherati: sono certi i blocchi uguali lunghi almeno 2 o fra
   blocchi uguali; gli altri blocchi uguali e quelli sostituiti della stessa lunghezza sono incerti
   e si usano solo se coerenti con gli appaiamenti certi; i sottoalberi riscritti dai canali
   strutturali (tipi diversi) restano non appaiati. Un confronto o un'operazione commutativa con gli
   operandi scambiati (canali ``compare_dir``, ``equality_dir``, ``operand_order``) si appaia
   nell'ordine scambiato; se entrambi gli ordini sono possibili (es. ``a == b`` contro ``b == a``)
   l'appaiamento è ambiguo e si decide con gli appaiamenti certi, oppure si scarta;
3. dagli appaiamenti: una variabile dell'originale che corrisponde a due variabili del marcato (o
   viceversa) è una violazione.

Le variabili che compaiono solo in sottoalberi riscritti non vengono controllate: il risultato le
conta (``n_unpaired_original``, ``n_unpaired_marked``).
"""

from __future__ import annotations

import ast
import difflib
from dataclasses import dataclass, field
from typing import Optional, Union

from multimark._astindex import AstIndex
from multimark.scopes import ScopeResolver, _Scope

Identity = tuple[int, str]
_Pair = tuple[Identity, Identity]

#: Confronti con gli operandi scambiati: operatore originale → operatore dopo lo scambio.
_MIRROR = {
    ast.Lt: ast.Gt, ast.Gt: ast.Lt, ast.LtE: ast.GtE, ast.GtE: ast.LtE,
    ast.Eq: ast.Eq, ast.NotEq: ast.NotEq, ast.Is: ast.Is, ast.IsNot: ast.IsNot,
}  # fmt: skip
_COMMUTATIVE = (ast.Add, ast.Mult, ast.BitAnd, ast.BitOr, ast.BitXor)
_FREE = -1


class _Resolver(ScopeResolver):
    """``ScopeResolver`` che risolve anche i ``Name`` in ``Store``/``Del``, i parametri e i
    bersagli di ``NamedExpr``, con ``global``/``nonlocal`` dichiarati per scope."""

    def __init__(self, index: AstIndex) -> None:
        self._where: dict[int, _Scope] = {}
        self._args: dict[int, _Scope] = {}
        self._decl: dict[int, dict[str, str]] = {}
        super().__init__(index)

    def _arguments(self, args: ast.arguments, outer: _Scope, inner: _Scope) -> list:
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        params += [a for a in (args.vararg, args.kwarg) if a is not None]
        for a in params:
            self._args[id(a)] = inner
        return super()._arguments(args, outer, inner)

    def _enter(self, node: ast.AST, scope: _Scope) -> list[tuple[ast.AST, _Scope]]:
        if isinstance(node, ast.Name):
            self._where[id(node)] = scope
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            target = scope
            while target.kind == "comprehension" and target.parent is not None:
                target = target.parent
            self._where[id(node.target)] = target
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            kind = "global" if isinstance(node, ast.Global) else "nonlocal"
            for n in node.names:
                self._decl.setdefault(id(scope), {})[n] = kind
        return super()._enter(node, scope)

    def _declared(self, scope: _Scope, name: str) -> Optional[str]:
        return self._decl.get(id(scope), {}).get(name)

    def _nonlocal_owner(self, scope: _Scope, name: str) -> Optional[_Scope]:
        current = scope.parent
        while current is not None and current.kind != "module":
            if current.kind != "class":
                decl = self._declared(current, name)
                if decl == "global":
                    return self.module
                if decl is None and name in current.bindings:
                    return current
            current = current.parent
        return None

    def _owner(self, scope: _Scope, name: str, store: bool) -> Optional[_Scope]:
        current: Optional[_Scope] = scope
        while current is not None:
            if current.kind == "class" and current is not scope:
                current = current.parent
                continue
            decl = self._declared(current, name)
            if decl == "global":
                return self.module
            if decl == "nonlocal":
                return self._nonlocal_owner(current, name)
            if store or name in current.bindings:
                return current
            current = current.parent
        return None

    def identity(self, node: Union[ast.Name, ast.arg]) -> Identity:
        if isinstance(node, ast.arg):
            return (self._args[id(node)].position, node.arg)
        scope = self._where[id(node)]
        owner = self._owner(scope, node.id, not isinstance(node.ctx, ast.Load))
        return (_FREE, node.id) if owner is None else (owner.position, node.id)

    def label(self, ident: Identity) -> str:
        """Etichetta leggibile: ``scope:nome`` (``<module>``, ``f``, ``f.<lambda@3>``, ...)."""
        pos, name = ident
        if pos == _FREE:
            return f"<free>:{name}"
        return f"{self._scope_label(pos)}:{name}"

    def _scope_label(self, position: int) -> str:
        scopes = {s.position: s for s in self._all_scopes()}
        parts = []
        current: Optional[_Scope] = scopes[position]
        while current is not None and current.kind != "module":
            node = current.node
            line = getattr(node, "lineno", 0)
            if current.kind in ("function", "class"):
                parts.append(getattr(node, "name", "?"))
            else:
                parts.append(f"<{current.kind}@{line}>")
            current = current.parent
        return ".".join(reversed(parts)) or "<module>"

    def _all_scopes(self) -> list[_Scope]:
        out = {id(s): s for s in [*self._where.values(), *self._args.values(), self.module]}
        for s in list(out.values()):
            p = s.parent
            while p is not None:
                out[id(p)] = p
                p = p.parent
        return list(out.values())


def _shape(node: ast.AST) -> str:
    """Forma del nodo senza i nomi delle variabili (per decidere gli scambi di operandi)."""
    if isinstance(node, ast.Name):
        return "N"
    if isinstance(node, ast.arg):
        return "A"
    if isinstance(node, ast.Constant):
        return f"C({node.value!r})"
    parts = [type(node).__name__]
    for _, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            parts.append(_shape(value))
        elif isinstance(value, list):
            parts.append("[" + ",".join(_shape(v) for v in value if isinstance(v, ast.AST)) + "]")
        elif isinstance(value, str):
            parts.append(repr(value))
    return "(" + " ".join(parts) + ")"


class _Pairer:
    def __init__(self, orig: _Resolver, marked: _Resolver) -> None:
        self.orig = orig
        self.marked = marked
        self.pairs: list[tuple[_Pair, str, str]] = []
        self.ambiguous: list[list[list[tuple[_Pair, str, str]]]] = []
        #: appaiamenti incerti (blocchi sostituiti di più istruzioni): si usano solo se coerenti
        self.tentative: list[list[tuple[_Pair, str, str]]] = []

    def _record(self, o: Union[ast.Name, ast.arg], m: Union[ast.Name, ast.arg]) -> None:
        on = o.id if isinstance(o, ast.Name) else o.arg
        mn = m.id if isinstance(m, ast.Name) else m.arg
        self.pairs.append(((self.orig.identity(o), self.marked.identity(m)), on, mn))

    def _sub(self, pairs: list[tuple[ast.AST, ast.AST]]) -> list[tuple[_Pair, str, str]]:
        saved_pairs, saved_amb = self.pairs, self.ambiguous
        self.pairs, self.ambiguous = [], []
        for o, m in pairs:
            self.pair(o, m)
        out = self.pairs
        self.pairs, self.ambiguous = saved_pairs, saved_amb + self.ambiguous
        return out

    def _swappable(
        self, ol: ast.AST, orr: ast.AST, ml: ast.AST, mr: ast.AST, direct_ok: bool, swap_ok: bool
    ) -> bool:
        direct = direct_ok and _shape(ol) == _shape(ml) and _shape(orr) == _shape(mr)
        swapped = swap_ok and _shape(ol) == _shape(mr) and _shape(orr) == _shape(ml)
        if direct and swapped:
            self.ambiguous.append(
                [self._sub([(ol, ml), (orr, mr)]), self._sub([(ol, mr), (orr, ml)])]
            )
        elif swapped:
            self.pair(ol, mr)
            self.pair(orr, ml)
        elif direct or direct_ok:
            self.pair(ol, ml)
            self.pair(orr, mr)
        else:
            return False
        return True

    def pair(self, o: ast.AST, m: ast.AST) -> None:
        if type(o) is not type(m):
            return
        if isinstance(o, ast.Name):
            self._record(o, m)  # type: ignore[arg-type]
            return
        if isinstance(o, ast.arg):
            self._record(o, m)  # type: ignore[arg-type]
            if o.annotation is not None and m.annotation is not None:  # type: ignore[attr-defined]
                self.pair(o.annotation, m.annotation)  # type: ignore[attr-defined]
            return
        if isinstance(o, ast.Compare) and isinstance(m, ast.Compare):
            if len(o.ops) == len(m.ops) == 1:
                oop, mop = type(o.ops[0]), type(m.ops[0])
                if self._swappable(
                    o.left, o.comparators[0], m.left, m.comparators[0],
                    oop is mop, _MIRROR.get(oop) is mop,
                ):  # fmt: skip
                    return
        if isinstance(o, ast.BinOp) and isinstance(m, ast.BinOp):
            if type(o.op) is type(m.op):
                self._swappable(
                    o.left, o.right, m.left, m.right, True, isinstance(o.op, _COMMUTATIVE)
                )
            return
        for (_, ov), (_, mv) in zip(ast.iter_fields(o), ast.iter_fields(m)):
            if isinstance(ov, ast.AST) and isinstance(mv, ast.AST):
                self.pair(ov, mv)
            elif isinstance(ov, list) and isinstance(mv, list):
                self._pair_lists(ov, mv)

    def _pair_lists(self, ov: list, mv: list) -> None:
        ov = [x for x in ov if isinstance(x, ast.AST)]
        mv = [x for x in mv if isinstance(x, ast.AST)]
        if len(ov) == len(mv):
            for a, b in zip(ov, mv):
                self.pair(a, b)
            return
        # allineamento sulla forma con i nomi mascherati: le istruzioni solo rinominate coincidono,
        # quelle riscritte (es. ``list_comp``: 1 istruzione contro 2) restano non appaiate
        sm = difflib.SequenceMatcher(
            None, [_shape(x) for x in ov], [_shape(x) for x in mv], autojunk=False
        )
        ops = sm.get_opcodes()
        for k, (tag, i1, i2, j1, j2) in enumerate(ops):
            if tag not in ("equal", "replace") or i2 - i1 != j2 - j1:
                continue
            pairs = list(zip(ov[i1:i2], mv[j1:j2]))
            near = [ops[x][0] for x in (k - 1, k + 1) if 0 <= x < len(ops)]
            if tag == "equal" and (i2 - i1 >= 2 or all(n == "equal" for n in near)):
                for a, b in pairs:
                    self.pair(a, b)
            else:
                # accanto a una riscrittura che cambia il numero di istruzioni (es. ``list_comp``)
                # un blocco corto può appaiare istruzioni diverse con la stessa forma
                # (``h = []`` e ``seen = []``): appaiamento incerto
                self.tentative.append(self._sub(pairs))


@dataclass
class RenameCheck:
    """Esito del controllo: ``ok`` se non ci sono violazioni."""

    ok: bool
    violations: list[str] = field(default_factory=list)
    n_pairs: int = 0
    #: appaiamenti ambigui scartati (entrambi gli ordini compatibili con gli appaiamenti certi)
    n_ambiguous_skipped: int = 0
    #: blocchi incerti scartati perché incoerenti con gli appaiamenti certi
    n_tentative_dropped: int = 0
    n_variables_original: int = 0
    n_variables_marked: int = 0
    #: variabili mai appaiate (compaiono solo in sottoalberi riscritti): non controllate
    n_unpaired_original: int = 0
    n_unpaired_marked: int = 0
    error: Optional[str] = None


def _identities(res: _Resolver, tree: ast.AST) -> set[Identity]:
    out: set[Identity] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.arg)) and (
            id(node) in res._where or id(node) in res._args
        ):
            ident = res.identity(node)
            if ident[0] != _FREE:
                out.add(ident)
    return out


def _consistent(
    pairs: list[tuple[_Pair, str, str]],
    fwd: dict[Identity, set[Identity]],
    bwd: dict[Identity, set[Identity]],
) -> bool:
    for (o, m), _, _ in pairs:
        if (o in fwd and fwd[o] != {m}) or (m in bwd and bwd[m] != {o}):
            return False
    return True


def check_renaming(original: str, marked: str) -> RenameCheck:
    """Verifica in sola lettura che la rinomina da ``original`` a ``marked`` sia una biiezione fra
    le variabili dei due codici, scope per scope (vedi la docstring del modulo). Non modifica
    niente; ``ok=False`` con ``error`` se uno dei due codici non si analizza."""
    try:
        oi, mi = AstIndex.from_code(original), AstIndex.from_code(marked)
    except (SyntaxError, ValueError) as exc:
        return RenameCheck(ok=False, error=f"{type(exc).__name__}: {exc}")
    orig, mark = _Resolver(oi), _Resolver(mi)
    pairer = _Pairer(orig, mark)
    pairer.pair(oi.tree, mi.tree)
    fwd: dict[Identity, set[Identity]] = {}
    bwd: dict[Identity, set[Identity]] = {}
    names: dict[_Pair, tuple[str, str]] = {}

    def add(pairs: list[tuple[_Pair, str, str]]) -> None:
        for (o, m), on, mn in pairs:
            fwd.setdefault(o, set()).add(m)
            bwd.setdefault(m, set()).add(o)
            names.setdefault((o, m), (on, mn))

    add(pairer.pairs)
    pending = list(pairer.ambiguous)
    changed = True
    while pending and changed:
        changed = False
        rest = []
        for alternatives in pending:
            good = [alt for alt in alternatives if _consistent(alt, fwd, bwd)]
            if len(good) == 1:
                add(good[0])
                changed = True
            elif not good:
                add(alternatives[0])
                changed = True
            else:
                rest.append(alternatives)
        pending = rest
    dropped = 0
    for group in pairer.tentative:
        if _consistent(group, fwd, bwd):
            add(group)
        else:
            dropped += 1
    violations = []
    for o, ms in sorted(fwd.items()):
        if len(ms) > 1:
            got = ", ".join(sorted(mark.label(m) for m in ms))
            violations.append(f"original {orig.label(o)} -> marked {got}")
    for m, os_ in sorted(bwd.items()):
        if len(os_) > 1:
            got = ", ".join(sorted(orig.label(o) for o in os_))
            violations.append(f"marked {mark.label(m)} <- original {got}")
    for (o, m), (on, mn) in sorted(names.items()):
        if (o[0] == _FREE or m[0] == _FREE) and on != mn:
            violations.append(f"free name changed: {orig.label(o)} -> {mark.label(m)}")
    vo, vm = _identities(orig, oi.tree), _identities(mark, mi.tree)
    return RenameCheck(
        ok=not violations,
        violations=violations,
        n_pairs=len(pairer.pairs),
        n_ambiguous_skipped=len(pending),
        n_tentative_dropped=dropped,
        n_variables_original=len(vo),
        n_variables_marked=len(vm),
        n_unpaired_original=len(vo - set(fwd)),
        n_unpaired_marked=len(vm - set(bwd)),
    )
