"""Quali variabili sono siti del canale dei nomi (§3.6.1)."""

from __future__ import annotations

from multimark._astindex import AstIndex
from multimark.names import name_sites
from multimark.sites import find_sites, loop_form_targets
from tests.helpers import src


def names(code: str, include_params: bool = False) -> list[str]:
    index = AstIndex.from_code(src(code))
    targets = loop_form_targets(find_sites(index), index)
    return [
        s.name
        for s in name_sites(index, include_params=include_params, excluded_binding_ids=targets)
    ]


def test_binding_kinds() -> None:
    code = """
    def f(path):
        total = 0
        count += 1
        size: int = 3
        for item in path:
            pass
        with open(path) as handle:
            pass
        if (found := path):
            pass
        first, *rest = path
        return [elem for elem in path]
    """
    assert names(code) == ["total", "count", "size", "item", "handle", "found", "first", "rest"]


def test_params_excluded_by_default_and_included_on_request() -> None:
    code = """
    def f(alpha, beta=1, *args, gamma, **kwargs):
        alpha = 2
        delta = 3
    """
    assert names(code) == ["delta"]
    assert names(code, include_params=True) == ["alpha", "beta", "args", "gamma", "kwargs", "delta"]


def test_rank_follows_first_binding() -> None:
    code = """
    def f():
        bb = 1
        aa = 2
        bb = 3
    """
    index = AstIndex.from_code(src(code))
    got = [(s.name, s.rank) for s in name_sites(index)]
    assert got == [("bb", 0), ("aa", 1)]


def test_excluded_names() -> None:
    code = """
    import os
    def f(self):
        x = 1
        _hidden = 2
        __dunder = 3
        cls = 4
        self = 5
        kw = 6
        attr = 7
        glob = 8
        g(kw=1)
        os.attr
        mod = 9
        import mod
        def helper():
            pass
        helper = 1
        try:
            pass
        except E as err:
            err = 1
        keep = 10
    def h():
        global glob
    """
    assert names(code) == ["keep"]


def test_dynamic_scope_functions_have_no_name_sites() -> None:
    for call in ("locals()", "vars()", "eval('1')", "exec('1')"):
        code = f"def f():\n    value = 1\n    {call}\n"
        assert names(code) == []
    assert names("def f():\n    value = 1\ndef g():\n    eval('1')\n") == ["value"]


def test_module_level_has_no_name_sites() -> None:
    assert names("value = 1\nclass K:\n    other = 2\n") == []


def test_nested_function_belongs_to_outer() -> None:
    code = """
    def outer():
        first = 1
        def inner():
            second = 2
        return inner
    """
    index = AstIndex.from_code(src(code))
    got = [(s.unit.name, s.name) for s in name_sites(index)]
    assert got == [("outer", "first"), ("outer", "second")]


def test_list_comp_loop_target_is_not_a_binding() -> None:
    loop = """
    def f(items):
        out = []
        for item in items:
            out.append(item)
        return out
    """
    comp = """
    def f(items):
        out = [item for item in items]
        return out
    """
    assert names(loop) == names(comp) == ["out"]


def test_ordinary_loop_target_is_a_binding() -> None:
    code = """
    def f(items):
        for item in items:
            print(item)
    """
    assert names(code) == ["item"]
