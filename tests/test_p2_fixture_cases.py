"""Casi del criterio (a) di P2 (``tests/fixtures/p2_failures.jsonl``, attacco ``none``, file
CodeNet): tutti i casi ``mcss`` e il ``rewrite_mismatch`` di ``multimark``.

Le chiavi del benchmark non sono nella fixture (le deriva ``MethodAdapter.key``): si usano chiavi
nostre, con il messaggio atteso del caso. Dopo le correzioni MD20–MD25 inserimento e rilevazione
con la stessa chiave e lo stesso messaggio devono dare:

- inserimento riuscito (``OK``/``PARTIAL``), nessun sito saltato, nessun nome non scrivibile;
- gli stessi siti prima e dopo (nessun sito perso o nuovo);
- nessun voto sbagliato e nessun nome illeggibile, quindi una decodifica coerente: mai
  ``inconsistent``, mai un messaggio diverso da quello atteso.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from multimark._astindex import AstIndex
from multimark.config import mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.layout import build_layout

FIXTURE = Path(__file__).parent / "fixtures" / "p2_failures.jsonl"
KEYS = (1000, 1001, 1002, 20261117)


def _cases() -> list[dict]:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["method"] == "mcss" or "embed_rewrite_mismatch" in r["reasons"]]


CASES = _cases()


def test_fixture_selection() -> None:
    methods = [r["method"] for r in CASES]
    assert methods.count("mcss") == 30 and methods.count("multimark") == 1


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[f"{r['method']}-{r['sample_id'].split('/')[1]}-{r['reasons'][0]}" for r in CASES],
)
def test_fixture_case_decodes_consistently(case: dict) -> None:
    cfg = mcss_profile() if case["method"] == "mcss" else multimark_base()
    code = case["original_code"]
    msg = [int(c) for c in case["expected_message"]]
    expected = case["expected_message"]
    for key in KEYS:
        r = embed(code, msg, key, cfg)
        assert r.status in ("OK", "PARTIAL"), (key, r.reason, r.extra.get("error"))
        x = r.extra
        assert x["skipped_sites"] == 0, key
        assert x["n_names_unwritable"] == 0 and x["n_names_unread"] == 0, key
        assert x["n_names_wrong"] == 0, key
        before = build_layout(AstIndex.from_code(code), cfg, key)
        after = build_layout(AstIndex.from_code(r.code), cfg, key)
        assert [s.uid for s in after.slots] == [s.uid for s in before.slots], key
        assert [s.indices for s in after.slots] == [s.indices for s in before.slots], key
        d = detect(r.code, msg, key, cfg, registry_sizes=(1,), method=case["method"])
        assert d.extra["agreement"] == d.extra["n_votes"], key
        assert d.extra["decode_status"] != "inconsistent", key
        assert d.decoded_message in (None, expected), key
        if len({i for s in after.slots for i in s.indices}) == cfg.codeword_length:
            assert d.decoded_message == expected, key
