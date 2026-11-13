"""Ricerca dei siti strutturali sull'``ast`` (PIPELINE_metodo.md §3.2–3.4).

Passi, identici in inserimento e rilevazione:

1. visita in pre-ordine esplicita del modulo; per ogni nodo, i candidati di tutti i canali
   (``channels.recognize``);
2. sovrapposizioni (§3.3.2 punto 3): un nodo ``ast`` appartiene al più a un sito; si accettano i
   candidati canale per canale, dal numero minore al maggiore e, nello stesso canale, in ordine di
   visita; un candidato che contiene un nodo già assegnato viene scartato;
3. rango (§3.4): indice del sito fra i siti dello stesso canale della stessa unità di funzione, in
   ordine di visita (0-based);
4. ordine di uscita (§3.9): funzioni in ordine di visita, poi ``MODULE``; dentro l'unità, canali
   1..8; dentro il canale, rango.

Nota (TODO(ivan)): il rango è per unità di funzione (oggetto), come nello pseudocodice di §3.9. Due
funzioni con lo stesso ``fid`` (stesso nome e numero di parametri, es. metodi omonimi di classi
diverse) hanno quindi siti con la stessa chiave ``(fid, canale, rango)``; in P1 va deciso se è
voluto (stesso ``off`` e stessa maschera) o se va disambiguato.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Optional

from multimark._astindex import AstIndex, FunctionUnit
from multimark.channels import CHANNEL_NUMBER, CHANNELS, Match, ReadContext, ReadOptions, recognize

SiteKey = tuple[str, int, str, int]


@dataclass(frozen=True)
class Site:
    """Sito strutturale: unità di funzione, canale, rango, valore letto (0/1) e posizione del nodo
    radice (``lineno``, ``col_offset``) per ritrovarlo nel CST (§3.3.3)."""

    unit: FunctionUnit
    channel: str
    rank: int
    value: int
    lineno: int
    col_offset: int
    node: ast.AST = field(compare=False, repr=False, hash=False)
    owned: frozenset[int] = field(default=frozenset(), compare=False, repr=False, hash=False)

    @property
    def key(self) -> SiteKey:
        """``(fid_name, n_params, channel, rank)``: chiave del sito nei confronti fra
        rilevazioni."""
        return (self.unit.name, self.unit.n_params, self.channel, self.rank)


def _resolve_overlaps(candidates: list[Match], index: AstIndex) -> list[Match]:
    """Regola «vince il canale con numero minore», poi l'ordine di visita."""
    ordered = sorted(
        candidates,
        key=lambda m: (CHANNEL_NUMBER[m.channel], index.position[id(m.node)]),
    )
    claimed: set[int] = set()
    accepted: list[Match] = []
    for match in ordered:
        if match.owned & claimed:
            continue
        claimed |= match.owned
        accepted.append(match)
    return accepted


def find_sites(
    index: AstIndex, options: Optional[ReadOptions] = None, ctx: Optional[ReadContext] = None
) -> list[Site]:
    """Siti strutturali del modulo, nell'ordine di §3.9."""
    ctx = ctx or ReadContext(index, options or ReadOptions())
    candidates: list[Match] = []
    for node in index.order:
        candidates.extend(recognize(node, ctx))
    accepted = _resolve_overlaps(candidates, index)
    accepted.sort(key=lambda m: index.position[id(m.node)])
    ranks: dict[tuple[int, str], int] = {}
    sites: list[Site] = []
    for match in accepted:
        unit = index.unit_of(match.node)
        rank = ranks.get((unit.index, match.channel), 0)
        ranks[(unit.index, match.channel)] = rank + 1
        sites.append(
            Site(
                unit=unit,
                channel=match.channel,
                rank=rank,
                value=match.value,
                lineno=getattr(match.node, "lineno", 0),
                col_offset=getattr(match.node, "col_offset", 0),
                node=match.node,
                owned=match.owned,
            )
        )
    sites.sort(key=lambda s: (s.unit.order_key, CHANNEL_NUMBER[s.channel], s.rank))
    return sites


def find_sites_in_code(code: str, options: Optional[ReadOptions] = None) -> list[Site]:
    """Come ``find_sites``, partendo dal sorgente. Solleva ``SyntaxError`` se non si analizza."""
    return find_sites(AstIndex.from_code(code), options)


def loop_form_targets(sites: list[Site], index: AstIndex) -> frozenset[int]:
    """Id dei bersagli ``x`` dei cicli dei siti ``list_comp`` in forma 0: per la regola di non
    interferenza non sono binding del canale dei nomi (``names.name_sites``)."""
    out: set[int] = set()
    for site in sites:
        if site.channel == "list_comp" and site.value == 0:
            loop = index.next_sibling(site.node)
            if isinstance(loop, ast.For):
                out.add(id(loop.target))
    return frozenset(out)


def count_by_channel(sites: list[Site]) -> dict[str, int]:
    """Numero di siti per canale (tutti i canali, anche a zero)."""
    counts = {c: 0 for c in CHANNELS}
    for site in sites:
        counts[site.channel] += 1
    return counts
