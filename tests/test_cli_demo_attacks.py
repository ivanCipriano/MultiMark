"""Attacchi dimostrativi (``multimark/cli/demo_attacks.py``, P7.d): per ogni attacco,
determinismo con lo stesso seme, codice Python valido, modifica sul codice di esempio,
comportamento conservato dove l'attacco lo promette; ri-marcatura senza chiavi nei risultati.

Nessuna chiave è scritta qui: ogni test ne genera una a caso."""

from __future__ import annotations

import ast
import dataclasses
import re
import secrets
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from multimark.cli import demo
from multimark.cli import demo_attacks as da

EXAMPLE = '''"""Esempio per gli attacchi."""
import math

MAX_VALUE = 10


def scaleValues(itemList, factor):
    # moltiplica ogni elemento
    resultList = []
    for i in range(len(itemList)):
        value = itemList[i] * factor
        if value > MAX_VALUE:
            resultList.append(MAX_VALUE)
        else:
            resultList.append(value)
    total = 0
    total += 2
    return resultList


def countPositive(numbers):
    count = 0
    for n in numbers:
        if 0 < n:
            count = count + 1
    return count
'''
TOOLS = ["T1.1", "T1.2", "T4.1"]  # strumenti dell'extra demo (black, ruff, python-minifier)


def _ids(ids: list[str]) -> list[Any]:
    """Gli attacchi con uno strumento esterno si saltano se l'extra ``demo`` manca."""
    return [pytest.param(a, marks=pytest.mark.skipif(da.unavailable(a) is not None,
                                                     reason=da.DEMO_EXTRA_HINT))
            for a in ids]  # fmt: skip


DETERMINISTIC = _ids([a for a in da.ATTACKS if a != da.REMARK_ID])
# Attacchi che non cambiano il comportamento delle funzioni (T2.4 e T2.4k tolgono codice).
SAME_BEHAVIOUR = _ids(["T1.1", "T1.2", "T1.3", "T1.4", "T1.5", "T1.6", "T2.1", "T2.5", "T4.1"])
needs_tools = pytest.mark.skipif(any(da.unavailable(a) for a in TOOLS), reason=da.DEMO_EXTRA_HINT)


def _functions(code: str) -> dict[str, Callable[..., Any]]:
    env: dict[str, Any] = {}
    exec(compile(code, "<attacked>", "exec"), env)  # noqa: S102 - codice di esempio del test
    return env


