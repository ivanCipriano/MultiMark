# Istruzioni per Claude Code — repository `MultiMark` (`multimark`, metodo di watermarking multi-bit post-hoc)

Prima di qualsiasi lavoro leggi `PIPELINE_metodo.md` per intero. È la specifica vincolante: in caso di ambiguità fermati e chiedi a Ivan, non reinterpretare.

## Cosa c'è qui
- `multimark/`: la libreria del metodo (puro Python ≥ 3.9; dipendenza obbligatoria `libcst`; `torch` e `transformers` solo nell'extra `[neural]`). Contiene sia il metodo proposto (`multimark`) sia la reimplementazione di MCSS (`mcss`), che è lo stesso codice con gli interruttori di `PIPELINE_metodo.md` §3.11.
- `tests/`: test unitari e di proprietà (`pytest`, `hypothesis`).
- `PROVENANCE.md`: ogni file o funzione ripresa da altri repository (es. Zottarelli), con repository, commit, file d'origine, funzione, data e modifiche fatte.
- Questo repository è agganciato come submodule `third_party/multimark` del benchmark `wm-bench`. Adapter, shim, configurazioni e tutto ciò che riguarda il benchmark **non** stanno qui.

## Regole fisse
- Rispondi sempre in italiano. Identificatori, nomi di file, chiavi di configurazione e log in inglese; docstring e commenti in italiano.
- Valgono le regole di `PIPELINE_metodo.md` §1: una fase alla volta, nell'ordine; nessun passaggio alla fase successiva senza i criteri di accettazione; riepilogo a fine fase (fatto, aperto, decisioni richieste).
- Non fare mai `git push` e non modificare i remote: lo fa Ivan. Commit locali piccoli con messaggio `[P<n>] <area>: <descrizione>`.
- Nessun segreto nei file. Nessun percorso del cluster nel codice.
- Lettura del codice solo con `ast` della libreria standard; LibCST solo per scrivere e per rinominare rispettando gli scope (`PIPELINE_metodo.md` §0.1 e §3.3.3). Nessun canale che dipenda da spazi, a capo o commenti.
- Il codice deve restare compatibile con Python 3.9 (gira nei worker del benchmark): niente `match`, niente `X | Y` nei tipi valutati a runtime, `from __future__ import annotations` in ogni modulo.
- Ogni nuovo modulo ha test; `pytest`, `ruff` e `mypy` (non strict) puliti prima di ogni commit.
- Ogni deviazione da MCSS (paper arXiv 2607.06009v1) va scritta subito nella sezione «Deviazioni dal paper» di `docs/mcss_deviations.md` di questo repository; il benchmark la riprende nell'audit.
- Non inventare valori: dove serve una scelta non coperta dalla pipeline, `TODO(ivan)` nel codice e nel riepilogo.
- A ogni fase che cambia il comportamento del codice, oltre ai test, scrivi `docs/reports/P<n>_esempi.md` con due o tre esempi completi (codice di partenza, siti, bit, codice marcato con diff, rilettura e punteggio; se c'è un attacco, anche prima/dopo), secondo `PIPELINE_metodo.md` §1 regola 12. Ivan li legge a mano: sono parte dei criteri di accettazione.
