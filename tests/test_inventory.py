"""Inventario per campione e per dataset, e comando ``multimark.cli.inventory``."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from multimark.channels import CHANNELS
from multimark.cli.inventory import main
from multimark.inventory import count_loc, inventory_code, quantile, summarize
from tests.helpers import src

SAMPLE = src(
    '''
    """Docstring del modulo."""
    import math


    def area(radius):
        """Docstring
        su due righe."""
        # commento
        result = math.pi * radius * radius
        if radius < 0:
            return None
        values = []
        for step in range(3):
            values.append(step + 1)
        return result if result is not None else 0.0
    '''
)


def test_inventory_row() -> None:
    row = inventory_code(SAMPLE)
    assert row["parse_ok"] is True
    assert row["n_functions"] == 1
    assert row["n_sites_compare_dir"] == 1  # radius < 0
    assert row["n_sites_list_comp"] == 1
    assert row["n_sites_operand_order"] == 1  # step + 1
    assert row["n_sites_none_check"] == 1
    assert row["n_sites_ternary"] == 0  # return, non assegnazione
    assert row["n_vars"] == 2  # result, values (step è bersaglio di list_comp)
    assert row["n_sites_structural"] == sum(row[f"n_sites_{c}"] for c in CHANNELS)
    assert row["n_sites_total"] == row["n_sites_structural"] + row["n_vars"]
    assert row["n_bits_v1"] == row["n_sites_structural"] + 2 * row["n_vars"]
    assert row["n_duplicate_fids"] == 0
    # righe di codice: import, def, result, if, return None, values, for, append, return
    assert row["loc"] == 9


def test_inventory_options() -> None:
    code = "def f(alpha, beta):\n    gamma = len(alpha) < len(beta)\n    return alpha < beta\n"
    assert inventory_code(code)["n_sites_compare_dir"] == 0
    assert inventory_code(code, canonical="paper")["n_sites_compare_dir"] == 1
    assert inventory_code(code, canonical="paper", guards=False)["n_sites_compare_dir"] == 2
    assert inventory_code(code)["n_vars"] == 1
    assert inventory_code(code, include_params=True)["n_vars"] == 3


def test_inventory_duplicate_fids() -> None:
    code = src(
        """
        class A:
            def run(self):
                pass
        class B:
            def run(self):
                pass
            def go(self):
                pass
        class C:
            def go(self):
                pass
        def run(x):
            pass
        """
    )
    row = inventory_code(code)
    assert row["n_functions"] == 5 and row["n_duplicate_fids"] == 2


def test_inventory_syntax_error() -> None:
    row = inventory_code("def f(:\n")
    assert row["parse_ok"] is False and row["error"].startswith("SyntaxError")


def test_count_loc() -> None:
    code = 'x = """a\nb\nc"""\n\n# solo commento\ny = 1  # coda\n'
    assert count_loc(code) == 4
    assert count_loc('def f():\n    """doc"""\n    return 1\n') == 2


def test_quantile_linear() -> None:
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([1, 2, 3, 4], 0.25) == 1.75
    assert quantile([7], 0.75) == 7
    assert math.isnan(quantile([], 0.5))


def test_summarize() -> None:
    rows = [
        {"parse_ok": False, "error": "SyntaxError"},
        *[inventory_code("def f(a):\n    return a < 1\n") for _ in range(3)],
        inventory_code("def f(a):\n" + "".join(f"    v{i} = a + {i}\n" for i in range(20))),
    ]
    s = summarize(rows)
    assert s["n_samples"] == 5 and s["n_parsed"] == 4 and s["n_parse_errors"] == 1
    # ultimo campione: 20 siti operand_order (a + 0 compreso) + 20 variabili
    assert rows[-1]["n_sites_operand_order"] == 20
    assert rows[-1]["n_sites_total"] == 40
    assert s["frac_total_ge_32"] == 0.25
    assert s["frac_total_ge_20"] == 0.25
    assert s["frac_total_ge_13"] == 0.25
    assert s["most_frequent_structural_channel"] == "operand_order"
    assert s["sites_by_channel"]["compare_dir"] == 3
    assert s["stats"]["n_sites_total"]["median"] == 1.0
    assert s["stats"]["n_bits_v1"]["mean"] == (3 * 1 + 60) / 4
    assert s["frac_with_duplicate_fids"] == 0.0


def test_summarize_empty() -> None:
    s = summarize([])
    assert s["n_samples"] == 0 and math.isnan(s["frac_total_ge_32"])
    assert s["most_frequent_channel"] is None


@pytest.mark.parametrize("ext", [".csv", ".jsonl"])
def test_cli(tmp_path: Path, ext: str) -> None:
    inp = tmp_path / "in.jsonl"
    records = [
        {"sample_id": "a", "code": "def f(a):\n    return a < 1\n"},
        {"sample_id": "b", "code": "def f(:\n"},
    ]
    inp.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    out = tmp_path / f"rows{ext}"
    summary = tmp_path / "summary.txt"
    summary_json = tmp_path / "summary.json"
    rc = main(
        [
            "--input", str(inp), "--output", str(out), "--summary", str(summary),
            "--summary-json", str(summary_json), "--id-field", "sample_id", "--label", "test",
        ]
    )  # fmt: skip
    assert rc == 0
    if ext == ".csv":
        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["sample_id"] == "a" and rows[0]["n_sites_compare_dir"] == "1"
    else:
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["n_sites_compare_dir"] == 1 and rows[1]["parse_ok"] is False
    text = summary.read_text(encoding="utf-8")
    assert "Inventory test" in text and "frac n_sites_total >= 32" in text
    assert "frac with duplicate fids" in text and "n_bits_v1" in text
    data = json.loads(summary_json.read_text(encoding="utf-8"))
    assert data["n_parse_errors"] == 1 and data["options"]["guards"] is True


def test_cli_missing_field(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    inp.write_text('{"other": 1}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--input", str(inp)])
