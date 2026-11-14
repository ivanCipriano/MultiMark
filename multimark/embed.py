"""Inserimento (PIPELINE_metodo.md §3.9).

Passi:

1. lettura (``ast``) del codice: siti strutturali, variabili sito, disposizione dei bit
   (``layout.build_layout``); ``N`` = voti potenziali;
2. **nomi**: per ogni variabile, il nome che porta i bit richiesti (V2: il bit di
   ``prf_bit(K, "name", norm(n))``; V1/V1b: lo stile; V2b: candidato con ``cw[phi] == bit``); la
   rinomina si scrive con LibCST (``ScopeProvider``);
3. **siti strutturali**, sul codice già rinominato (con ``canonical="paper"`` la forma canonica
   dipende dai nomi): forma ``cw[phi(s)] XOR mask(s)``, scritta con LibCST;
4. rilettura completa (§3.3.3): un sito strutturale con valore diverso da quello richiesto si
   annulla (resta nella forma originale) e si conta in ``skipped_sites``; una variabile che non
   rilegge il nome scelto si lascia col nome originale. Si riparte dal codice originale con le
   esclusioni, fino a ``MAX_ATTEMPTS`` volte; se la rilettura non torna, ``FAILED`` con motivo
   ``rewrite_mismatch``.

Stati (§3.9): ``OK`` se ``N ≥ B``; ``PARTIAL`` se ``0 < N < B``; ``FAILED`` se ``N = 0``
(``no_sites``), errore di sintassi (``syntax_error``), ``rewrite_mismatch`` o eccezione.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from multimark import __version__
from multimark._astindex import AstIndex
from multimark.channels import CHANNELS
from multimark.codec import encode
from multimark.config import Config
from multimark.layout import Layout, Slot, build_layout, name_value
from multimark.names import (
    BASE_CANDIDATES,
    MAX_CANDIDATES,
    Proposer,
    StaticProposer,
    first_binding_value,
    identifiers_in,
    name_bit,
    name_slot,
    read_style,
    read_style_v1b,
    render_style,
    segments,
    type_suffix,
    valid_new_name,
)
from multimark.rewrite import RewriteError, WriteRequest, rename_variables, write_structural

EMBED_STATUSES = ("OK", "PARTIAL", "FAILED")
MAX_ATTEMPTS = 4


@dataclass
class EmbedResult:
    """Esito dell'inserimento: codice marcato, stato, motivo del fallimento, campi di ``extra``."""

    code: str
    status: str
    reason: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def message_to_bits(message: Union[str, Sequence[int]], n: int) -> list[int]:
    """Messaggio come lista di bit; accetta anche la stringa di ``0``/``1`` del benchmark."""
    bits = [int(c) for c in message] if isinstance(message, str) else [int(b) for b in message]
    if len(bits) != n or any(b not in (0, 1) for b in bits):
        raise ValueError(f"message must be {n} bits of 0/1")
    return bits


def default_proposer(cfg: Config) -> Proposer:
    if cfg.names_proposer == "static":
        return StaticProposer()
    raise NotImplementedError("names.proposer=neural arrives in P3 (names_neural.py)")


@dataclass
class _NameChoice:
    new: Optional[str]  # None = il nome originale porta già i bit richiesti
    reason: str = "ok"  # ok | no_candidate | unwritable


def _choose_name(
    slot: Slot,
    cw: list[int],
    key: int,
    cfg: Config,
    code: str,
    index: AstIndex,
    used: set[str],
    proposer: Proposer,
) -> _NameChoice:
    assert slot.name is not None
    site = slot.name
    name = site.name
    variant = cfg.names_variant
    if variant in ("V2", "V2b"):

        def good(n: str) -> bool:
            bit = name_bit(key, n)
            if variant == "V2":
                return bit == cw[slot.indices[0]]
            return cw[name_slot(key, n, cfg.codeword_length)] == bit

        if good(name):
            return _NameChoice(None)
        func = site.unit.name
        # Prima i primi 8 candidati (§3.6.4); se nessuno ha il bit giusto, fino a 32.
        for k in (BASE_CANDIDATES, MAX_CANDIDATES):
            for cand in proposer.propose(code, func, name, k=k):
                if valid_new_name(cand, name, used) and good(cand):
                    return _NameChoice(cand)
        return _NameChoice(None, "no_candidate")
    # V1 (2 bit di stile) e V1b (snake/camel)
    if variant == "V1":
        want = 2 * cw[slot.indices[0]] + cw[slot.indices[1]]
        reader = read_style
    else:
        want = cw[slot.indices[0]]
        reader = read_style_v1b
    if reader(name) == want:
        return _NameChoice(None)
    segs = segments(name)
    if len(segs) < 2:
        segs = [*segs, type_suffix(first_binding_value(index, site))]
    new = render_style(segs, want)
    if new == name:
        return _NameChoice(None)
    if not valid_new_name(new, name, used, snake=False) or reader(new) != want:
        return _NameChoice(None, "unwritable")
    return _NameChoice(new)


