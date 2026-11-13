"""Disposizione dei voti: per ogni sito, le posizioni della parola di codice che legge e la
maschera (PIPELINE_metodo.md §3.4–3.6, §4.1). È la stessa in inserimento e rilevazione, perché
dipende solo dall'``ast`` del codice, dalla chiave e dalla configurazione.

Un ``Slot`` è un sito strutturale (1 bit, maschera se ``mask=on``) o una variabile del canale dei
nomi (1 bit con V1b/V2/V2b, 2 bit consecutivi con V1; mai maschera).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from multimark._astindex import AstIndex
from multimark.channels import ReadOptions
from multimark.config import Config
from multimark.linking import mask as site_mask
from multimark.linking import offset, phi_function, phi_positional, phi_single_run
from multimark.names import (
    NameSite,
    name_bit,
    name_sites,
    name_slot,
    read_style,
    read_style_v1b,
)
from multimark.sites import Site, find_sites, loop_form_targets


@dataclass(frozen=True)
class Slot:
    """Un sito con le sue posizioni di bit (``indices``) e la maschera (0 per i nomi)."""

    channel: str
    indices: tuple[int, ...]
    mask: int = 0
    site: Optional[Site] = None
    name: Optional[NameSite] = None

    @property
    def is_name(self) -> bool:
        return self.name is not None

    @property
    def key(self) -> tuple:
        if self.site is not None:
            return self.site.key
        assert self.name is not None
        return self.name.key


@dataclass(frozen=True)
class Vote:
    """Voto di un sito su una posizione: ``value`` già smascherato, peso ``weight``."""

    index: int
    value: int
    weight: float
    slot: Slot
    value_read: Optional[int]


@dataclass
class Layout:
    slots: list[Slot]
    b: int

    @property
    def structural(self) -> list[Slot]:
        return [s for s in self.slots if not s.is_name]

    @property
    def names(self) -> list[Slot]:
        return [s for s in self.slots if s.is_name]

    @property
    def n_bits(self) -> int:
        """``N`` di §3.9: voti potenziali (2 per variabile con V1)."""
        return sum(len(s.indices) for s in self.slots)


def name_width(cfg: Config) -> int:
    return 2 if cfg.names_variant == "V1" else 1


def read_options(cfg: Config) -> ReadOptions:
    return ReadOptions(canonical=cfg.canonical, guards=True, channels=cfg.channels)


def build_layout(index: AstIndex, cfg: Config, key: int) -> Layout:
    """Siti del codice e loro posizioni di bit secondo ``cfg.linking`` (§3.4, §4.1)."""
    b = cfg.codeword_length
    sites = find_sites(index, read_options(cfg))
    names: list[NameSite] = []
    if cfg.names_variant != "V0":
        names = name_sites(
            index,
            include_params=cfg.names_include_params,
            excluded_binding_ids=loop_form_targets(sites, index),
            module_level=cfg.names_module_level,
        )
    width = name_width(cfg)
    use_mask = cfg.mask == "on"

    def smask(site: Site) -> int:
        if not use_mask:
            return 0
        return site_mask(key, site.unit.name, site.unit.n_params, site.channel, site.rank)

    slots: list[Slot] = []
    if cfg.linking == "positional":
        pool_names = sorted(names, key=lambda n: n.position)
        pool_sites = sorted(sites, key=lambda s: index.position[id(s.node)])
        n_name_slots = 0 if cfg.names_variant == "V2b" else width * len(pool_names)
        phi = phi_positional(key, n_name_slots + len(pool_sites), b)
        i = 0
        for ns in pool_names:
            if cfg.names_variant == "V2b":
                slots.append(Slot("names", (name_slot(key, ns.name, b),), name=ns))
                continue
            slots.append(Slot("names", tuple(phi[i : i + width]), name=ns))
            i += width
        for s in pool_sites:
            slots.append(Slot(s.channel, (phi[i],), smask(s), site=s))
            i += 1
        return Layout(slots, b)
    if cfg.linking == "function_single_run":
        run: dict[int, int] = {}
        for s in sites:
            r = run.get(s.unit.index, 0)
            run[s.unit.index] = r + 1
            idx = phi_single_run(key, s.unit.name, s.unit.n_params, r, b)
            slots.append(Slot(s.channel, (idx,), smask(s), site=s))
        for ns in names:
            r = run.get(ns.unit.index, 0)
            run[ns.unit.index] = r + width
            if cfg.names_variant == "V2b":
                indices: tuple[int, ...] = (name_slot(key, ns.name, b),)
            else:
                indices = tuple(
                    phi_single_run(key, ns.unit.name, ns.unit.n_params, r + j, b)
                    for j in range(width)
                )
            slots.append(Slot("names", indices, name=ns))
        return Layout(slots, b)
    # function_channel (base di multimark)
    for s in sites:
        idx = phi_function(key, s.unit.name, s.unit.n_params, s.channel, s.rank, b)
        slots.append(Slot(s.channel, (idx,), smask(s), site=s))
    for ns in names:
        if cfg.names_variant == "V2b":
            indices = (name_slot(key, ns.name, b),)
        else:
            off = offset(key, ns.unit.name, ns.unit.n_params, "names", b)
            indices = tuple((off + width * ns.rank + j) % b for j in range(width))
        slots.append(Slot("names", indices, name=ns))
    return Layout(slots, b)


def name_value(slot: Slot, key: int, cfg: Config) -> Optional[int]:
    """Valore letto di una variabile: bit (V1b/V2/V2b) o stile a 2 bit (V1); ``None`` se lo
    stile non si legge."""
    assert slot.name is not None
    name = slot.name.name
    if cfg.names_variant in ("V2", "V2b"):
        return name_bit(key, name)
    if cfg.names_variant == "V1":
        return read_style(name)
    return read_style_v1b(name)


def read_votes(
    layout: Layout, key: int, cfg: Config, weights: Optional[dict[str, float]] = None
) -> list[Vote]:
    """Voti di tutti i siti (§3.10): ``b(s) XOR mask(s)`` per i siti strutturali, il bit o lo
    stile della variabile per i nomi; i valori non leggibili non votano."""
    votes: list[Vote] = []
    for slot in layout.slots:
        w = (weights or {}).get(slot.channel, 1.0)
        if slot.site is not None:
            v = slot.site.value
            votes.append(Vote(slot.indices[0], v ^ slot.mask, w, slot, v))
            continue
        value = name_value(slot, key, cfg)
        if value is None:
            continue
        if len(slot.indices) == 2:
            votes.append(Vote(slot.indices[0], value >> 1, w, slot, value))
            votes.append(Vote(slot.indices[1], value & 1, w, slot, value))
        else:
            votes.append(Vote(slot.indices[0], value, w, slot, value))
    return votes
