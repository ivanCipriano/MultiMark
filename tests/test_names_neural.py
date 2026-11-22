"""Proponente neurale dei nomi (§3.6.4, §P3 punto 1, MD31).

I test non caricano il modello: ``NeuralProposer`` riceve un generatore finto con la stessa
interfaccia di ``HFGenerator``. Il test con il modello vero gira solo se ``MULTIMARK_NEURAL_MODEL``
indica il modello (nome Hugging Face o cartella locale) e c'è l'extra ``[neural]``.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import os
import random
import sys
import textwrap
import types
from collections.abc import Sequence
from pathlib import Path

import pytest

from multimark.config import Config, multimark_base
from multimark.detect import detect
from multimark.embed import default_proposer, embed
from multimark.names import _BUILTINS, StaticProposer
from multimark.names_neural import (
    N_CANDIDATES,
    SYSTEM_PROMPT,
    HFGenerator,
    NeuralProposer,
    build_messages,
    highlighted_source,
    normalize_code,
    parse_names,
    shared_proposer,
)
from multimark.rename_check import check_renaming
from multimark.synthetic import generate

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_functions.jsonl"
TINY = [json.loads(line)["code"] for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
WORDS = ("amount", "acc", "result", "current", "item", "entry", "data", "part", "step", "value",
         "count", "sum", "total", "first", "last", "best", "seen", "tmp", "out",
         "node")  # fmt: skip

B = multimark_base().with_(names_bits_per_name=2, names_proposer="neural")
D = B.with_(
    names_single_letter="extend_except_loop",
    canonical_same_kind="binding_order",
    names_include_params=True,
)


def _var(messages: list[dict[str, str]]) -> str:
    return messages[1]["content"].rsplit("Variable to rename: ", 1)[1].strip()


class FakeGenerator:
    """Risposta deterministica dal prompt: 16 nomi ``<var>_<parola>`` più alcuni non validi
    (riservati, builtin, camelCase, il nome originale, duplicati), come JSON."""

    def __init__(self, n: int = N_CANDIDATES, extra: Sequence[str] = ("class", "len", "fooBar")):
        self.n = n
        self.extra = extra
        self.calls = 0

    def __call__(self, batch: Sequence[list[dict[str, str]]]) -> list[str]:
        out = []
        for messages in batch:
            self.calls += 1
            var = _var(messages)
            seed = int.from_bytes(
                hashlib.sha256(messages[1]["content"].encode()).digest()[:4], "big"
            )
            words = random.Random(seed).sample(WORDS, len(WORDS))[: self.n]
            base = var.lower()
            names = [*self.extra, var, *(f"{base}_{w}" for w in words), f"{base}_{words[0]}"]
            out.append(json.dumps(names))
        return out


class ConstGenerator:
    """Sempre lo stesso testo."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def __call__(self, batch: Sequence[list[dict[str, str]]]) -> list[str]:
        self.calls += len(batch)
        return [self.text for _ in batch]


def _msg(seed: int) -> list[int]:
    return [random.Random(seed).getrandbits(1) for _ in range(24)]


def _sites(code: str, cfg: Config) -> list[tuple[str, str]]:
    from multimark._astindex import AstIndex
    from multimark.layout import build_layout

    layout = build_layout(AstIndex.from_code(code), cfg, 0)
    return [(s.name.unit.name, s.name.name) for s in layout.names if s.name is not None]


# ----------------------------------------------------------------------------- prompt e lettura


def test_prompt_follows_the_spec() -> None:
    code = (
        "def f(items, rate):\n    # nota\n    total = 0\n    for it in items:\n"
        "        total += it * rate\n    return total\n"
    )
    msgs = build_messages(normalize_code(code), "f", "total", N_CANDIDATES)
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT.format(k=16)}
    assert "JSON list of 16 alternative snake_case names" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert user.endswith("\n\nVariable to rename: total")
    assert user.count("<<total>>") == 3 and "nota" not in user  # codice normalizzato
    assert "items" in user and "<<items>>" not in user


def test_highlight_only_the_function_and_parameters() -> None:
    code = "x = 1\n\ndef g(x):\n    return x\n\ndef f(x, y):\n    z = x + y\n    return z\n"
    src = highlighted_source(normalize_code(code), "f", "x")
    assert src.startswith("def f(<<x>>, y):") and "def g" not in src and src.count("<<x>>") == 2
    module = highlighted_source(normalize_code(code), "", "x")
    # variabile di modulo: le funzioni con un loro x locale non si evidenziano
    assert module.count("<<x>>") == 1 and module.startswith("<<x>> = 1") and "def g" in module


def test_highlight_with_non_ascii_text() -> None:
    code = "def f(s):\n    t = 'è' + s\n    return t\n"
    assert "t = 'è' + <<s>>" in highlighted_source(normalize_code(code), "f", "s")