def _all_param_sets(attack_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for p in da.ATTACKS[attack_id].params:
        out = [{**o, p.name: c} for o in out for c in (p.choices or (p.default,))]
    return out


# ---------------------------------------------------------------------------- ogni attacco
@pytest.mark.parametrize("attack_id", DETERMINISTIC)
def test_default_attack_changes_the_example_and_stays_python(attack_id: str) -> None:
    r = da.apply_attack(attack_id, EXAMPLE, {})
    assert r.status == da.APPLIED, r.detail
    assert r.code != EXAMPLE and r.parses
    assert r.seed == da.DEMO_SEED


@pytest.mark.parametrize("attack_id", DETERMINISTIC)
def test_every_parameter_is_deterministic_and_valid(attack_id: str) -> None:
    for params in _all_param_sets(attack_id):
        a = da.apply_attack(attack_id, EXAMPLE, params)
        b = da.apply_attack(attack_id, EXAMPLE, params)
        assert a == b, params
        assert a.parses, (params, a.detail)
        assert a.status in (da.APPLIED, da.UNCHANGED), (params, a.detail)


@pytest.mark.parametrize("attack_id", SAME_BEHAVIOUR)
def test_behaviour_is_preserved(attack_id: str, capsys: pytest.CaptureFixture[str]) -> None:
    before = _functions(EXAMPLE)
    for params in _all_param_sets(attack_id):
        after = _functions(da.apply_attack(attack_id, EXAMPLE, params).code)
        for data in ([], [1, 5, 12], [3, -2, 0, 7]):
            assert after["scaleValues"](data, 2) == before["scaleValues"](data, 2), params
            assert after["countPositive"](data) == before["countPositive"](data), params
    assert capsys.readouterr().out == ""  # T1.5 scrive solo su stderr


def test_attacks_can_be_chained() -> None:
    code = EXAMPLE
    for attack_id in ("T1.6", "T2.1", "T1.5", "T2.5", "T1.3"):
        r = da.apply_attack(attack_id, code, {})
        assert r.parses
        code = r.code
    assert code != EXAMPLE
    assert _functions(code)["countPositive"]([1, -1, 2]) == 2


def test_invalid_code_is_a_tool_error_or_not_applicable() -> None:
    bad = "def f(:\n    return 1\n"
    for attack_id in da.ATTACKS:
        if attack_id == da.REMARK_ID:
            continue
        r = da.apply_attack(attack_id, bad, {})
        # ruff --fix lascia com'è un file con errori di sintassi (uscita 1), come nel benchmark
        allowed = (da.UNCHANGED,) if attack_id == "T1.2" else (da.TOOL_ERROR, da.NOT_APPLICABLE)
        if da.unavailable(attack_id):
            allowed = (da.NOT_APPLICABLE,)
        assert r.status in allowed, attack_id
        assert r.code == bad


# ---------------------------------------------------------------------------- casi particolari
def test_t1_3_removes_comments_and_keeps_docstrings() -> None:
    r = da.apply_attack("T1.3", EXAMPLE, {})
    assert "#" not in r.code and '"""Esempio per gli attacchi."""' in r.code
    assert r.detail["n_removed"] == 1


def test_t1_4_changes_with_the_seed() -> None:
    a = da.apply_attack("T1.4", EXAMPLE, {"ratio": 1.0}, seed=1)
    b = da.apply_attack("T1.4", EXAMPLE, {"ratio": 1.0}, seed=2)
    assert a.code != b.code and a.detail["n_renamed"] == a.detail["n_candidates"]


def test_t1_6_snake_case_and_caps() -> None:
    convert = da.apply_attack("T1.6", EXAMPLE, {"caps": "convert"}).code
    keep = da.apply_attack("T1.6", EXAMPLE, {"caps": "keep"}).code
    assert "item_list" in convert and "result_list" in convert and "itemList" not in convert
    assert "max_value = 10" in convert and "MAX_VALUE = 10" in keep
    assert "def scaleValues" in convert  # i nomi delle funzioni non sono candidati


def test_t2_1_catalog() -> None:
    r = da.apply_attack("T2.1", EXAMPLE, {"b": "all"})
    assert set(r.detail["applied"]) >= {"for_to_while", "if_else_inversion", "comparison_flip"}
    # for_to_while, poi comparison_flip anche sul confronto appena creato e sulle condizioni
    assert re.search(r"\n    i = 0\n    \w+ = len\(itemList\)\n    while \w+ > i:", r.code)
    assert "if not (MAX_VALUE < value)" in r.code and "i = i + (1)" in r.code
    assert "n > 0" in r.code
    one = da.apply_attack("T2.1", EXAMPLE, {"b": 1})
    assert len(one.detail["chosen"]) == 1


def test_t2_4_targets() -> None:
    r = da.apply_attack("T2.4", EXAMPLE, {"p": 0.5})
    assert r.detail["function"] == "scaleValues" and r.detail["kept"] == 2
    other = da.apply_attack("T2.4", EXAMPLE, {"p": 0.5, "target": "countPositive"})
    assert other.detail["function"] == "countPositive"
    missing = da.apply_attack("T2.4", EXAMPLE, {"target": "nope"})
    assert missing.status == da.NOT_APPLICABLE and missing.code == EXAMPLE


def test_t2_4k_needs_two_functions() -> None:
    r = da.apply_attack("T2.4k", EXAMPLE, {"k": 1})
    assert len(r.detail["kept"]) == 1 and r.detail["removed"] == 1
    single = da.apply_attack("T2.4k", "def f():\n    return 1\n", {"k": 1})
    assert single.status == da.NOT_APPLICABLE


def test_t2_5_adds_pool_functions_after_the_imports() -> None:
    r = da.apply_attack("T2.5", EXAMPLE, {"n": 4, "position": "before"})
    tree = ast.parse(r.code)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert names[:4] == sorted(names[:4], key=r.detail["names"].index)
    assert isinstance(tree.body[1], ast.Import)  # dopo docstring e import
    assert len(names) == 6


def test_demo_attacks_imports_nothing_from_the_benchmark() -> None:
    tree = ast.parse(open(da.__file__, encoding="utf-8").read())
    modules = {
        ((n.module or "") if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    }
    assert "bench" not in modules
    assert modules <= {"__future__", "ast", "builtins", "importlib", "io", "keyword", "math",
                       "random", "re", "string", "subprocess", "sys", "tempfile", "tokenize",
                       "warnings", "collections", "dataclasses", "pathlib", "typing", "libcst",
                       "multimark", "black", "python_minifier"}  # fmt: skip


def test_tools_are_used_only_in_demo_attacks() -> None:
    """black, ruff e python-minifier (extra ``demo``) si importano o si lanciano solo in
    ``demo_attacks.py``. Eccezione già esistente: l'autovalidazione di P1 (``cli/selftest.py``)
    usa black e ruff se ci sono (extra ``dev``), per le prove di invarianza alla formattazione."""
    root = Path(da.__file__).parents[1]
    allowed = {Path(da.__file__).resolve(), (root / "cli" / "selftest.py").resolve()}
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                 for a in n.names}  # fmt: skip
        names |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom)}  # fmt: skip
        if path.resolve() not in allowed:
            assert not names & {"black", "ruff", "python_minifier"}, path
            assert '"ruff"' not in text, path


