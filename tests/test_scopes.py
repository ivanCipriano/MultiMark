"""Risoluzione degli scope (``multimark/scopes.py``, MD28)."""

from __future__ import annotations

import ast
from typing import Optional

from multimark._astindex import AstIndex
from multimark.scopes import Binding, ScopeResolver


def _bindings(code: str, name: str) -> list[Optional[Binding]]:
    """Binding di tutti i ``Name`` letti chiamati ``name``, in ordine di visita."""
    index = AstIndex.from_code(code)
    resolver = ScopeResolver(index)
    return [
        resolver.binding(n)
        for n in index.order
        if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
    ]


def test_param_and_local() -> None:
    code = "def f(a):\n    b = a\n    return b\n"
    (a,) = _bindings(code, "a")
    (b,) = _bindings(code, "b")
    assert a is not None and b is not None
    assert (a.scope_kind, a.first_how, b.first_how) == ("function", "param", "store")
    assert a.first < b.first and a.scope_position == b.scope_position


def test_first_binding_is_the_earliest() -> None:
    code = "def f(c):\n    if c:\n        x = 1\n    else:\n        x = 2\n    return x\n"
    (x,) = _bindings(code, "x")
    index = AstIndex.from_code(code)
    stores = [
        index.position[id(n)]
        for n in index.order
        if isinstance(n, ast.Name) and n.id == "x" and isinstance(n.ctx, ast.Store)
    ]
    assert x is not None and x.first == min(stores)


def test_closure_reads_enclosing_function() -> None:
    code = "def f(a):\n    def g():\n        return a\n    return g\n"
    (a,) = _bindings(code, "a")
    assert a is not None and a.scope_kind == "function" and a.first_how == "param"


def test_local_anywhere_in_function_is_local() -> None:
    # ``x`` è legato in g dopo la lettura: resta locale di g (regola di Python)
    code = "x = 1\ndef g():\n    y = x\n    x = 2\n    return y\n"
    (x,) = _bindings(code, "x")
    assert x is not None and x.scope_kind == "function"


def test_comprehension_scopes() -> None:
    code = "def f(xs):\n    return [x for x in xs if x], [xs for xs in xs]\n"
    x1, x2 = _bindings(code, "x")
    assert x1 is not None and x1.scope_kind == "comprehension"
    assert x2 is not None and x2.scope_kind == "comprehension"
    # il primo iterabile è dello scope esterno: ``in xs`` è il parametro, l'elemento ``xs`` no
    xs_first, elt, it = _bindings(code, "xs")
    assert xs_first is not None and xs_first.scope_kind == "function"
    assert elt is not None and elt.scope_kind == "comprehension"
    assert it is not None and it.scope_kind == "function" and it.first_how == "param"


def test_walrus_in_comprehension_binds_outside() -> None:
    code = "def f(xs):\n    ys = [(m := x) for x in xs]\n    return m\n"
    (m,) = _bindings(code, "m")
    assert m is not None and (m.scope_kind, m.first_how) == ("function", "walrus")


def test_class_body_not_visible_from_methods() -> None:
    code = "u = 0\nclass C:\n    u = 1\n    v = u\n    def m(self):\n        return u\n"
    in_body, in_method = _bindings(code, "u")
    assert in_body is not None and in_body.scope_kind == "class"
    assert in_method is not None and in_method.scope_kind == "module"


def test_lambda_params_and_defaults() -> None:
    code = "def f(p):\n    return lambda q=p: q\n"
    (p,) = _bindings(code, "p")
    (q,) = _bindings(code, "q")
    assert p is not None and p.scope_kind == "function"
    assert q is not None and (q.scope_kind, q.first_how) == ("lambda", "param")


def test_unresolved_names() -> None:
    code = (
        "import os\n\n\ndef f(a):\n    global g\n    g = a\n    del a\n    return len, os, g, z\n"
        "\n\ndef h():\n    del w\n    return w\n"
    )
    assert _bindings(code, "len") == [None]  # builtin
    assert _bindings(code, "z") == [None]  # non definito
    assert _bindings(code, "g") == [None]  # global
    assert _bindings(code, "w") == [None]  # solo del
    (os,) = _bindings(code, "os")
    assert os is not None and not os.variable  # import: binding non di variabile


def test_identity_distinguishes_scopes() -> None:
    code = "def f(a):\n    def g(a):\n        return a\n    return a, g\n"
    inner, outer = _bindings(code, "a")
    assert inner is not None and outer is not None
    assert inner.identity != outer.identity