def test_parse_names() -> None:
    assert parse_names('Sure: ["a_b", "c", 3, "d_e"]') == ["a_b", "c", "d_e"]
    # risposta troncata da MAX_NEW_TOKENS: le stringhe complete fra virgolette
    assert parse_names('["total_sum", "acc_value", "run') == ["total_sum", "acc_value"]
    assert parse_names("no list here") == []


def test_candidates_are_valid_on_twenty_fixture_functions() -> None:
    """§P3 punto 1: su 20 funzioni della fixture ``tiny`` i candidati sono identificatori validi,
    diversi dal nome originale, non riservati (e non builtin)."""
    assert len(TINY) == 20
    proposer = NeuralProposer(generate=FakeGenerator())
    checked = 0
    for code in TINY:
        for func, var in _sites(code, D):
            cands = proposer.propose(code, func, var, k=N_CANDIDATES)
            assert cands and len(cands) <= N_CANDIDATES and len(set(cands)) == len(cands)
            for c in cands:
                assert c.isidentifier() and c != var and not keyword.iskeyword(c)
                assert c not in _BUILTINS and c == c.lower()
            checked += 1
    assert checked == 53  # siti dei nomi con le opzioni di D


# ------------------------------------------------------------------------ determinismo e cache


def test_deterministic_and_cached_by_normalized_code() -> None:
    gen = FakeGenerator()
    proposer = NeuralProposer(generate=gen)
    code = "def f(a, b):\n    total = a + b\n    return total\n"
    same = "def f(a, b):   # commento\n\n    total = (a + b)\n    return total\n"
    first = proposer.propose(code, "f", "total", k=16)
    assert proposer.propose(same, "f", "total", k=16) == first
    assert proposer.propose(code, "f", "total", k=4) == first[:4]
    # un lotto per codice: le tre variabili (a, b, total) insieme, poi tutto dalla cache
    assert gen.calls == 3 and proposer.n_generated == 3
    proposer.propose(code, "f", "a", k=16)
    assert gen.calls == 3
    # un proponente nuovo (un altro worker) con lo stesso modello dà gli stessi candidati
    assert NeuralProposer(generate=FakeGenerator()).propose(same, "f", "total", k=16) == first
    # una variabile fuori dall'insieme dei siti si chiede da sola
    proposer.propose(code, "f", "zz", k=16)
    assert gen.calls == 4


def test_embed_is_deterministic() -> None:
    code = generate(5, 30, 2)
    msg = _msg(1)
    a = embed(code, msg, 11, B, proposer=NeuralProposer(generate=FakeGenerator()))
    p = NeuralProposer(generate=FakeGenerator())
    b = embed(code, msg, 11, B, proposer=p)
    calls = p.n_generated
    c = embed(code, msg, 11, B, proposer=p)
    assert a.code == b.code == c.code and a.extra == b.extra == c.extra
    assert p.n_generated == calls  # seconda volta tutto dalla cache


def test_shared_proposer_is_loaded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import multimark.names_neural as nn

    loaded: list[str] = []

    class Loader:
        def __init__(self, model: str) -> None:
            loaded.append(model)

        def __call__(self, batch: Sequence[list[dict[str, str]]]) -> list[str]:
            return FakeGenerator()(batch)

    monkeypatch.setattr(nn, "HFGenerator", Loader)
    shared_proposer.cache_clear()
    try:
        p = default_proposer(B)
        assert isinstance(p, NeuralProposer) and p is default_proposer(D) and loaded == []
        for seed in range(3):
            embed(generate(seed, 20, 2), _msg(seed), seed, B)
        assert loaded == [nn.DEFAULT_MODEL]
    finally:
        shared_proposer.cache_clear()
    assert isinstance(default_proposer(multimark_base()), StaticProposer)


# ------------------------------------------------------------------------------------- ripiego


def test_fallback_to_static_is_counted() -> None:
    code = generate(3, 30, 2)
    msg = _msg(4)
    neural = embed(code, msg, 9, B, proposer=NeuralProposer(generate=ConstGenerator("[]")))
    static = embed(code, msg, 9, B.with_(names_proposer="static"), proposer=StaticProposer())
    # nessun candidato neurale: ogni nome da cambiare passa ai candidati statici
    assert neural.code == static.code
    assert (
        neural.extra["n_names_neural_fallback"]
        == neural.extra["n_renamed"] + (neural.extra["n_names_no_candidate"])
    )
    assert neural.extra["n_renamed"] > 0
    assert {k: v for k, v in neural.extra.items() if k != "n_names_neural_fallback"} == static.extra
    assert "n_names_neural_fallback" not in static.extra


def test_fallback_only_for_names_without_a_good_candidate() -> None:
    """Con un solo candidato neurale per nome, circa 3/4 dei nomi da cambiare (2 bit) ricadono sui
    candidati statici; gli altri usano il nome del modello."""
    gen = FakeGenerator(n=1, extra=())
    fallback = renamed = 0
    for seed in range(6):
        r = embed(generate(seed, 30, 2), _msg(seed), seed, B, proposer=NeuralProposer(generate=gen))
        fallback += r.extra["n_names_neural_fallback"]
        renamed += r.extra["n_renamed"]
    assert 0 < fallback < renamed


