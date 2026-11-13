"""Variabili di modulo nel canale dei nomi (``names.module_level``, §3.6.1 [v1.2]).

Regole (c)–(g) come nelle funzioni, più (h)–(i)."""

from __future__ import annotations

from multimark._astindex import AstIndex
from multimark.names import name_sites
from multimark.sites import find_sites, loop_form_targets
from tests.helpers import src


def names(code: str, module_level: bool = True) -> list[tuple[str, str]]:
    index = AstIndex.from_code(src(code))
    targets = loop_form_targets(find_sites(index), index)
    return [
        (s.unit.name, s.name)
        for s in name_sites(index, excluded_binding_ids=targets, module_level=module_level)
    ]


def test_off_by_default_and_on_request() -> None:
    code = """
    total = 0
    for item in range(3):
        total += item
    """
    assert names(code, module_level=False) == []
    assert names(code) == [("", "total"), ("", "item")]


def test_module_sites_come_after_functions_and_rank_by_first_binding() -> None:
    code = """
    second = 1
    def f():
        local = 2
        return local
    first = 3
    second = 4
    """
    index = AstIndex.from_code(src(code))
    got = [(s.unit.name, s.name, s.rank) for s in name_sites(index, module_level=True)]
    assert got == [("f", "local", 0), ("", "second", 0), ("", "first", 1)]
    module = [s for s in name_sites(index, module_level=True) if s.unit.is_module]
    assert all(s.key[:2] == ("", 0) for s in module)


def test_binding_kinds_at_module_level() -> None:
    code = """
    import os
    size: int = 3
    with open(os.sep) as handle:
        pass
    if (found := size):
        pass
    first, *rest = [1, 2]
    squares = [elem for elem in rest]
    """
    assert [n for _, n in names(code)] == ["size", "handle", "found", "first", "rest", "squares"]


def test_class_bodies_and_functions_are_not_module_scope() -> None:
    code = """
    class Config:
        timeout = 3
        def method(self):
            inner = 1
            return inner
    def helper():
        value = 2
        return value
    """
    assert names(code) == [("method", "inner"), ("helper", "value")]


def test_rule_h_global_all_def_class_import() -> None:
    code = """
    import json
    from os import path as joined
    __all__ = ["exported", "other"]
    exported = 1
    counter = 0
    json = 2
    joined = 3
    helper = 4
    Widget = 5
    keep = 6
    def helper():
        global counter
        counter += 1
    class Widget:
        pass
    """
    assert names(code) == [("", "keep")]


def test_rule_h_dunder_all_augmented() -> None:
    code = """
    __all__ = ("alpha",)
    __all__ += ["beta"]
    alpha = 1
    beta = 2
    gamma = 3
    """
    assert names(code) == [("", "gamma")]


def test_rules_c_to_g_still_apply() -> None:
    code = """
    x = 1
    _hidden = 2
    attr = 3
    kw = 4
    self = 5
    good = 6
    obj.attr = 7
    call(kw=1)
    """
    assert names(code) == [("", "good")]


def test_rule_i_dynamic_scope_at_module_level() -> None:
    for call in ("locals()", "vars()", "eval('1')", "exec('1')", "globals()"):
        code = f"value = 1\n{call}\n"
        assert names(code) == []


def test_rule_i_dynamic_scope_inside_function_does_not_block_module() -> None:
    code = """
    value = 1
    def f():
        local = 2
        return globals(), local
    """
    # globals() dentro f non è uso «a livello di modulo»; f non ha (f) per globals
    assert names(code) == [("f", "local"), ("", "value")]


def test_list_comp_loop_target_excluded_at_module_level() -> None:
    loop = """
    out = []
    for item in data:
        out.append(item)
    """
    comp = """
    out = [item for item in data]
    """
    assert names(loop) == names(comp) == [("", "out")]


def test_function_rules_unchanged_when_module_level_on() -> None:
    code = """
    def f(param):
        result = param
        return result
    """
    assert names(code) == names(code, module_level=False) == [("f", "result")]