def _structural_keys(layout: Layout) -> list[tuple]:
    return [s.key for s in layout.structural]


def _name_keys(layout: Layout) -> list[tuple]:
    return [s.key for s in layout.names]


def embed(
    code: str,
    message: Union[str, Sequence[int]],
    key: int,
    cfg: Config,
    proposer: Optional[Proposer] = None,
) -> EmbedResult:
    """Marca ``code`` con il messaggio ``message`` (24 bit) e la chiave ``key``."""
    try:
        bits = message_to_bits(message, cfg.message_bits)
        return _embed(code, bits, key, cfg, proposer or default_proposer(cfg))
    except (SyntaxError, ValueError) as exc:
        if isinstance(exc, SyntaxError) or "null bytes" in str(exc):
            return EmbedResult(code, "FAILED", "syntax_error", {"library_version": __version__})
        raise


def _embed(code: str, bits: list[int], key: int, cfg: Config, proposer: Proposer) -> EmbedResult:
    tree = ast.parse(code, type_comments=False)
    index0 = AstIndex(tree)
    layout0 = build_layout(index0, cfg, key)
    cw = encode(bits, cfg.t)
    b = cfg.codeword_length
    n_bits = layout0.n_bits
    by_channel = {c: 0 for c in CHANNELS}
    by_channel["names"] = 0
    for slot in layout0.slots:
        by_channel[slot.channel] += 1
    extra: dict[str, Any] = {
        "n_sites": n_bits,
        "n_structural_sites": len(layout0.structural),
        "n_name_sites": len(layout0.names),
        "n_sites_by_channel": by_channel,
        "codeword_length": b,
        "library_version": __version__,
    }
    if n_bits == 0:
        extra.update(skipped_sites=0, n_renamed=0, n_names_no_candidate=0, n_names_unwritable=0)
        return EmbedResult(code, "FAILED", "no_sites", extra)

    excluded_sites: set[tuple] = set()
    excluded_names: set[tuple] = set()
    for _attempt in range(MAX_ATTEMPTS):
        # 2. nomi
        scope_names = _ScopeNames(index0)
        renames = []
        no_candidate = unwritable_names = 0
        chosen: dict[tuple, str] = {}
        for slot in layout0.names:
            assert slot.name is not None
            original = slot.name.name
            chosen[slot.key] = original
            if slot.key in excluded_names:
                continue
            pool = scope_names.for_slot(slot)
            choice = _choose_name(slot, cw, key, cfg, code, index0, pool, proposer)
            if choice.reason == "no_candidate":
                no_candidate += 1
            elif choice.reason == "unwritable":
                unwritable_names += 1
            if choice.new is not None:
                scope_names.add(slot, choice.new)
                renames.append((slot.name, choice.new))
                chosen[slot.key] = choice.new
        try:
            code1, failed_renames = rename_variables(code, index0, renames)
            for k in failed_renames:
                chosen[k] = next(s.name.name for s in layout0.names if s.key == k and s.name)
            unwritable_names += len(failed_renames)
            index1 = AstIndex.from_code(code1)
            layout1 = build_layout(index1, cfg, key)
            if _structural_keys(layout1) != _structural_keys(layout0):
                raise RewriteError("renaming changed the structural sites")
            # 3. siti strutturali
            requests = []
            planned: dict[tuple, int] = {}
            for slot in layout1.structural:
                assert slot.site is not None
                target = cw[slot.indices[0]] ^ slot.mask
                if slot.key in excluded_sites:
                    target = slot.site.value
                planned[slot.key] = target
                requests.append(WriteRequest(slot.site, target))
            code2, unwritable = write_structural(code1, index1, requests)
            for k in unwritable:
                planned[k] = next(s.site.value for s in layout1.structural if s.key == k and s.site)
            # 4. rilettura completa
            layout2 = build_layout(AstIndex.from_code(code2), cfg, key)
        except (RewriteError, SyntaxError) as exc:
            extra["error"] = str(exc)
            return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)
        bad_sites: set[tuple] = set()
        bad_names: set[tuple] = set()
        keys2 = _structural_keys(layout2)
        if keys2 != _structural_keys(layout0):
            missing = set(_structural_keys(layout0)) - set(keys2)
            if not missing - excluded_sites:
                extra["error"] = "structural sites changed after writing"
                return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)
            bad_sites |= missing
        else:
            for slot in layout2.structural:
                assert slot.site is not None
                if slot.site.value != planned[slot.key]:
                    bad_sites.add(slot.key)
        if _name_keys(layout2) != _name_keys(layout0):
            bad_names |= {k for k, v in chosen.items() if v != _original_name(layout0, k)}
            if not bad_names - excluded_names:
                extra["error"] = "name sites changed after writing"
                return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)
        else:
            for slot in layout2.names:
                assert slot.name is not None
                if slot.name.name != chosen[slot.key]:
                    bad_names.add(slot.key)
        new_bad = (bad_sites - excluded_sites) | (bad_names - excluded_names)
        if not new_bad:
            if bad_sites or bad_names:
                extra["error"] = "rewrite does not read back"
                return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)
            skipped = len(excluded_sites | set(unwritable))
            renamed = sum(1 for slot in layout0.names if slot.name and
                          chosen[slot.key] != slot.name.name)  # fmt: skip
            extra.update(
                skipped_sites=skipped,
                n_renamed=renamed,
                n_names_no_candidate=no_candidate,
                n_names_unwritable=unwritable_names + len(excluded_names),
                n_names_wrong=_wrong_names(layout2, cw, key, cfg),
                n_names_unread=sum(1 for s in layout2.names if name_value(s, key, cfg) is None),
            )
            status = "OK" if n_bits >= b else "PARTIAL"
            return EmbedResult(code2, status, None, extra)
        excluded_sites |= bad_sites
        excluded_names |= bad_names
    extra["error"] = f"rewrite does not read back after {MAX_ATTEMPTS} attempts"
    return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)