def test_demo_extra_pins_the_benchmark_versions() -> None:
    text = (Path(da.__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    demo_line = next(line for line in text.splitlines() if line.startswith("demo = ["))
    for tool, version in da.TOOL_PINS.items():
        assert f'"{tool}=={version}"' in demo_line
    assert da.TOOL_PINS == {"black": "24.10.0", "ruff": "0.7.4", "python-minifier": "2.11.3"}


def test_note_lists_the_excluded_attacks() -> None:
    for word in ("T2.2", "T2.3", "T4.2", "benchmark"):
        assert word in da.ATTACK_NOTE
    for word in TOOLS:  # ora disponibili con l'extra demo
        assert word not in da.ATTACK_NOTE


# ---------------------------------------------------------------------------- strumenti esterni
def test_missing_tool_disables_the_attack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da, "_have_module", lambda module: False)
    for attack_id in TOOLS:
        assert (
            da.unavailable(attack_id)
            == da.DEMO_EXTRA_HINT
            == "richiede pip install multimark[demo]"
        )
        r = da.apply_attack(attack_id, EXAMPLE, {})
        assert r.status == da.NOT_APPLICABLE and r.code == EXAMPLE
    assert da.unavailable("T1.3") is None


@needs_tools
def test_tool_attacks_record_the_versions() -> None:
    for attack_id in TOOLS:
        r = da.apply_attack(attack_id, EXAMPLE, {})
        assert r.detail["pinned"] == da.TOOL_PINS[r.detail["tool"]]
        assert r.detail["version"] == da.tool_version(r.detail["tool"])


@needs_tools
def test_t1_1_black_formats() -> None:
    r = da.apply_attack("T1.1", EXAMPLE, {})
    assert '"""Esempio per gli attacchi."""\n\nimport math\n' in r.code
    assert da.apply_attack("T1.1", r.code, {}).status == da.UNCHANGED  # già formattato
    assert da.apply_attack("T1.1", "  \n", {}).detail.get("empty")


@needs_tools
def test_t1_2_ruff_removes_the_unused_import() -> None:
    r = da.apply_attack("T1.2", EXAMPLE, {})
    assert "import math" not in r.code and "MAX_VALUE = 10" in r.code
    assert r.code.replace("import math\n", "") == EXAMPLE.replace("import math\n", "")
    assert sys.executable  # ruff gira con l'interprete corrente


@needs_tools
def test_t4_1_rename() -> None:
    plain = da.apply_attack("T4.1", EXAMPLE, {"rename": False}).code
    renamed = da.apply_attack("T4.1", EXAMPLE, {"rename": True}).code
    assert "resultList" in plain and "resultList" not in renamed
    for code in (plain, renamed):  # i nomi globali e i parametri restano
        assert "def scaleValues(itemList,factor)" in code and "MAX_VALUE" in code


# ---------------------------------------------------------------------------- ri-marcatura
def test_remark_uses_the_second_key_and_hides_both() -> None:
    key1, key2 = secrets.randbits(64), secrets.randbits(64)
    first = format(0xABCDEF, "024b")
    second = format(0x123456, "024b")
    marked = demo.mark_code(EXAMPLE, first, key1, "multimark_prudent")
    assert marked.code is not None
    r = da.remark(marked.code, second, key2, "multimark_prudent")
    assert r.attack_id == "T3.1" and r.status == da.APPLIED and r.parses
    v2 = demo.verify_code(r.code, key2, "multimark_prudent", demo.MODELS[0], second)
    assert v2.detected
    text = repr(dataclasses.asdict(r))
    for key in (key1, key2):
        for form in (str(key), hex(key), f"{key:x}", f"{key:016x}"):
            assert form not in text


def test_remark_without_sites_is_unchanged() -> None:
    r = da.remark("import os\n", "0" * 24, secrets.randbits(64), "mcss_main")
    assert r.status == da.UNCHANGED and r.code == "import os\n"
