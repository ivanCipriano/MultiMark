"""Inserimento (PIPELINE_metodo.md §3.9).

Passi:

1. lettura (``ast``) del codice: siti strutturali, variabili sito, disposizione dei bit
   (``layout.build_layout``); ``N`` = voti potenziali;
2. **nomi**: per ogni variabile, il nome che porta i bit richiesti (V2: il bit di
   ``prf_bit(K, "name", norm(n))``, o i 2 bit di ``names.name_bits`` con
   ``names.bits_per_name = 2``, MD27; V1/V1b: lo stile; V2b: candidato con ``cw[phi] == bit``); la
   rinomina si scrive con LibCST (``ScopeProvider``). Con ``names.suffix_by_type = on`` (MD30)
   i candidati si filtrano con il tipo dedotto (``names.filter_by_type``); se nessuno ha i bit
   giusti si usa l'elenco completo senza ``the_``, contato in ``n_names_type_fallback``;
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
    RETRY_SUFFIXES,
    Proposer,
    StaticProposer,
    deduce_type,
    filter_by_type,
    first_binding_value,
    identifiers_in,
    name_bit,
    name_bits,
    name_slot,
    read_style,
    read_style_v1b,
    render_style,
    segments,
    style_forms_ok,
    styles_of_variant,
    type_suffix,
    valid_new_name,
    without_excluded_prefix,
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
    #: MD30 regola (a): nessun candidato filtrato per tipo andava bene, scelto dall'elenco completo
    type_fallback: bool = False


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
            if variant == "V2":
                # 1 o 2 posizioni (names.bits_per_name, MD27): il candidato è valido se tutti i
                # bit del nome coincidono con la parola di codice
                want = 0
                for i in slot.indices:
                    want = 2 * want + cw[i]
                return name_bits(key, n, len(slot.indices)) == want
            return cw[name_slot(key, n, cfg.codeword_length)] == name_bit(key, n)

        if good(name):
            return _NameChoice(None)
        func = site.unit.name
        # Anche i nomi di una lettera (names.single_letter) seguono questa regola.
        # Prima i primi 8 candidati (§3.6.4); se nessuno ha il bit giusto, fino a 32.
        by_type = cfg.names_suffix_by_type == "on"
        typ = deduce_type(index, site) if by_type else None
        for k in (BASE_CANDIDATES, MAX_CANDIDATES):
            cands = proposer.propose(code, func, name, k=k)
            if by_type:
                # MD30: suffissi coerenti con il tipo dedotto, senza il prefisso ``the_``
                cands = filter_by_type(cands, name, typ)
            for cand in cands:
                if valid_new_name(cand, name, used) and good(cand):
                    return _NameChoice(cand)
        if by_type:
            # MD30 regola (a): elenco completo di oggi (senza ``the_``, regola (b)); la lettura
            # non cambia, perché prende il bit dal nome
            for cand in without_excluded_prefix(
                proposer.propose(code, func, name, k=MAX_CANDIDATES)
            ):
                if valid_new_name(cand, name, used) and good(cand):
                    return _NameChoice(cand, type_fallback=True)
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
    styles = styles_of_variant(variant)
    segs = segments(name)
    first = segs if len(segs) >= 2 else [*segs, type_suffix(first_binding_value(index, site))]
    # MD20: se la resa richiesta non si può usare per il contesto (conflitto con un nome,
    # riservata, builtin), si provano i suffissi successivi prima di rinunciare.
    last = segs[-1].lower() if segs else ""
    tries = [first] + [
        [*segs, sfx] for sfx in RETRY_SUFFIXES if sfx != last and [*segs, sfx] != first
    ]
    for parts in tries:
        new = render_style(parts, want)
        if new == name:
            return _NameChoice(None)
        if (
            valid_new_name(new, name, used, snake=False)
            and reader(new) == want
            and style_forms_ok(parts, styles)
        ):
            return _NameChoice(new)
    return _NameChoice(None, "unwritable")


def _structural_keys(layout: Layout) -> list[tuple]:
    return [s.uid for s in layout.structural]


def _name_keys(layout: Layout) -> list[tuple]:
    return [s.uid for s in layout.names]


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
    cw = encode(bits, cfg.t, cfg.code_matrix)
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
        if cfg.names_suffix_by_type == "on":
            extra["n_names_type_fallback"] = 0
        return EmbedResult(code, "FAILED", "no_sites", extra)

    excluded_sites: set[tuple] = set()
    excluded_names: set[tuple] = set()
    for _attempt in range(MAX_ATTEMPTS):
        # 2. nomi
        scope_names = _ScopeNames(index0)
        renames = []
        no_candidate = unwritable_names = type_fallback = 0
        chosen: dict[tuple, str] = {}
        for slot in layout0.names:
            assert slot.name is not None
            original = slot.name.name
            chosen[slot.uid] = original
            if slot.uid in excluded_names:
                continue
            pool = scope_names.for_slot(slot)
            choice = _choose_name(slot, cw, key, cfg, code, index0, pool, proposer)
            if choice.reason == "no_candidate":
                no_candidate += 1
            if choice.type_fallback:
                type_fallback += 1
            elif choice.reason == "unwritable":
                unwritable_names += 1
            if choice.new is not None:
                scope_names.add(slot, choice.new)
                renames.append((slot.name, choice.new))
                chosen[slot.uid] = choice.new
        try:
            code1, failed_renames = rename_variables(code, index0, renames)
            for k in failed_renames:
                chosen[k] = next(s.name.name for s in layout0.names if s.uid == k and s.name)
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
                if slot.uid in excluded_sites:
                    target = slot.site.value
                planned[slot.uid] = target
                requests.append(WriteRequest(slot.site, target))
            code2, unwritable = write_structural(code1, index1, requests)
            for k in unwritable:
                planned[k] = next(s.site.value for s in layout1.structural if s.uid == k and s.site)
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
                if slot.site.value != planned[slot.uid]:
                    bad_sites.add(slot.uid)
        if _name_keys(layout2) != _name_keys(layout0):
            bad_names |= {k for k, v in chosen.items() if v != _original_name(layout0, k)}
            if not bad_names - excluded_names:
                extra["error"] = "name sites changed after writing"
                return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)
        else:
            for slot in layout2.names:
                assert slot.name is not None
                if slot.name.name != chosen[slot.uid]:
                    bad_names.add(slot.uid)
        new_bad = (bad_sites - excluded_sites) | (bad_names - excluded_names)
        if not new_bad:
            if bad_sites or bad_names:
                extra["error"] = "rewrite does not read back"
                return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)
            skipped = len(excluded_sites | set(unwritable))
            renamed = sum(1 for slot in layout0.names if slot.name and
                          chosen[slot.uid] != slot.name.name)  # fmt: skip
            extra.update(
                skipped_sites=skipped,
                n_renamed=renamed,
                n_names_no_candidate=no_candidate,
                n_names_unwritable=unwritable_names + len(excluded_names),
                n_names_wrong=_wrong_names(layout2, cw, key, cfg),
                n_names_unread=sum(1 for s in layout2.names if name_value(s, key, cfg) is None),
            )
            if cfg.names_suffix_by_type == "on":
                # MD30 regola (a): nomi scelti dall'elenco completo perché nessun candidato
                # filtrato per tipo aveva i bit giusti (solo con l'opzione attiva: con ``off`` il
                # registro resta quello di prima)
                extra["n_names_type_fallback"] = type_fallback
            status = "OK" if n_bits >= b else "PARTIAL"
            return EmbedResult(code2, status, None, extra)
        excluded_sites |= bad_sites
        excluded_names |= bad_names
    extra["error"] = f"rewrite does not read back after {MAX_ATTEMPTS} attempts"
    return EmbedResult(code, "FAILED", "rewrite_mismatch", extra)


def _original_name(layout: Layout, key: tuple) -> str:
    for slot in layout.names:
        if slot.uid == key and slot.name is not None:
            return slot.name.name
    raise KeyError(key)


def _wrong_names(layout: Layout, cw: list[int], key: int, cfg: Config) -> int:
    """Voti sbagliati del canale dei nomi (variabili senza candidato o non scrivibili): con V1 e
    con V2 a 2 bit per nome una variabile porta due voti. Le variabili non leggibili non votano e
    non si contano qui."""
    wrong = 0
    for slot in layout.names:
        value = name_value(slot, key, cfg)
        if value is None:
            continue
        if len(slot.indices) == 2:
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
    identificatori del modulo, i nomi nuovi già scelti per il modulo e quelli scelti nelle unità
    che **leggono** la variabile (nome presente nell'unità e non legato lì: MD20; prima si
    contavano i nomi scelti in tutte le unità, e un nome di una lettera di modulo trovava già preso
    ``a_val`` da un parametro omonimo di una funzione che non lo legge). Due funzioni diverse
    possono quindi ricevere lo stesso nome nuovo."""

    def __init__(self, index: AstIndex) -> None:
        self.all = identifiers_in(index.tree)
        self.by_unit: dict[int, set[str]] = {}
        self.bound_by_unit: dict[int, set[str]] = {}
        shared: set[str] = set()
        for node in index.order:
            unit = index.unit_of(node)
            for name in _node_identifiers(node):
                self.by_unit.setdefault(unit.index, set()).add(name)
            if _binds(node):
                self.bound_by_unit.setdefault(unit.index, set()).update(_node_identifiers(node))
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
            readers = {
                i for i in self.chosen_by_unit if i == unit.index or slot.name.name in self._free(i)
            }
            chosen = set().union(*(self.chosen_by_unit[i] for i in readers)) if readers else set()
            return self.all | chosen
        own = self.by_unit.get(unit.index, set())
        free = self._free(unit.index)
        read_module = {new for old, new in self.module_renames.items() if old in free}
        return own | self.shared | self.chosen_by_unit.get(unit.index, set()) | read_module

    def _free(self, unit_index: int) -> set[str]:
        """Nomi presenti nell'unità e non legati lì (letti da uno scope esterno)."""
        own = self.by_unit.get(unit_index, set())
        return own - self.bound_by_unit.get(unit_index, set())

    def add(self, slot: Slot, name: str) -> None:
        assert slot.name is not None
        unit = slot.name.unit
        self.chosen_by_unit.setdefault(unit.index, set()).add(name)
        if unit.is_module:
            self.module_renames[slot.name.name] = name


def _binds(node: ast.AST) -> bool:
    """``node`` lega il suo identificatore nello scope dell'unità."""
    if isinstance(node, ast.Name):
        return not isinstance(node.ctx, ast.Load)
    return isinstance(
        node, (ast.arg, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.alias)
    )


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