def _original_name(layout: Layout, key: tuple) -> str:
    for slot in layout.names:
        if slot.key == key and slot.name is not None:
            return slot.name.name
    raise KeyError(key)


def _wrong_names(layout: Layout, cw: list[int], key: int, cfg: Config) -> int:
    """Voti sbagliati del canale dei nomi (variabili senza candidato o non scrivibili): con V1 una
    variabile porta due voti. Le variabili non leggibili non votano e non si contano qui."""
    wrong = 0
    for slot in layout.names:
        value = name_value(slot, key, cfg)
        if value is None:
            continue
        if cfg.names_variant == "V1":
            wrong += int(value >> 1 != cw[slot.indices[0]]) + int(value & 1 != cw[slot.indices[1]])
        else:
            wrong += int(value != cw[slot.indices[0]])
    return wrong


class _ScopeNames:
    """Nomi in conflitto per una rinomina (§3.6.4 [v1.2.1], MD16; V1, V1b, V2, V2b).

    Per una variabile locale: i nomi legati o letti nella sua funzione (l'unità, con le funzioni
    annidate, che sono i suoi scope racchiudenti diversi dal modulo; i nomi di modulo che la
    funzione legge sono fra questi), i nomi nuovi già scelti nella stessa unità e i nomi nuovi
    delle variabili di modulo che l'unità legge. In più, perché la variabile rinominata resti un
    sito (regole (d)–(e) di §3.6.1), gli attributi, gli argomenti con nome e i nomi in
    ``global``/``nonlocal`` di tutto il modulo. Per una variabile di modulo: tutti gli
    identificatori del modulo e tutti i nomi nuovi già scelti. Due funzioni diverse possono quindi
    ricevere lo stesso nome nuovo."""

    def __init__(self, index: AstIndex) -> None:
        self.all = identifiers_in(index.tree)
        self.by_unit: dict[int, set[str]] = {}
        shared: set[str] = set()
        for node in index.order:
            unit = index.unit_of(node)
            for name in _node_identifiers(node):
                self.by_unit.setdefault(unit.index, set()).add(name)
            if isinstance(node, ast.Attribute):
                shared.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                shared.add(node.arg)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                shared.update(node.names)
        self.shared = shared
        self.chosen_by_unit: dict[int, set[str]] = {}
        self.module_renames: dict[str, str] = {}  # nome originale di modulo -> nome nuovo

    def for_slot(self, slot: Slot) -> set[str]:
        assert slot.name is not None
        unit = slot.name.unit
        if unit.is_module:
            every = set().union(*self.chosen_by_unit.values()) if self.chosen_by_unit else set()
            return self.all | every
        own = self.by_unit.get(unit.index, set())
        read_module = {new for old, new in self.module_renames.items() if old in own}
        return own | self.shared | self.chosen_by_unit.get(unit.index, set()) | read_module

    def add(self, slot: Slot, name: str) -> None:
        assert slot.name is not None
        unit = slot.name.unit
        self.chosen_by_unit.setdefault(unit.index, set()).add(name)
        if unit.is_module:
            self.module_renames[slot.name.name] = name


def _node_identifiers(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.alias):
        return [node.asname or node.name.split(".")[0]]
    return []