def test_wrong_votes_only_when_static_also_fails() -> None:
    for seed in range(4):
        r = embed(generate(seed, 25, 2), _msg(seed), seed, B,
                  proposer=NeuralProposer(generate=FakeGenerator()))  # fmt: skip
        d = detect(r.code, _msg(seed), seed, B, registry_sizes=(1,))
        assert r.extra["n_names_wrong"] <= r.extra["n_names_no_candidate"] * 2
        assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]


# --------------------------------------------- coerenza di inserimento e lettura, check_renaming


@pytest.mark.parametrize("cfg", [B, D], ids=["B", "D"])
def test_embed_read_and_check_renaming(cfg: Config) -> None:
    codes = TINY + [generate(seed, 30, 2) for seed in range(8)]
    renamed = 0
    for i, code in enumerate(codes):
        msg = _msg(i)
        proposer = NeuralProposer(generate=FakeGenerator())
        r = embed(code, msg, 100 + i, cfg, proposer=proposer)
        if r.status == "FAILED":
            assert r.reason == "no_sites"
            continue
        chk = check_renaming(code, r.code)
        assert chk.ok, (i, chk.violations)
        d = detect(r.code, msg, 100 + i, cfg, registry_sizes=(1,))
        assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]
        assert r.extra["n_names_neural_fallback"] >= 0
        renamed += r.extra["n_renamed"]
        # la lettura non usa il modello: stesso esito con il profilo statico
        static_cfg = cfg.with_(names_proposer="static")
        s = detect(r.code, msg, 100 + i, static_cfg, registry_sizes=(1,))
        assert s.extra["agreement"] == d.extra["agreement"]
    assert renamed > 0


def test_neural_names_are_used() -> None:
    code = textwrap.dedent(
        """
        def solve(values, limit):
            total = 0
            best = None
            for value in values:
                if value > limit:
                    total += value
                    best = value
            return total, best
        """
    )
    seen = set()
    for key in range(10):
        r = embed(code, _msg(key), key, B, proposer=NeuralProposer(generate=FakeGenerator()))
        seen |= {w for w in WORDS if f"_{w}" in r.code}
        assert check_renaming(code, r.code).ok
    assert seen


def test_config() -> None:
    assert Config(names_proposer="neural").names_proposer == "neural"
    with pytest.raises(ValueError):
        Config(names_proposer="gpt")
    # il proponente statico resta il default: nessun campo nuovo nella configurazione
    assert multimark_base().names_proposer == "static"


@pytest.mark.skipif(
    not os.environ.get("MULTIMARK_NEURAL_MODEL"), reason="MULTIMARK_NEURAL_MODEL not set"
)
def test_real_model_on_twenty_fixture_functions() -> None:  # pragma: no cover - GPU/modello
    model = os.environ["MULTIMARK_NEURAL_MODEL"]
    proposer = NeuralProposer(model)
    again = NeuralProposer(model, generate=proposer.generator)
    total = 0
    for code in TINY:
        for func, var in _sites(code, D):
            cands = proposer.propose(code, func, var, k=N_CANDIDATES)
            for c in cands:
                assert c.isidentifier() and c != var and not keyword.iskeyword(c)
                assert c not in _BUILTINS
            assert again.propose(code, func, var, k=N_CANDIDATES) == cands  # greedy
            total += 1
    # la qualità (quanti nomi validi restano) si misura a parte, non qui
    assert total == 53


def test_hf_generator_passes_torch_dtype(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from_pretrained`` riceve ``torch_dtype`` (transformers 4.46.3 dell'ambiente posthoc di
    wm-bench: ``dtype`` finisce in ``Qwen2ForCausalLM.__init__`` e dà TypeError)."""
    calls: list[tuple[str, dict[str, object]]] = []

    class Model:
        def to(self, device: str) -> Model:
            return self

        def eval(self) -> Model:
            return self

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(name: str, **kwargs: object) -> Model:
            calls.append((name, kwargs))
            return Model()

    class Tokenizer:
        pad_token = None
        eos_token = "<eos>"
        padding_side = "right"

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(name: str, **kwargs: object) -> Tokenizer:
            return Tokenizer()

    torch = types.ModuleType("torch")
    torch.float32 = "float32-dtype"  # type: ignore[attr-defined]
    torch.bfloat16 = "bfloat16-dtype"  # type: ignore[attr-defined]
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)  # type: ignore[attr-defined]
    transformers = types.ModuleType("transformers")
    transformers.AutoModelForCausalLM = AutoModelForCausalLM  # type: ignore[attr-defined]
    transformers.AutoTokenizer = AutoTokenizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    g = HFGenerator("some/model")
    assert calls == [("some/model", {"torch_dtype": "float32-dtype"})]
    assert g.device == "cpu" and g.tokenizer.padding_side == "left"
    HFGenerator("other", dtype="bfloat16")
    assert calls[-1] == ("other", {"torch_dtype": "bfloat16-dtype"})
