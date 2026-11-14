# PIPELINE_metodo.md — MultiMark: watermark multi-bit post-hoc per Python nel benchmark wm-bench

> **Destinatario:** Claude Code. **Natura:** specifica vincolante di implementazione. In caso di ambiguità, fermati e chiedi a Ivan; non reinterpretare.
> **Versione:** 1.2.2, 14 novembre 2026 (matrice `dmin4` per `multimark`, §3.8; v1.2.1 del 13 sera: regola di scope per i nomi nuovi, `else_return` forma 0 solo in coda al blocco, MD15–MD17 accettate) (dopo l'inventario di P0: canali nuovi 9–14, variabili di modulo, criteri di P2 rivisti, autovalidazione `mcss` rivista, rilevazione aggregata; le modifiche rispetto alla 1.1 sono marcate «**[v1.2]**»). **Repository:** `multimark` (libreria del metodo, questo file sta nella sua radice) e `wm-bench` (benchmark, commit di partenza `a64f4ea`, ramo `posthoc-multimark`), vedi §0.4.
> **Convenzioni:** prosa, docstring e commenti in italiano; identificatori, nomi di file, chiavi di configurazione e log in inglese (CLAUDE.md del benchmark). Le pagine di MCSS sono quelle del PDF arXiv 2607.06009v1.

---

## 0. Contesto e obiettivi

### 0.1 Cosa si costruisce

Due metodi nuovi nel benchmark, entrambi post-hoc (`CodeEmbedder + Detector`), solo Python, nello stesso ambiente conda `posthoc` e nella stessa libreria: il pacchetto Python `multimark` del repository `multimark` (§0.4):

| Nome nel benchmark | Cosa è | Ruolo |
|---|---|---|
| `mcss` | Reimplementazione fedele di Multi-Channel Spread-Spectrum (Choi, Gao, Duan, 2026) dal paper, con le sole deviazioni dichiarate in §4 | riga di confronto |
| `multimark` | Metodo proposto, **MultiMark** (nome provvisorio), 24 bit | metodo della tesi, configurazione principale |

**Lettura e scrittura del codice (vale per tutto il documento).** I siti si trovano e si leggono **solo** sull'`ast` della libreria standard, che non vede spazi, a capo e commenti; i canali di formattazione sono esclusi. LibCST si usa **solo per scrivere** la forma richiesta di un sito e per rinominare le variabili rispettando gli scope (come fa l'attacco T1.4 del benchmark), così il resto del file resta identico, commenti compresi; dopo ogni scrittura il file viene riletto con `ast` e il valore deve coincidere. Il segnale del watermark non dipende mai dal CST (è il punto debole del metodo di Zottarelli segnalato dal prof il 5 novembre).

**Configurazione di base di `multimark`** (§3 per le specifiche): identificazione per confronto con il registro (1A) con punteggio principale a `N_reg = 1` e secondari a `N_reg ∈ {16, 1024}`; mascheramento con la chiave (1B); legame sito → bit per (funzione, canale) con offset da (nome della funzione, numero di parametri) (2A); forme canoniche indipendenti dai nomi (2D); **[v1.2]** 14 canali strutturali: gli 8 di MCSS più i 6 nuovi di §3.3.1b (`channels=extended`); canale dei nomi V2 (bit da HMAC del nome normalizzato, candidati da un modello di linguaggio piccolo con ripiego non neurale), parametri esclusi, variabili di modulo secondo la decisione O (§7); voto semplice (pesi uniformi); codice compatto con t = 2 (B = 32); messaggio di 24 bit.

**[v1.2] Obiettivo sul codice corto, ridefinito dopo l'inventario di P0.** Sulle funzioni di L1 (mediana 1–2 siti, 0% con ≥ 13) nessun metodo strutturale post-hoc può rilevare il singolo campione: non è un difetto da correggere con più canali (stima P0: con 8 canali nuovi la frazione di campioni L1 con ≥ 8 siti passa da 3–8% a 4–10%). La tesi misura quindi **due cose**: (1) la rilevazione per campione nella fascia 8–31 siti, dove MCSS a 32 bit non entra e `multimark` sì (L2 con 21+ righe, ClassEval); (2) la **rilevazione aggregata** su k campioni dello stesso modello (§5.10), che è la risposta onesta per L1. La F5.1 della tesi ha l'asse x in numero di siti; la selezione dei file CodeNet per l'autovalidazione di `mcss` (§4.4) è in **bit** (`n_bits_v1`, come la Tabella 3 del paper): i due assi non vanno confusi.

### 0.2 Cosa è escluso

- Marcatura del codice umano nel benchmark (al più un esperimento piccolo fuori benchmark, alla fine, P7 punto 6).
- Integrazione del metodo di Zottarelli come metodo del benchmark (dopo `multimark`, solo se avanza tempo). Il suo repository si legge **solo** come fonte di trasformazioni (P8).
- Tetto per canale (2C), stima dell'affidabilità per sito con gradient boosting, decodificatore neurale, trasformazioni generate da LLM, crittografia asimmetrica, Merkle tree, canali di formattazione.
- Linguaggi diversi da Python: le celle Java, C++, JavaScript sono `NOT_APPLICABLE` senza invocare il worker (come ACW, D6).

### 0.3 Decisioni già prese da Ivan (non rimetterle in discussione)

- α = 1% (soglia del benchmark); `N_reg` secondari 16 e 1024.
- `message_accuracy` su tutti i positivi (come MCGMark) e in più `message_accuracy_detected` condizionata al rilevamento, come metrica secondaria.
- Confronto con MCGMark: `multimark` a 24 bit; nella tesi si scrive esplicitamente «24 bit contro 12» (D1). Nessuna versione a 12 bit del metodo (decisione del 12 novembre).
- Variante del canale dei nomi scelta **fuori dall'HPO**, sui soli dati di sviluppo, con il criterio fissato di §6.4 (il limite di AUROC va confermato dal prof).
- Attacchi nuovi: `T1.6` (tutto in `snake_case`) e `T2.5` (diluizione). Metriche nuove: `bits_correct` e lunghezza del messaggio per metodo, capacità sotto attacco, attribuzioni sbagliate, curva per numero di siti, FPR per l'identificativo peggiore, flip rate per canale, `conditional_preservation` per ogni `CodeEmbedder`.
- Solo se avanza tempo: rinomina della funzione d'ingresso, T2.1 per singolo canale, prova di aggiunta o rimozione di un sito.

### 0.4 Due repository

| Repository | Contiene | Chi lo modifica |
|---|---|---|
| **`multimark`** (il metodo; radice = questo file) | pacchetto `multimark/` (puro Python ≥ 3.9: `sites.py`, `channels.py`, `names.py`, `names_neural.py`, `linking.py`, `codec.py`, `prf.py`, `embed.py`, `detect.py`, `inventory.py`, `data/name_synonyms.json`, `cli/`), `tests/`, `PROVENANCE.md`, `CLAUDE.md`, `pyproject.toml`, `README.md`. Nessuna dipendenza dal benchmark: il profilo `mcss` è lo stesso pacchetto con gli interruttori di §3.11 | sessioni di Claude Code aperte nel repository `multimark` |
| **`wm-bench`**, ramo `posthoc-multimark` | il metodo come submodule `third_party/multimark` (come gli altri cinque), `patches/multimark/README.md` (nessuna patch), `environment-posthoc.yml`, `configs/method/{mcss,multimark}.yaml`, `configs/hpo/*`, `src/bench/methods/adapters/{mcss,multimark}.py`, `shims/bench_shims/{mcss,multimark}/`, `docs/audit/{mcss,multimark}.md`, ADR, deviazioni, modifiche comuni (§5), script e attacchi nuovi | sessioni di Claude Code aperte nel benchmark; **mai** modificare `third_party/multimark` da lì (regola del CLAUDE.md del benchmark): le modifiche alla libreria si fanno nel repository `multimark`, poi si aggiorna il puntatore del submodule (commit `[P<n>] submodule: multimark → <commit>`) |

I worker eseguono `build/patched/multimark/` (copia del submodule fatta da `scripts/apply_patches.sh multimark`, zero patch) con `PYTHONPATH` = `shims/` + `build/patched/multimark`; il commit del submodule entra nel `config_hash` come per gli altri metodi (`MethodAdapter.source_commit`).

---

## 1. Regole di lavoro

1. Valgono tutte le regole di `CLAUDE.md` e di `SPEC.md` §0 del benchmark: audit prima dell'adapter (`docs/audit/<metodo>.md`), test per ogni modulo nuovo, `mypy --strict` pulito su `src/bench` e `packages/bench-contracts`, `ruff` pulito, un ADR per ogni decisione architetturale, ogni deviazione dal protocollo in `docs/deviations.md` con ID progressivo (il prossimo libero è **D42**).
2. **Mai** `git push`, **mai** modificare i remote. Commit locali piccoli, un argomento per commit, messaggio `[P<n>] <area>: <descrizione>` dove `<n>` è la fase di §2 (prefisso `P` per distinguerli dalle milestone `M` del benchmark).
3. Nel benchmark si lavora sul ramo `posthoc-multimark` (creato da Ivan da `main`); nel repository `multimark` sul ramo `main`. Le modifiche alle parti comuni del benchmark (§5) vanno in commit separati e marcati `[P<n>] common: …`, così Ivan può mostrarli a Simone prima di unirli. Ogni fase che tocca entrambi i repository finisce con l'aggiornamento del submodule nel benchmark.
4. Nessun segreto in file, log o manifest. Nessuna chiave reale: le chiavi del watermark le deriva il benchmark (`MethodAdapter.key`).
5. **Non cancellare mai risultati esistenti** sotto `artifacts/`; i log già salvati in `docs/milestone_logs/` non si sovrascrivono: ogni nuovo log ha un nome nuovo con prefisso `P<n>_`. I risultati superati si spostano in `superseded/`, come già fatto per MCGMark (D32).
6. **Nessuna ricalibrazione sul test.** Soglie solo sui negativi umani di sviluppo (I3); nessuna fase con `split=test` prima del congelamento del metodo (ADR-013); `hpo.allow_frozen_override` resta `false`.
7. Ogni differenza fra la reimplementazione `mcss` e il paper va scritta **nel momento in cui si decide**, non alla fine: nel repository `multimark` in `docs/mcss_deviations.md` (lo tiene aggiornato la sessione che lavora sulla libreria); il benchmark la riprende in `docs/audit/mcss.md` §«Deviazioni dal paper» in P2.
8. Non si passa alla fase successiva senza aver superato tutti i criteri di accettazione della fase corrente; alla fine di ogni fase si consegna a Ivan un riepilogo (fatto, aperto, decisioni richieste) e il log `docs/milestone_logs/P<n>_*.txt`.
9. Niente comandi per il cluster eseguiti da Claude Code (`sbatch`, `srun`, percorsi `/mnt/beegfs/...`): si scrivono completi e pronti da copiare per Ivan.
10. Il codice dei worker (shim e libreria) deve girare con Python ≥ 3.9 e usare solo stdlib più i pacchetti dell'ambiente `posthoc` (§2, fase P0). Il codice in `src/bench` è Python 3.11.
11. Quando un dato manca, prima si misura e poi si decide (vedi §7). Nessun iperparametro, prompt o valore inventato: dove serve una scelta non coperta da questo documento, `TODO(ivan)` nel codice e nel riepilogo.
12. **Report di esempi a ogni fase.** Oltre ai test, ogni fase che cambia il comportamento del codice (P0–P5, e P7 per i canali nuovi) produce `docs/reports/P<n>_esempi.md` nel repository `multimark` (per le fasi del benchmark, lo stesso file con suffisso `_bench`), con **due o tre esempi** reali o sintetici, letti da Ivan a mano. Per ogni esempio, nell'ordine: (1) codice di partenza intero; (2) tabella dei siti: funzione (`fid`), canale, rango, forma letta, `phi`, maschera, valore da scrivere; (3) messaggio e parola di codice in bit; (4) codice dopo l'inserimento e diff riga per riga; (5) rilettura: voti per bit, concordanze, punteggio, messaggio decodificato; (6) se la fase riguarda un attacco: codice attaccato, siti sopravvissuti/spostati/persi, voti e punteggio dopo. Gli esempi vanno scelti così: uno corto (funzione di HumanEval), uno con più funzioni (estrazione o diluizione), uno in cui qualcosa non va (sito annullato, nome senza candidato, decodifica fallita). Per P0 il report mostra, su tre file, i siti trovati per canale e, per alcuni nodi vicini, perché **non** sono siti. Il report è un criterio di accettazione della fase come i test.

---

## 2. Fasi

Ordine = priorità rivista. Tempi in giorni di lavoro di Claude Code, test compresi; «Ivan» indica ciò che fa Ivan.

### P0 — Ramo, ambiente, scheletro della libreria e inventario dei siti (3 giorni)

**Obiettivo.** Mettere in piedi il contenitore di tutto il lavoro e misurare quanti siti offre il codice corto, prima di qualsiasi scelta sui canali.

**File da creare.**
- `environment-posthoc.yml` (radice del repository). Contenuto minimo, versioni fissate alle stesse di `bench-core` dove il pacchetto esiste in entrambi (`environment-bench-core.yml`): `python=3.11`, `libcst==1.5.0`, `tree-sitter` + grammatica Python alla versione del lockfile di bench-core, `numpy==1.26.4`, `torch==2.4.1` (wheel CUDA 12.1), `transformers==4.46.3`, `accelerate==1.1.1`, `safetensors`, `tokenizers`, `pip install -e packages/bench-contracts`. Nessun altro pacchetto. Commento in testa: «Ambiente dei metodi post-hoc della tesi (mcss, multimark); creato da Ivan sul cluster con `conda env create -f environment-posthoc.yml -p <prefisso>/posthoc`».
- `configs/envs/envs.yaml`: voce `posthoc` con `TODO(ivan)` per il percorso dell'interprete.
- **Repository `multimark`:** `pyproject.toml` (pacchetto `multimark`, `requires-python >= 3.9`, dipendenze: `libcst`; `torch` e `transformers` come extra `[neural]`), `multimark/` con i moduli `sites.py` (ricerca dei siti sull'AST), `channels.py` (gli 8 canali: riconoscimento, lettura, scrittura), `names.py` (canale dei nomi), `linking.py` (φ e maschera), `codec.py` (messaggio, codice compatto, decodifica), `prf.py` (HMAC), `embed.py`, `detect.py`, `inventory.py`, `cli/inventory.py` (legge un JSONL di codici, scrive le tabelle di sotto); `tests/` con `pytest`; `README.md`; `PROVENANCE.md` vuoto con l'intestazione di P8.
- **Benchmark:** `.gitmodules` con `third_party/multimark` (lo aggiunge Ivan, §P0 passo 0), `scripts/setup_submodules.sh` e `scripts/apply_patches.sh` estesi a `multimark` (zero patch: `patches/multimark/README.md` lo dichiara), `configs/method/{mcss,multimark}.yaml` con `submodule: third_party/multimark`, `patched_dir: build/patched/multimark`.
- Benchmark, `scripts/inventory_sites.py`: dato un parquet di campioni (`problems` canoniche o `baseline`) scrive una tabella con, per campione: `n_sites_total`, `n_sites_<canale>` per ciascun canale, `n_vars` (siti del canale dei nomi secondo la regola di §3.6), `n_functions`, `loc`; e un riepilogo per dataset (media, mediana, P25, P75, frazione con `n_sites_total ≥ 32`, `≥ 20`, `≥ 13`).

**Passi.**
0. (Ivan, prima di tutto) Repository `multimark` creato e agganciato come submodule: §10, passi 1–6.
1. Nel repository `multimark`: i file sopra, lo scheletro dei moduli con le firme di §3 e docstring. Nel benchmark: gli script e le configurazioni elencati.
2. Implementare `sites.py` e `channels.py` solo nella parte di **riconoscimento** (lettura dei siti e del loro valore), con i controlli di §3.3; la scrittura arriva in P1.
3. Implementare `inventory.py` e lo script; test unitari su frammenti sintetici per ogni canale (presente/assente, forma 0/forma 1, casi esclusi).
4. Ivan lancia lo script sul cluster su: canoniche L1 (HumanEval+, MBPP+), baseline L1 dev dei due modelli, canoniche e baseline L2 dev, canoniche ClassEval.

**Ingressi.** Tabelle `data/problems/*.parquet` e `baseline/<modello>/L1_python_dev.parquet`, `L2_python_dev.parquet`.
**Uscite.** `docs/milestone_logs/P0_inventory.txt` con le tabelle del riepilogo; `environment-posthoc.yml`.

**Criteri di accettazione.**
- Repository `multimark`: `pytest` verde (`tests/test_sites.py`, `tests/test_channels_read.py`), `ruff` pulito, `mypy` (non strict: Python 3.9) senza errori. Benchmark: `mypy --strict` su `src/bench` invariato; `ruff` pulito; `bash scripts/apply_patches.sh multimark` produce `build/patched/multimark` e `build/patched/multimark.source_commit`.
- Il riepilogo riporta, per L1 dev, la frazione di campioni con `n_sites_total ≥ 32` (atteso: bassa) e il canale più frequente. Questi numeri entrano nella tabella 4.1 della tesi (§6.6).
- Ivan ha creato l'ambiente e `bench doctor` lo vede (`configs/envs/envs.yaml` compilato).

**Ivan:** crea l'ambiente dal file, lancia l'inventario, riporta `P0_inventory.txt`. **Claude Code:** tutto il resto.

**[v1.2] Esito di P0 (13 novembre, `P0_inventory.txt`, `P0_candidates.txt`, `P0_mcss_selftest.txt`; libreria `fe44298`).**
- L1 dev: mediana 1–2 siti per campione, 22–45% con zero siti, 0% con ≥ 13. L2 dev: media 3,6–4,7. ClassEval: media 11,6, 33% con ≥ 13. Pool CodeNet L2 (5.449 file, profilo base): media 3,1 siti, 0,31% con ≥ 32, 3,4% con ≥ 13; `n_vars` medio 0,37 perché le soluzioni CodeNet sono quasi tutte a livello di modulo (`n_functions` mediana 0) e la regola di §3.6.1 contava solo le variabili dentro le funzioni. Canale più frequente: `equality_dir` (nel paper è `operand_order`, p. 5: la nostra condizione «esattamente una costante numerica» è più stretta, deviazione 6 di §4.2).
- Candidati (23 pattern, ranking `no_overlap` su L1): `range_zero` 148, `slice_bound` 124, `else_return` 90, `nested_if` 59, `square` 46, `range_len` 28, `return_none` 25, `bool_return` 18, poi ≤ 13. `str_method` forma 0 presente nel 78–85% dei campioni L2 ma la forma 1 (`str.split(s)`) non compare mai e serve una guardia sul tipo. `elif` e `else: if` sono lo stesso `ast`: non è un canale. Decisioni sui canali: §3.3.1b.
- Autovalidazione `mcss`: nel pool solo 37 file con `n_bits_v1 ≥ 32` e 18 nella fascia 32–39 (15 problemi); su quei 18, variabili 7,50 contro 11,9 (−37%) e siti strutturali 18,0 contro 10,9 (+65%); totale 33,0 contro 34,6 (−5%). Letture: (i) il paper usa anch'esso CodeNet Python (p. 7, «Dataset»), quindi la differenza è nelle regole di lettura, non nei dati: la più probabile è l'esclusione delle variabili di modulo; (ii) la fascia è definita sui bit totali, perciò dentro la fascia pochi nomi implicano molti siti strutturali (anticorrelazione da selezione): il confronto componente per componente non misura la fedeltà, il totale sì. Conseguenze in §4.4 (criterio sul totale, selezione rifatta dopo la decisione O) e in §7 (K, O).
- Decisione C chiusa: parametri **esclusi** dal canale dei nomi di `multimark` (rinominarli cambia la firma e rompe i test di chi chiama); nel pool i parametri valgono il 31% dei siti dei nomi (2.619 contro 1.995): la perdita si dichiara e `names.include_params=true` resta un punto dell'ablazione (§6.3).

---

### P1 — Libreria: inserimento e rilevazione, `mcss` e `multimark` (6 giorni)

**Obiettivo.** Libreria completa e autoverificata: scrittura dei siti via LibCST, legame positionale (mcss) e per funzione (multimark), maschera, codice compatto, due modalità di lettura (confronto e decodifica), canale dei nomi V1 (stili) e V2 (nome con chiave) con ripiego non neurale. Il modello neurale dei nomi arriva in P3.

**File.** Repository `multimark`: completamento di `multimark/*` secondo §3 e §4; `tests/test_*.py`; `tests/test_roundtrip_property.py` (Hypothesis, dipendenza di sviluppo). Tutto in questa fase sta nel repository `multimark`; alla fine Ivan aggiorna il submodule nel benchmark.

**Passi.**
0. **[v1.2] Prima di tutto, in un commit a parte (`[P1] names: module-level variables option`)**, così Ivan può rilanciare l'inventario sul cluster mentre P1 prosegue: (a) opzione `names.module_level` (§3.6.1) nel lettore e nell'inventario (`--module-level on|off`), con le guardie elencate lì; (b) in `candidates.py` la forma `g.f0_guarded` di `str_method` (ricevitore letterale stringa, f-string, o chiamata a `input`/`str`/`repr`; §3.3.1b, canale 15 facoltativo); (c) test. Poi Ivan: aggiorna il submodule, `apply_patches.sh multimark`, rilancia `inventory_sites.sh` (tutti i gruppi, profili `base` e `mcss`, entrambi i valori di `--module-level`), `candidates` e `selftest`; i file nuovi si chiamano `P1_inventory_modlevel.txt`, `P1_candidates_modlevel.txt`, `P1_mcss_selftest_modlevel.txt` (i vecchi non si toccano, regola 5). Da quei numeri Ivan chiude le decisioni O e P di §7.
1. `channels.py`: lettura dei 6 canali nuovi di §3.3.1b (9–14) e scrittura di **tutti** i canali con LibCST (`PositionProvider` per ritrovare il nodo dal sito, §3.3.3). Dopo ogni scrittura: `ast.parse` del risultato e rilettura del sito; se la rilettura non dà il valore scritto, la scrittura si annulla e il sito è `skipped` (contato in `extra`). Opzione `channels` (§3.11): `mcss8` (canali 1–8) e `extended` (1–14).
2. `codec.py`: alfabeto a 6 bit (§3.7), codice compatto (§3.8), decodifica per cancellazioni.
3. `linking.py`: `phi_positional` (mcss) e `phi_function` (multimark), maschera (§3.4–3.5).
4. `names.py`: V1 (4 stili con estensione dei nomi di una parola, §4.3), V1b, V2 con il proponente `StaticProposer` (§3.6.4); interfaccia `Proposer` per il modello neurale di P3.
5. `embed.py`, `detect.py`: pipeline di §3.9 e §3.10 con tutte le opzioni di configurazione di §3.11.
6. Test di autovalidazione (§4.4) e proprietà: per 500 frammenti generati (funzioni sintetiche con siti di tutti i canali) e 100 chiavi, `detect(embed(code, m, K), K)` restituisce `m` (decodifica) e punteggio massimo (confronto) quando `N ≥ B`; con `N < B` il confronto dà il punteggio atteso e la decodifica dichiara cancellazioni; invarianza a `black`, `ruff --fix`, rimozione dei commenti: letture identiche.

**Ingressi.** Nessuno dal cluster. **Uscite.** Libreria, test, `docs/milestone_logs/P1_selftest.txt` (riassunto dei test di proprietà: numero di frammenti, chiavi, esiti).

**Criteri di accettazione.**
- Round trip 100% sui frammenti sintetici con `N ≥ B`, per `mcss` e `multimark`; invarianza alla formattazione 100%.
- Ogni canale ha un test «cambio di forma = stesso output»: per ogni frammento di test con un `main` eseguibile, l'output di forma 0 e forma 1 coincide (`subprocess` con timeout 5 s, senza sandbox: sono frammenti scritti da noi). **[v1.2]** Per i canali 9–14 il test include i casi limite elencati in §3.3.1b (es. `square` con `float`, `nested_if` con tre `if` annidati, `else_return` seguito da un altro `if`).
- **[v1.2]** Test di non interferenza (§3.3.2 punto 3) su frammenti che combinano canali vecchi e nuovi sullo stesso nodo (`if a and b: return X` + istruzioni dopo; `L = list(a)`; `x = x + 1` dentro `range(0, x + 1)`): `sites(embed(code)) == sites(code)` per tutte le 2^k scritture possibili dei siti coinvolti.
- Tempo di inserimento + rilevazione su un file da 100 righe < 1 s su CPU (misurato nel log).
- **[v1.2]** `docs/reports/P1_esempi.md` (regola 12) con almeno un esempio per ciascun canale nuovo.

**Ivan:** rilancia inventario, candidati e selftest dopo il passo 0 e riporta i tre file. **Claude Code:** tutto il resto.

---

### P2 — Adapter, shim, audit, modifiche comuni al benchmark (5 giorni)

**Obiettivo.** I due metodi girano nel benchmark su L1 dev; le quattro modifiche comuni indispensabili sono fatte, retrocompatibili, con ADR e test.

**File.**
- `configs/method/{mcss,multimark}.yaml`, `configs/hpo/{mcss,multimark}.yaml` (un solo punto ciascuno, §6.4), `configs/hpo/multimark_ablation.yaml` (§6.3).
- `src/bench/methods/adapters/{mcss,multimark}.py` (`Mbw12Adapter` nello stesso file di `multimark`, eredita), registrazione in `adapters/__init__.py`.
- `shims/bench_shims/{mcss,multimark}/__init__.py`, `__main__.py` (due entry point, una classe comune `PosthocShim` in `shims/bench_shims/multimark/shim_base.py`, che importa il pacchetto `multimark` da `build/patched/multimark` tramite il `PYTHONPATH` del worker).
- `docs/audit/mcss.md`, `docs/audit/multimark.md` (punti 1–9 di SPEC §9.0; per `mcss` il punto 2 descrive gli algoritmi del paper invece del codice; sezione «Deviazioni dal paper»).
- Modifiche comuni di §5.1–§5.4 con i loro test e ADR.
- `configs/config.yaml`: aggiunta dei due metodi a `methods_catalog`; **non** a `methods` di default (lì restano i cinque, per non cambiare i lanci di Simone).
- `src/bench/chains.py`: `LANGS` e `METHOD_OWNER` per i due metodi (`ivan`), senza toccare le voci esistenti.

**Passi.**
1. Adapter: `family=POST_HOC`, `gpu_for_embed=True` per `multimark` (modello dei nomi; `False` finché il proponente è quello statico: parametro `names.proposer`), `gpu_for_detect=False`; `to_native_hparams` valida le chiavi di §3.11; `message_for` e `expected_message` come MCGMark (`message_bits`, §3.7); `secondary_scores = {"nreg16": "score_nreg16", "nreg1024": "score_nreg1024", "decode": "score_decode"}`; `message_bits: ClassVar[int] = 24`; `embed_metrics` con `n_sites`.
2. Shim: `embed_batch`/`detect_batch`; `extra` secondo §3.10.4. Stato di inserimento secondo §3.9.3.
3. Modifiche comuni (§5), ciascuna in un commit `common` con il suo test di retrocompatibilità.
4. Smoke test locale: `bench +experiment=smoke stage=…` sulle fixture `tests/fixtures/tiny/` per i due metodi (watermark → execute → detect → calibrate → metrics), con `paths=local`.
5. Ivan lancia su L1 dev **e L2 dev** **[v1.2]**: `watermark`, `execute`, `detect` (positivi, `neg_human`, `neg_llm`), `calibrate` (provvisorio, L1+L2), `metrics` per `mcss` e `multimark`, entrambi i modelli; su ClassEval (canoniche come ingresso, come fa il benchmark per L3) solo `watermark`, `execute`, `detect` di `multimark`. In più `scripts/mcss_paper_attacks.py --attack none` sulla selezione di §4.4 (criterio (a)).

**Ingressi.** Baseline L1 dev, L2 dev; canoniche ClassEval; selezione CodeNet di §4.4. **Uscite.** Tabelle `watermarked/`, `detection/`, `thresholds/`, `metrics/` dei due metodi; `docs/milestone_logs/P2_dev.txt` con `scripts/report_metrics.py` (estendere lo script ai due metodi se filtra per nome) e `scripts/report_capacity.py` (§5.6, anticipato da P3 a P2 nella sola versione da riga di comando).

**Criteri di accettazione.**
- `pytest tests/unit tests/contract -m "not gpu"` verde, compresi i test di retrocompatibilità di §5 (metriche identiche a prima su tabelle di MCGMark/ACW/STONE sintetiche e su una cella reale già calcolata, confronto con `metrics/metrics.parquet` esistente a tolleranza 1e-9).
- `mypy --strict`, `ruff`, `pre-commit` puliti.
- **[v1.2]** Criteri funzionali (su L1 dev nessun campione ha ≥ 32 siti e lo 0% ne ha ≥ 13: i criteri si misurano dove i siti ci sono):
  (a) `mcss` senza attacchi: `message_accuracy` = 1,00 sui file CodeNet della selezione di §4.4 (fascia 32–39 bit; Tabella 4 del paper, p. 8: 100% no-attack), eseguiti con `scripts/mcss_paper_attacks.py --attack none`; `multimark` sugli stessi file: `message_accuracy` ≥ 0,99 sui file con `n_sites ≥ 32`.
  (b) `multimark` senza attacchi su **L2 dev e ClassEval** (fase `watermark`+`detect` lanciata anche su L2 dev in P2, non più solo in P4): TPR@1%FPR con soglia provvisoria L1+L2 ≥ 0,90 sui campioni con `n_sites ≥ 13` (tabella di §3.10.3, `N_reg = 1`, f = 0) e ≥ 0,70 sui campioni con `8 ≤ n_sites ≤ 12`.
  (c) su L1 dev si controlla solo che non ci siano errori: `embedding_success_rate` ≥ 0,99 sui campioni con almeno un sito, `FAILED` con motivo `no_sites` sugli altri, `fpr_human` ≤ 0,015.
  Se (a) o (b) non valgono c'è un bug: fermarsi.
- ΔPass@1 di `multimark` e `mcss` rispetto alla baseline ≤ 3 pp su L1 dev (vincolo dell'HPO); se maggiore, i siti responsabili si individuano con `scripts/debug_posthoc_failures.py` (benchmark, da scrivere: per ogni campione `PASSED` prima e `FAILED` dopo, il diff e i canali toccati) e il canale si corregge o si esclude, registrandolo nell'audit.
- `fpr_human` e `fpr_llm` ≤ 0,015 su L1 dev per i punteggi principale e secondari.

**Ivan:** ambiente già pronto; lancia le fasi; riporta il log. **Claude Code:** tutto il resto.

---

### P3 — Canale dei nomi V2 con modello neurale, attacchi T1.6 e T2.5, report per numero di siti (5 giorni)

**Obiettivo.** Completare la configurazione di base e gli strumenti di misura specifici.

**File.**
- Repository `multimark`, `multimark/names_neural.py`: `NeuralProposer` (§3.6.4) con `Qwen/Qwen2.5-Coder-0.5B-Instruct` (TODO(ivan): percorso locale nella cache HF del cluster; se assente, `1.5B`), caricato una volta per worker in `setup`.
- `src/bench/attacks/t1/snake_case.py` (`T1.6`), `configs/attack/t1_6_snake_case.yaml`.
- `src/bench/attacks/t2/dilution.py` (`T2.5`), `configs/attack/t2_5_dilution.yaml`, `src/bench/pipeline/stages/function_pools.py` (fase `function_pools`, artefatto `data/function_pools/python.parquet`), `src/bench/data/function_pools.py`.
- `src/bench/report.py`: tabella `tables/capacity_by_sites_<livello>.{csv,tex}` e figura `figures/capacity_by_sites_<livello>.{pdf,png}` (§5.6).
- `scripts/report_capacity.py` (stessa figura da riga di comando, per i controlli intermedi).
- ADR-018 (attacchi nuovi), ADR-020 (report per siti).

**Passi.**
1. `NeuralProposer`: prompt di infilling/riscrittura per una variabile (§3.6.4), 8 candidati per variabile, deterministico (greedy) a parità di chiave e codice; cache per (codice normalizzato, nome). Test: su 20 funzioni di `tests/fixtures/tiny`, i candidati sono identificatori validi, diversi dal nome originale, non riservati.
2. `T1.6` e `T2.5` secondo §5.5, con i test di proprietà del benchmark (determinismo dato il seme; canoniche di L1 verdi dopo l'attacco, marker `apptainer`; `UNCHANGED` se nulla cambia).
3. Report per numero di siti (§5.6) e test su tabelle sintetiche.
4. Ivan: fase `function_pools` (CPU, defq); rilancio `watermark` di `multimark` su L1 dev con `names.proposer=neural` (nuovo `config_hash`: i risultati con il proponente statico restano come variante dell'ablazione); verifica delle canoniche con `scripts/check_attacks_canonical.sh` esteso a T1.6 e T2.5.

**Criteri di accettazione.**
- Su L1 dev, frazione di variabili rinominate dalla V2 ≈ 50% ± 5 (deve esserlo per costruzione: metà dei nomi originali ha già il bit giusto); frazione di siti dei nomi senza candidato adatto < 5% (in `extra`).
- ΔPass@1 ≤ 3 pp invariato; `adversarial_logreg` su L1 dev calcolato per V2 e salvato per il confronto di P5.
- T1.6 e T2.5: canoniche L1 100% verdi; `changed_fraction` di T1.6 sui marcati `mcss` (V1) ≈ frazione di variabili a più parole (è l'attacco che annulla il canale degli stili); su `multimark` T1.6 non cambia il punteggio principale di più dello 0,5% in media (invarianza della V2 allo stile).
- La figura per numero di siti si genera da artefatti reali di L1 dev per `multimark`, `mcss`, `mcgmark`.

**Ivan:** lanci, percorso del modello. **Claude Code:** tutto il resto.

---

### P4 — Base definitiva su L1+L2 dev, misure utili, calibrazione definitiva (4 giorni)

**Obiettivo.** Soglie definitive (L1+L2) per i due metodi; FPR per l'identificativo peggiore; flip rate per canale; `conditional_preservation` generalizzata; confronto con il codice ufficiale di MCSS se disponibile.

**File.** `scripts/report_worst_id_fpr.py`, `scripts/report_flip_rate.py` (§5.7, §5.8); modifica di `metrics.py` per `conditional_preservation` (§5.4); `docs/audit/mcss.md` §«Confronto con il codice ufficiale» (se il codice è uscito).

**Passi.**
1. Ivan: `watermark`, `execute`, `detect` su **L2 dev** per i due metodi (configurazione di base); `calibrate` e `tune` su L1+L2 (`submit_hpo_l2.sh`-equivalente per i due metodi: scrivere `scripts/submit_posthoc_dev.sh`).
2. Script delle misure utili e loro test.
3. Se il codice ufficiale di MCSS è disponibile: Ivan lo copia fuori dal repository; Claude Code scrive `scripts/compare_mcss_official.py` che su 50 file CodeNet dev confronta pool dei siti (ordine e valori letti) e messaggi decodificati fra la nostra `mcss` e il codice ufficiale a parità di input; le differenze vanno in `docs/audit/mcss.md`. Niente patch al codice ufficiale.

**Criteri di accettazione.**
- Soglie L1+L2 non provvisorie per `mcss` e `multimark`, con `underpowered=False`.
- `report_worst_id_fpr.py` produce, per `mcss` e `multimark`, l'FPR dei negativi umani dev per ciascuno dei 66 messaggi fissi (§5.7); per `multimark` il massimo non supera il minimo di più di 3 volte l'errore binomiale; per `mcss` si riporta il valore (atteso molto più alto per il messaggio tutto a zero: è un risultato della tesi).
- `report_flip_rate.py` produce la tabella canale × attacco sui campioni di sviluppo attaccati (gli attacchi su dev si lanciano in P5).

**Ivan:** lanci. **Claude Code:** script e modifiche.

---

### P5 — Ablazioni su sviluppo e scelta della configurazione finale (5 giorni, in parallelo ai lanci)

**Obiettivo.** Un fattore alla volta rispetto alla base, tutto su L1+L2 dev, poi scelta con il criterio fissato di §6.4.

**Passi.**
1. Griglia `configs/hpo/multimark_ablation.yaml` con i punti di §6.3 (ogni punto cambia **un** fattore). Ivan lancia lo sweep (`hpo.grid=multimark_ablation hpo.use_selected=false`): `watermark`, `execute`, `detect`, `calibrate` su L1+L2 dev; poi gli attacchi di sviluppo di §6.3 sulle celle dev di ogni punto (`attack`, `execute`, `detect`, `metrics` con `split=dev`; le celle dev senza congelamento usano il `config_hash` del punto: `CellPlanner` dà l'hash congelato solo a `split=test`, `stage.py` riga 273).
2. `imperceptibility` (solo `adversarial_unixcoder` e `adversarial_logreg`) sulle celle L1 dev dei punti del fattore «canale dei nomi».
3. `scripts/select_multimark_config.py`: applica il criterio di §6.4 e scrive `docs/milestone_logs/P5_selection.txt` con tutti i numeri e la configurazione scelta; aggiorna `configs/hpo/multimark.yaml` e `configs/method/multimark.yaml` (`default_hparams`) con la scelta. Deviazione D4x: «variante del canale dei nomi scelta su dev con un criterio diverso da `ConstrainedTprCriterion`», con ADR-021.

**Criteri di accettazione.**
- Ogni punto dell'ablazione ha celle complete (nessuna cella mancante) e le tabelle di §6.6 (T5.x) si producono dai soli artefatti.
- La scelta è riproducibile: rilanciando lo script si ottiene la stessa configurazione.

**Ivan:** lanci; chiede al prof il limite di AUROC (§7, punto A) **prima** di P5.3. **Claude Code:** griglia, script, tabelle.

---

### P6 — Congelamento, fase 0 sul test, attacchi, metriche, report (5 giorni, tempi macchina a parte)

**Passi.**
1. Ivan: `scripts/freeze_method.py multimark` e `mcss` (log `P6_freeze_<metodo>.txt`).
2. Fase 0 su L1 test e L2 test: `watermark`, `execute`, `detect`, `metrics` (soglie L1L2).
3. Attacchi su L1 test (tutti quelli di SPEC §12 applicabili a Python più T1.6 e T2.5), poi L2 test e L3 (ClassEval, CodeSearchNet) secondo le catene di `chains.py` (aggiungere i passi dei due metodi come proprietario `ivan`). T2.2 e T3.1 richiedono GPU: stima dei costi con `scripts/estimate_closing_cost.py` esteso **prima** del lancio.
4. `metrics`, `metrics_imperceptibility`, `report`.

**Criteri di accettazione.** Tutte le celle di test previste da §6.5 complete; `report.py` rigenera tabelle e figure di §6.6 con un comando; nessuna soglia ricalibrata dopo il congelamento (controllo sha256 di `metrics`).

**Ivan:** tutti i lanci. **Claude Code:** passi delle catene, estensione degli script di controllo (`check_test.py`, `check_attacks.py`) ai due metodi, lettura dei log e tabella dei risultati per la tesi.

---

### P7 — Facoltativi, in quest'ordine (solo se P6 è chiusa entro il 21 dicembre)

1. Attacco «rinomina della funzione d'ingresso» (`T1.7`, §7 punto H).
2. T2.1 per singolo canale: punti `points` con `forced_types` (estensione di `RefactorAttack.apply_types(forced=…)`).
3. Prova di aggiunta/rimozione di un sito (script di sviluppo, non attacco).
4. Canali nuovi dalle trasformazioni irrobustite da Simone (P8), uno alla volta, con i tre controlli di §3.3.2 e la flip rate.
5. Voto pesato con cancellazioni come punto dell'ablazione.
6. Esperimento piccolo sul codice umano fuori benchmark (§0.2): marcatura delle canoniche di L1 dev con `multimark`, rilevazione e Pass@1, solo come script `scripts/human_code_experiment.py` del benchmark.
7. Integrazione di Zottarelli come metodo.

---

### P8 — Trasformazioni di Zottarelli: analisi e riuso delle versioni di Simone (0,5 giorni di analisi; integrazione in P7.4)

Decisione di Ivan (13 novembre): le trasformazioni di Zottarelli **non si riscrivono**. Simone, per la sua tesi, le sta irrobustendo (controlli sui tipi, condizioni di applicabilità): se un canale nuovo serve, si prende la **sua** versione. Il repository di Zottarelli (`TODO(ivan)`: percorso) si legge solo per scegliere quali trasformazioni chiedere.

1. **Analisi** (nella sessione del repository `multimark`, appena c'è il percorso): per T1–T39 (tesi pp. 50–57 e tabella di §5.3.6, pp. 112–113) elencare file, classe `CSTTransformer`, condizioni, flip rate per attacco. Giudicare candidata una trasformazione se: (a) le due forme sono riconoscibili sull'`ast`; (b) non dipende da spazi, a capo o commenti (T40–T45 escluse); (c) non ordina operandi per nome o hash (T46–T49 escluse); (d) compare con frequenza utile nell'inventario di P0 sul codice corto. Uscita: `docs/zottarelli_candidates.md` con, per ogni candidata, frequenza attesa e che cosa manca (inverso, condizione sui tipi).
2. **Da Simone** (le sue versioni lavorano sull'`ast`, senza LibCST, e fanno solo l'andata): si prendono il riconoscimento della forma e la condizione di applicabilità (controlli sui tipi), che sono già nel formato del lettore di §3.1. Il **ritorno** e la **scrittura con LibCST** in entrambe le direzioni (§3.3.3) li scrive Claude Code: senza inverso una trasformazione non è un canale. Se Simone scrive il codice con `ast.unparse`, la sua scrittura non si riusa (perde commenti e formattazione).
3. **Punto di controllo**: all'inizio di P7 Claude Code chiede a Ivan se le trasformazioni di Simone sono pronte; se sì si integrano, se no si prosegue senza (nessun canale di Zottarelli viene riscritto da zero).
4. **Integrazione** (P7, punto 4), un canale alla volta, con i tre controlli di §3.3.2 e la flip rate: il canale entra solo come punto dell'ablazione, mai nella configurazione di base già congelata.
5. **Provenienza**: ogni trasformazione presa dal repository di Simone (o, se mancasse, da quello di Zottarelli) va annotata in `PROVENANCE.md` con repository, commit, file d'origine, classe/funzione, data, modifiche fatte; in testa al file copiato il commento `# Origine: <repo>@<commit>:<file>::<classe>; modifiche: …`. Nella tesi la fonte si cita nel capitolo 4.
6. Candidate attese dalla tesi di Zottarelli (da confermare con l'inventario): T39 `method_call_to_type_call`, T38 `range_len_to_enumerate`, T36 `split_chained_comparison`, T16 `remove_unnecessary_else`, T9 `merge_else_if_into_elif`, T17 `merge_nested_ifs`, T7 `square_identity`, T2 `remove_redundant_slice_index`, T31 `identity_comprehension`.

---

## 3. Specifiche esatte di `multimark` (identiche in inserimento e rilevazione)

Notazione: `K` chiave intera del benchmark (31 bit), `B` lunghezza della parola di codice, `cw` parola di codice, `m` messaggio.

### 3.1 Lettura del codice

- Parser di lettura: modulo `ast` della stdlib (`ast.parse(code, type_comments=False)`). Tutto ciò che decide **quali** siti esistono e **che valore** hanno si calcola sull'`ast`; spazi, a capo, commenti, parentesi ridondanti non esistono per il lettore.
- Se `ast.parse` fallisce: inserimento `FAILED` (motivo `syntax_error`), rilevazione `FAILED`.
- Le docstring sono nodi `Expr(Constant(str))` in prima posizione: non contengono siti (regola: un nodo dentro una stringa non è mai un sito; vale per costruzione).

### 3.2 Funzioni e identificatore di funzione

- `function_of(node)`: la **più esterna** `FunctionDef`/`AsyncFunctionDef` che contiene il nodo (una funzione annidata appartiene alla sua funzione esterna; un metodo appartiene a sé stesso, la classe non conta). Se nessuna: funzione fittizia `MODULE`.
- `fid(function) = (name, n_params)` con `name = function.name` e `n_params = len(posonlyargs) + len(args) + len(kwonlyargs)`; per `MODULE`: `("", 0)`. Il nome della classe **non** entra (un metodo estratto dalla classe conserva il suo `fid`).
- Visita: `ast.walk` **non** si usa (ordine non garantito per i nostri scopi); si usa una visita in profondità esplicita (`iter_child_nodes`, pre-ordine), identica in inserimento e rilevazione.

### 3.3 Canali strutturali

#### 3.3.1 Definizioni (8 canali, numerazione di MCSS Tabella 2, p. 5)

Ogni canale definisce: il **sito** (nodo `ast` radice), la **forma 0** e la **forma 1**, le **condizioni** (se non valgono, il nodo non è un sito, in entrambe le forme). `kind(e)` è la classe sintattica di un operando: `Constant`=0, `Name`=1, `Attribute`=2, `Subscript`=3, `Call`=4, `BinOp`/`UnaryOp`=5, altro=6. «Puro» = non contiene `Call`, `Await`, `Yield`, `NamedExpr`, comprehension.

| # | Canale | Sito (nodo) | Forma 0 | Forma 1 | Condizioni |
|---|---|---|---|---|---|
| 1 | `aug_assign` | `Assign(targets=[Name x], value=BinOp(Name x, op, e))` oppure `AugAssign(Name x, op, e)` | `x = x op e` | `x op= e` | `op ∈ {+, -}` e `e` è `Constant` numerico; oppure `op ∈ {/, //, %, **}` e `e` puro. Mai `*`, `|`, `&`, `^`, `<<`, `>>`, `@` (aliasing e tipi). |
| 2 | `compare_dir` | `Compare` con **un solo** operatore in `{<, <=, >, >=}` | operando di `kind` minore a **sinistra** | operando di `kind` minore a **destra** (operatore specchiato) | `kind(sx) ≠ kind(dx)`; al più uno dei due operandi non puro; nessuno dei due è `Compare`. |
| 3 | `equality_dir` | `Compare` con un solo operatore in `{==, !=}` | come 2 | come 2 | come 2; esclusi i confronti con `None`, `True`, `False` (sono del canale 8 o non sono siti). |
| 4 | `list_comp` | coppia di istruzioni consecutive `L = []` ; `for x in it: L.append(expr)` (corpo di una sola istruzione, nessun `else`) **oppure** `L = [expr for x in it]` (una sola clausola, nessun `if`) | ciclo con `append` | comprehension | `L` e `x` sono `Name`; `x` non compare in `it`; `L` non compare in `expr` né in `it`; `x` **non è letto dopo il ciclo** nella stessa funzione (in Python 3 la variabile della comprehension non resta definita); `expr` e `it` puri rispetto a `L`. |
| 5 | `ternary` | `If(test, body=[Assign(Name x, a)], orelse=[Assign(Name x, b)])` **oppure** `Assign(Name x, IfExp(test, a, b))` | `if/else` | `x = a if test else b` | `a`, `b` puri; nessun `elif`; stesso `x`. |
| 6 | `operand_order` | `BinOp(l, op, r)` con `op ∈ {+, *}` | `Constant` numerico a **destra** | `Constant` numerico a **sinistra** | esattamente uno dei due operandi è `Constant` numerico (`int`/`float`, non `bool`, non complesso) e l'altro ha `kind ∈ {1, 2, 3}`; il nodo non è figlio di un altro `BinOp` con lo stesso operatore (evita `a + 1 + 2` ambigui). |
| 7 | `empty_coll` | `List([])` o `Call(Name list, [])`; `Dict({})` o `Call(Name dict, [])` | letterale `[]`, `{}` | `list()`, `dict()` | `list`/`dict` non ridefiniti nel modulo o nella funzione (nessun binding con quel nome). |
| 8 | `none_check` | `Compare(x, [Eq\|NotEq\|Is\|IsNot], [Constant None])` | `x is None` / `x is not None` | `x == None` / `x != None` | `x` puro. (Forma 0 = PEP 8; la forma 1 è una violazione E711: visibile, come in MCSS. Resta per fedeltà; esclusione valutata in §7 punto D.) |

#### 3.3.1b **[v1.2]** Canali nuovi 9–14 (solo `multimark`, `channels=extended`; `mcss` usa 1–8)

Scelti da `P0_candidates.txt` con tre filtri, nell'ordine: (1) le due forme hanno **lo stesso comportamento per qualunque tipo** degli operandi, oppure una guardia sintattica lo garantisce; (2) le due forme sono distinguibili sull'`ast`; (3) frequenza utile sul codice corto (`no_overlap` ≥ 25 su L1 oppure forma 0 presente in ≥ 10% dei campioni L2/ClassEval). Numerazione per frequenza decrescente su L1; la regola «vince il canale con numero minore» di §3.3.2 fa sì che i canali di MCSS prevalgano sempre sui nuovi.

| # | Canale | Sito (nodo) | Forma 0 | Forma 1 | Condizioni |
|---|---|---|---|---|---|
| 9 | `range_zero` | `Call(Name range, args)` con `len(args) ∈ {1, 2}`, nessun keyword | `range(0, n)` | `range(n)` | forma 0 solo se `args[0]` è `Constant` intero 0; con 2 argomenti e `args[0]` diverso da 0 il nodo **non** è un sito; `range` non ridefinito nel modulo né nella funzione. `range(0, n, s)` (3 argomenti) non è un sito. |
| 10 | `slice_lower` | `Subscript(value, Slice(lower, upper, step=None))` | `a[0:n]`, `a[0:]` | `a[:n]`, `a[:]` | forma 0 se `lower` è `Constant` intero 0, forma 1 se `lower` è `None`; altrimenti non è un sito. `upper` qualsiasi (resta com'è). La variante `a[i:len(a)]` ↔ `a[i:]` **non** si usa (frequenza 0–6 nell'inventario). |
| 11 | `else_return` | `If` senza `elif` | `if c: …; return X` / `else: Y…` | `if c: …; return X` seguito da `Y…` nello stesso blocco | il corpo dell'`if` termina con `Return`, `Raise`, `Continue` o `Break`; forma 0: `orelse` non vuoto, `orelse[0]` **non** è un `If` (esclude `elif` e `else: if`) e l'`If` è l'**ultima** istruzione del blocco (così 0→1→0 torna identico, MD15–17); forma 1: `orelse` vuoto, l'`If` **non** è l'ultima istruzione del blocco e l'istruzione successiva **non** è un `If`. Scrittura 0→1: le istruzioni di `orelse` seguono l'`if` nello stesso blocco; 1→0: tutte le istruzioni successive nel blocco entrano in `else`. Il nodo `If` è lo stesso in entrambe le forme (rango invariato); le istruzioni spostate conservano l'ordine di visita. |
| 12 | `nested_if` | `If` senza `orelse` | `if a: if b: corpo` | `if a and b: corpo` | non è un sito se nell'altra forma sarebbe un sito `else_return`; forma 0: il corpo è **un solo** `If` senza `orelse`, il cui corpo **non** è a sua volta un solo `If` (catene di tre o più `if` non sono siti); forma 1: `test` è `BoolOp(And)` e il corpo **non** è un solo `If`. In entrambe le forme l'`If` del sito **non** è l'unica istruzione del corpo di un altro `If` senza `orelse`. Scrittura 0→1: `test = BoolOp(And, flatten(a) + flatten(b))`; 1→0: primo operando fuori, gli altri nell'`if` interno (`if v0: if v1 and … : corpo`). Il cortocircuito di `and` rende le due forme identiche per qualunque tipo. |
| 13 | `square` | `BinOp(Mult, x, x)` oppure `BinOp(Pow, x, Constant 2)` | `x * x` | `x ** 2` | `x` è `Name` o `Attribute` (puro, valutato una volta sola); le due occorrenze di `x` hanno lo stesso `ast.dump`; il `BinOp` non è figlio di un altro `BinOp(Mult)` (evita `a * x * x`) né il lato destro di `x = x * x` (che in forma 1 diventerebbe un sito `aug_assign`). Caso limite da testare: `float` (`pow(x, 2.0)` e `x*x` coincidono in CPython su glibc; si misura e si riporta). |
| 14 | `return_none` | `Return` | `return None` | `return` | `value` è `Constant None` (forma 0) o `None` (forma 1); nessuna condizione. |
| 15 | `str_method` (**facoltativo**, fuori dalla base finché la decisione P di §7 è aperta) | `Call(Attribute(recv, m), args)` con `m` metodo di `str` | `recv.m(args)` | `str.m(recv, args)` | guardia sul tipo: `recv` è `Constant` stringa, `JoinedStr`, o `Call` a `input`/`str`/`repr`/`format` non ridefiniti; `str` non ridefinito. Forma 1 mai osservata nell'inventario: visibilità alta, si decide con i classificatori di impercettibilità. |

Esclusi e perché (da riportare in T4.2): `range_len` (`enumerate` su iterabili non indicizzabili, e introduce un nome nuovo che interferisce con il canale dei nomi); `not_eq` (`__ne__` può non essere la negazione di `__eq__`; stesso nodo di `equality_dir`); `len_test`, `empty_str`, `bool_cmp` (verità ≠ confronto per tipi diversi da contenitori/bool); `bool_return` (il tipo di ritorno cambia se `c` non è `bool`); `elif` (stesso `ast`); `or_eq` (`in` usa l'identità prima dell'uguaglianza: `nan`); `identity_comp` (crea o distrugge siti di `list_comp`; stile sconsigliato); `sorted_rev` (ordine degli elementi uguali diverso: stabilità); `max_ternary` (pareggi e `NaN`); `str_build`, `while_break`, `const_pow`, `get_none` (frequenza nulla o scrittura non deterministica).

**2D, indipendenza dai nomi:** nei canali 2, 3, 6 la forma canonica dipende solo da `kind`, mai dal testo dei nomi. Se `kind(sx) = kind(dx)` il nodo **non è un sito**. Questo è una deviazione da MCSS (p. 5: «commutative operands are sorted by type, and equality operands are ordered by complexity», con pareggi non specificati); in `mcss` si usa invece la regola di §4.2.

#### 3.3.2 Controlli per ammettere un canale (anche quelli futuri)

1. Le due forme sono riconoscibili dall'`ast` e la lettura è deterministica.
2. Cambiare forma non cambia il comportamento: test con esecuzione (P1) e Pass@1 su L1 dev (P2).
3. Nessuna interferenza: la scrittura di un sito non crea né distrugge siti di altri canali né dello stesso canale. Regola di costruzione: un nodo `ast` appartiene al più a un sito; in caso di sovrapposizione (es. `x = x + 1` è sito 1; il suo `BinOp` interno **non** è sito 6) vince il canale con numero minore. Test: per ogni frammento, `sites(embed(code)) == sites(code)` come insiemi di `(fid, canale, rango)`.

#### 3.3.3 Scrittura con LibCST

- Il codice si analizza con `libcst.parse_module`; `MetadataWrapper` con `PositionProvider`. Ogni sito `ast` porta `(lineno, col_offset)` del nodo radice; il nodo CST corrispondente è quello dello stesso tipo la cui posizione d'inizio coincide (per `list_comp` e `ternary`, la posizione della **prima istruzione** della coppia).
- Un `CSTTransformer` per canale scrive la forma richiesta conservando commenti e a capo circostanti (`leading_lines` del primo nodo).
- Dopo la scrittura dell'intero file: `ast.parse` e rilettura completa; ogni sito il cui valore letto ≠ valore richiesto viene annullato (riscrittura del solo sito nella forma originale) e contato in `extra["skipped_sites"]`; se dopo l'annullamento la rilettura non coincide ancora, inserimento `FAILED` con motivo `rewrite_mismatch`.
- Non si usa `ast.unparse` (deviazione da MCSS, che lo usa: p. 8, «Python's ast.unparse always produces valid code»).

### 3.4 Rango e legame sito → bit (2A)

Per ogni sito `s` di canale `c` nella funzione `f`:

```
rank(s) = indice di s fra i siti di canale c della funzione f, in ordine di visita (0-based)
off(f, c) = prf_int(K, "offset", name(f), str(n_params(f)), c) mod B
phi(s) = (off(f, c) + rank(s)) mod B
```

- Il canale dei nomi è il canale `"names"` con la sua coppia `(off, rank)` (rango per ordine della **prima** occorrenza di binding della variabile nella funzione).
- Il codice fuori da ogni funzione ha `f = MODULE`, `name="" , n_params=0`.
- Conseguenze volute: estrarre, spostare, aggiungere o togliere funzioni non cambia `phi` dei siti delle altre funzioni; aggiungere un sito di canale `c` in una funzione sposta solo i siti di `c` che lo seguono in quella funzione.
- Variante per l'ablazione (§6.3): `linking=positional` (ordine di MCSS, §4.2) e `linking=function_single_run` (un solo `off(f)` e rango su tutti i canali della funzione).

### 3.5 Maschera con la chiave (1B) e PRF

```
prf(K, *parts) = HMAC_SHA256(key = K.to_bytes(8, "big"), msg = "|".join(parts).encode("utf-8"))
prf_int(...)   = int.from_bytes(prf(...)[:8], "big")
prf_bit(...)   = prf(...)[-1] & 1
mask(s)        = prf_bit(K, "mask", name(f), str(n_params(f)), c, str(rank(s)))      # canali strutturali
```

- Inserimento: il sito strutturale `s` viene scritto nella forma `cw[phi(s)] XOR mask(s)`.
- Rilevazione: valore letto `b(s)` ∈ {0, 1, null}; voto `v(s) = b(s) XOR mask(s)` se `b(s) ≠ null`.
- I siti del canale dei nomi **non** hanno maschera: il loro valore è già `prf_bit(K, "name", norm(nome))` (§3.6).
- Ablazione: `mask=off` (MCSS puro).

### 3.6 Canale dei nomi

#### 3.6.1 Quali variabili sono siti (regola comune a V1, V1b, V2)

Un sito è un nome `n` che, nella funzione `f`: (a) ha almeno un binding come variabile locale (`Assign`, `AugAssign`, `AnnAssign`, target di `For`, `With ... as`, `comprehension` **esclusa**, `NamedExpr`); (b) non è parametro di `f` (`names.include_params=false` per `multimark`, decisione C chiusa il 13 novembre: esclusi; `true` per `mcss`); (c) `len(n) ≥ 2` e `n` non è `_` né inizia per `_`; (d) non è dichiarato `global`/`nonlocal`; (e) non compare come argomento con nome in una chiamata (`g(n=…)`) né come attributo (`.n`); (f) `f` non usa `locals`, `vars`, `eval`, `exec`; (g) `n` non è `self`, `cls`.

**[v1.2] Variabili di modulo (`names.module_level`).** Con `names.module_level=true` anche i nomi legati a livello di modulo (`f = MODULE`, `fid = ("", 0)`) sono siti, con le stesse regole (c)–(g) più: (h) `n` non compare in alcuna istruzione `global` del modulo, non è in `__all__`, non è il nome di una funzione, classe o `import`; (i) il modulo non usa `locals`, `vars`, `eval`, `exec`, `globals` a livello di modulo. La rinomina copre tutte le occorrenze nello scope del modulo e le letture dentro le funzioni (LibCST `ScopeProvider`). Valore: `true` per `mcss` (il paper parla di «each multi-word variable» senza limitarsi alle funzioni, p. 5, e la Tabella 3 non è spiegabile altrimenti su CodeNet, §P0 esito); per `multimark` si decide con l'inventario di P1 passo 0 (decisione O di §7); fino ad allora `false`.

T1.4 del benchmark (`attacks/t1/rename.py`) rinomina un insieme **più ampio** (anche parametri e nomi di una lettera): i siti dei nomi sono un sottoinsieme dei suoi candidati, quindi T1.4 con `r = 1,0` li colpisce tutti. T1.6 (§5.5) usa invece esattamente la regola di questa sezione. Da verificare nel benchmark (P2): se T1.4 tocca anche i nomi di modulo.

#### 3.6.2 Normalizzazione del nome

`norm(n)`: si spezza `n` nei suoi segmenti (su `_` e sui cambi minuscolo→maiuscolo e sulle sequenze di maiuscole seguite da minuscola), si mette tutto in minuscolo, si riunisce con `_`. Esempi: `totalCount`→`total_count`, `TotalCount`→`total_count`, `TOTAL_COUNT`→`total_count`, `total_count`→`total_count`, `HTTPResponse`→`http_response`.

#### 3.6.3 Varianti

| Variante | Bit per sito | Lettura `b(s)` | Scrittura |
|---|---|---|---|
| V0 | 0 | nessun sito dei nomi | nessuna |
| V1 (MCSS) | 2 | stile ∈ {snake 00, camel 01, Pascal 10, ALL_CAPS 11} del nome; nomi di una parola: estensione con suffisso (§4.3), altrimenti `null` | rinomina nello stile dei 2 bit richiesti |
| V1b | 1 | snake 0, camel 1; altri stili `null` | rinomina |
| V2 | 1 | `prf_bit(K, "name", norm(n))` | se il bit del nome originale è quello richiesto: nulla; altrimenti primo candidato valido con il bit giusto (§3.6.4); se nessuno: nome invariato (voto sbagliato, contato) |
| V2b | 1 | come V2, ma `phi(s) = prf_int(K, "name-slot", norm(n)) mod B` (indirizzo dal nome, nessun rango) | come V2, scegliendo il candidato per cui `cw[phi] == prf_bit` |

Con V1 ogni sito occupa 2 posizioni consecutive di `phi` (come MCSS, Alg. 1 riga 7, p. 5).

#### 3.6.4 Candidati (V2, V2b)

- Interfaccia `Proposer.propose(code, function_name, var_name, k=8) -> list[str]`, deterministica.
- `StaticProposer` (ripiego, nessun modello): candidati = (1) sinonimi dal dizionario fisso `multimark/data/name_synonyms.json` (compilato a mano da Claude Code, ≥ 300 voci comuni del codice: `count`→`counter, total, n_items, …`), (2) composizioni `norm(n) + "_" + suffisso` con suffissi `["value", "val", "item", "list", "count", "idx", "tmp", "res"]`, (3) `norm(n)` con prefissi `["cur_", "new_", "the_"]`; in quest'ordine.
- `NeuralProposer`: prompt chat al modello: sistema «You rename one variable in Python code. Answer with a JSON list of 8 alternative snake_case names, most natural first, no explanations.»; utente: il codice della funzione con la variabile evidenziata (`<<var_name>>`) e la riga «Variable to rename: var_name». Greedy, `max_new_tokens=64`; si prendono solo gli identificatori validi; se la lista ha meno di 3 voci, si completa con `StaticProposer`.
- Validità di un candidato: identificatore Python, snake_case, `len ≥ 2`, non parola riservata, non builtin (`builtins.__dict__`), **[v1.2.1]** non in conflitto nello **scope** della variabile (per una variabile locale: nomi legati o letti nella funzione, nei suoi scope racchiudenti e i nomi di modulo che la funzione legge; per una variabile di modulo: tutti i nomi del modulo; due funzioni diverse possono quindi ricevere lo stesso nome nuovo), non uguale al nome originale, non termina con `_`. La stessa regola vale per V1 e V1b (MD16).
- Rinomina: tutte le occorrenze del binding nella funzione (LibCST `ScopeProvider`, come T1.4).

### 3.7 Messaggio e alfabeto

- `message_bits = 24` (`multimark` e `mcss`).
- Nel benchmark il messaggio atteso è una stringa di `message_bits` cifre `0/1`: `format(derive_seed(global_seed, "<metodo>-msg", problem_key, language, model_id, sample_index) % 2**message_bits, "0{message_bits}b")`, con `sample_index` reso come stringa (`"None"` per i negativi senza indice), come `mcgmark.py::message_bits`.
- Alfabeto a 6 bit di MCSS (a–z 0–25, A–Z 26–51, 0–9 52–61, `_` 62, riempimento 63; p. 4–5) nel dimostratore per convertire «gpt4» in bit; il benchmark lavora direttamente in bit.

### 3.8 Codice compatto

- Codice sistematico lineare su GF(2): `cw = m ∥ p`, `p = m · P` con `P` matrice `message_bits × 4t` a elementi casuali generati da `random.Random(int.from_bytes(sha256(b"posthoc-compact-code-v1").digest()[:8], "big"))`, fissata nel codice e nel test (valore di controllo del suo hash). `t = 2` → `B = message_bits + 8`.
- Decodifica per sole cancellazioni (Teorema 5.2 di MCSS, p. 7): i bit decisi dal voto formano il vettore noto; per le posizioni cancellate si risolve `H · cw = 0` con eliminazione di Gauss su GF(2) (`H = [Pᵀ | I]`); soluzione unica → messaggio; nessuna soluzione o più soluzioni → `decode_status ∈ {inconsistent, ambiguous}`. Nessuna correzione di errori (non prevista dal codice compatto del paper).
- Deviazione dichiarata: la matrice del paper non è nota (seme SHA-256 non pubblicato, p. 3); la nostra ha la stessa costruzione e un seme nostro.
- **[v1.2.2] Matrice per profilo (MD18).** `mcss`: matrice casuale come sopra (fedeltà: il paper la dichiara «random by construction», p. 3). `multimark`: `code.matrix = dmin4`, matrice con **distanza minima 4** (il massimo possibile per un codice binario [32, 24]: d = 5 violerebbe il limite di Hamming, 1 + 32 + 496 = 529 > 2^8). Costruzione (codice di Hamming esteso accorciato): le 24 righe di `P` sono 24 vettori di 8 bit **distinti, di peso dispari e ≥ 3** (ce ne sono 120), estratti con `random.Random(int.from_bytes(sha256(b"multimark-compact-code-dmin4-v1").digest()[:8], "big")).sample(...)` dalla lista ordinata; valore di controllo dell'hash nel test. Garanzie, da fissare con test: con f ≤ 3 cancellazioni la decodifica riesce sempre; con e + f ≤ 3 (e = voti sbagliati, f = cancellazioni, in bit) non esce mai un messaggio sbagliato; con e = 0 non esce mai un messaggio sbagliato (vale per entrambe le matrici). Oltre questi limiti si riportano i tassi.
- **[v1.2.2] Controllo prima di adottare `dmin4`:** per entrambe le matrici, calcolo esatto (enumerazione per f ≤ 5, 10⁶ campioni per 6 ≤ f ≤ 8) della probabilità di decodifica unica con f cancellazioni scelte a caso e della probabilità di messaggio sbagliato con e = 1 ed f cancellazioni. `dmin4` diventa la base di `multimark` se a f = 4 e f = 5 la probabilità di decodifica unica non è inferiore di oltre 0,02 a quella della matrice casuale; altrimenti si tiene la casuale e `dmin4` resta un punto dell'ablazione. Tabella nel log `P1_codec_matrices.txt` e nella tesi (T4.3).

### 3.9 Inserimento (pseudocodice)

```
def embed(code, m_bits, K, cfg):
    tree = ast.parse(code)                       # FAILED se errore di sintassi
    funcs = functions(tree)                      # §3.2
    cw = encode(m_bits, t=cfg.t)                 # §3.8, lunghezza B
    sites = []                                   # strutturali, in ordine di visita
    for f in funcs + [MODULE]:
        for c in CHANNELS:                       # 1..8, ordine fisso
            for rank, s in enumerate(sites_of(f, c, tree)):
                sites.append(Site(f, c, rank, s))
    names = name_sites(tree, funcs, cfg.names)   # §3.6.1, con rango per funzione
    N = len(sites) + bits_of(names, cfg.names)   # V1: 2 per nome, V2: 1
    plan = {}
    for s in sites:
        target = cw[phi(s)] ^ mask(s)            # §3.4, §3.5
        plan[s] = target
    renames = {}
    for ns in names:                             # §3.6.3
        want = bits_wanted(cw, ns)               # 1 bit (V2) o 2 bit (V1)
        new_name = choose_name(ns, want, cfg)    # None se il nome originale va già bene
        if new_name: renames[ns] = new_name
    code2 = rewrite(code, plan, renames)         # §3.3.3 (LibCST), con annullamento dei siti incoerenti
    status = OK if N >= B else (PARTIAL if N > 0 else FAILED)
    return code2, status, extra(n_sites=N, per_channel_counts, skipped, n_renamed, …)
```

**Stati** (definizione operativa per l'audit): `OK` se `N ≥ B`; `PARTIAL` se `0 < N < B`; `FAILED` se `N = 0`, errore di sintassi, `rewrite_mismatch` o eccezione. `PARTIAL` è un positivo a tutti gli effetti (I2 esclude solo `FAILED`): è esattamente il caso del codice corto che `multimark` vuole coprire.

### 3.10 Rilevazione (pseudocodice)

```
def detect(code, m_expected, K, cfg, registry_sizes=(1, 16, 1024)):
    tree = ast.parse(code)                       # FAILED se errore
    sites, names = same enumeration as embed     # identica per costruzione
    votes = []                                   # (bit_index, value, weight, site_id)
    for s in sites:
        b = read(s)                              # 0 / 1 / None
        if b is not None: votes.append((phi(s), b ^ mask(s), 1.0, id(s)))
    for ns in names:
        for (idx, val) in read_name(ns):         # V2: uno; V1: due
            votes.append((idx, val, 1.0, id(ns)))
    N = len(votes)
    if N == 0: return FAILED("no_sites")
    # --- modo confronto (1A): punteggio principale e secondari
    registry = {1: [m_expected], 16: [m_expected] + decoys(15), 1024: [m_expected] + decoys(1023)}
    scores = {}
    for n_reg, cands in registry.items():
        best = max(cands, key=lambda m: agreement(votes, encode(m)))
        A = agreement(votes, encode(best))       # somma dei pesi dei voti concordi
        scores[n_reg] = (-log10(binom_tail(N, A)), best)
    # --- modo decodifica (aperto): bits_correct e message_accuracy
    tally = majority(votes, B)                   # per bit: 0, 1 o ERASURE (pareggio o nessun voto)
    decoded, dstatus = decode_erasures(tally, t)  # §3.8
    bits_correct = count(i for i in range(message_bits)
                         if decided(i) and decoded_or_tally(i) == m_expected[i])
    return OK, score=scores[1][0], extra = {...}  # §3.10.4
```

#### 3.10.1 Esche del registro

`decoys(k)`: `k` messaggi di `message_bits` bit da `derive_seed(global_seed, "<metodo>-registry", str(j)) % 2**message_bits` per `j = 1..k`, uguali per tutti i campioni; se un'esca coincide con `m_expected` si sostituisce con `j + 10**6`. Il `global_seed` arriva allo shim negli `hparams` nativi (`registry_seed`).

#### 3.10.2 Punteggio

- `agreement(votes, cw) = Σ w · [v == cw[idx]]`; con pesi uniformi è un intero `A ∈ [0, N]`.
- `score = -log10(P[Bin(N, 1/2) ≥ A])` calcolato in modo esatto con `math.comb` (N ≤ qualche migliaio); con pesi non uniformi (ablazione) si usa l'approssimazione normale `z = (2A − W)/√W` e `score = -log10(Φ̄(z))`.
- **Punteggio principale** = quello di `N_reg = 1`. **Secondari**: `score_nreg16`, `score_nreg1024` (massimo sulle esche), `score_decode` = `bits_correct / message_bits` (per confronto con il punteggio di MCGMark, che è un conteggio di bit).
- `native_decision` (diagnostica): `P[Bin(N,1/2) ≥ A] · N_reg ≤ 0,01` per `N_reg = 1`.

#### 3.10.3 Regola di decisione nel benchmark

`detected = status == OK and embed_status != FAILED and score ≥ τ`, con `τ` calibrata all'1% sui negativi umani di sviluppo (`metrics/calibration.py`). Il p-value analitico è un controllo da riportare nella tesi, non la soglia. Attesa analitica (α = 0,01, f = frazione di voti alterati), siti minimi: `N_reg = 1`: 7 (f=0), 11 (10%), 17 (20%); `N_reg = 16`: 11, 19, 31; `N_reg = 1024`: 17, 25, 51.

#### 3.10.4 Campi di `extra` (tutti obbligatori)

`n_sites`, `n_votes`, `n_sites_by_channel` (dict), `n_name_sites`, `agreement`, `score_nreg16`, `score_nreg1024`, `score_decode`, `best_nreg16`, `best_nreg1024` (messaggi scelti), `decoded_message_open` (stringa o `null`), `decode_status`, `bits_correct` (intero), `n_erasures`, `sites` (lista di `[fid_name, n_params, channel, rank, value_read, vote]`, con `value_read` `null` se non leggibile), `skipped_sites`, `library_version`.

`decoded_message` del `WorkerResult` = `decoded_message_open` (decodifica aperta): così `message_accuracy` misura il recupero in insieme aperto, confrontabile con MCGMark.

### 3.11 Opzioni di configurazione (nomi del protocollo → nativi, 1:1)

| Chiave | Valori | Base `multimark` | `mcss` |
|---|---|---|---|
| `t` | {0, 2, 4, 8} | 2 | 2 |
| `message_bits` | fisso dall'adapter | 24 | 24 |
| `linking` | `function_channel`, `function_single_run`, `positional` | `function_channel` | `positional` |
| `mask` | `on`, `off` | `on` | `off` |
| `canonical` | `kind` (2D), `paper` | `kind` | `paper` |
| `names.variant` | `V0`, `V1`, `V1b`, `V2`, `V2b` | `V2` | `V1` |
| `names.proposer` | `static`, `neural` | `neural` (P3; `static` fino a P2) | — |
| `names.include_params` | bool | `false` | `true` (non specificato dal paper: §4.2 punto 8) |
| `channels` **[v1.2]** | `mcss8`, `extended`, `extended+str` | `extended` | `mcss8` |
| `names.module_level` **[v1.2]** | bool | decisione O (§7); `false` fino ad allora | `true` |
| `code.matrix` **[v1.2.2]** | `random`, `dmin4` | `dmin4` (se passa il controllo di §3.8) | `random` |
| `voting` | `simple`, `weighted`, `weighted_erasure` | `simple` | `simple` |
| `channel_weights` | file JSON (solo `weighted*`) | — | — |

Il `config_hash` dipende da tutte le chiavi tranne `registry_seed` (è il `global_seed`, costante).

---

## 4. Reimplementazione di MCSS (`mcss`)

### 4.1 Cosa si riproduce fedelmente

- Alfabeto a 6 bit, 24 bit di messaggio, codice compatto con 4t bit di controllo, `B = 24 + 4t` (p. 3, p. 4–5).
- Otto canali della Tabella 2 (p. 5) con il significato delle forme canonica/alternativa.
- Canale dei nomi a 4 stili, 2 bit per variabile, variabili di una parola estese con un suffisso per diventare a più parole, variabili di una lettera escluse (p. 5, passi 1–2).
- Costruzione del pool (p. 5, passi 3–5): normalizzazione dei nomi a `snake_case`, normalizzazione strutturale alla forma canonica, siti in ordine di visita in profondità, **prima tutte le variabili poi i siti strutturali**, variabili con 2 posizioni consecutive.
- Assegnazione φ a cicli completi: per il ciclo `k = i // B`, una permutazione di `{0..B−1}` ottenuta con Fisher-Yates guidato dal flusso pseudo-casuale della chiave; `phi(i) = perm_k[i mod B]` (p. 5, §4.5).
- Rilevazione: voto a maggioranza per bit, parità → cancellazione, decodifica (Alg. 2, p. 6).

### 4.2 Deviazioni dichiarate (tutte in `docs/audit/mcss.md`)

1. **Lettura sull'AST, scrittura con LibCST** al posto di `ast.unparse` (p. 8): i commenti e la formattazione restano; il pool è identico perché la lettura è la stessa.
2. **PRF HMAC-SHA256 al posto dei punti su secp256k1** (p. 5): il flusso che guida Fisher-Yates è `prf_int(K, "fy", str(j))` per `j = 0, 1, …`; stessa sicurezza pratica, nessuna dipendenza da librerie di curve ellittiche. La permutazione dipende da `(K, N, B)` come nell'Alg. 1 (`SpreadSpectrum(K, N, B)`): si genera `ceil(N/B)` permutazioni consumando il flusso in ordine, così il risultato non cambia se cambia N? **No**: si sceglie la lettura più semplice compatibile con il paper, cioè le permutazioni dei cicli `0..k` non dipendono da N (il flusso si consuma in ordine); la dipendenza da N resta solo nel numero di cicli. Da verificare sul codice ufficiale quando esce (§P4.3).
3. **Forme canoniche con pareggio**: «sorted by type» e «ordered by complexity» (p. 5) senza regola per i pareggi. Regola nostra: `kind` come in §3.3.1; a parità di `kind`, ordine lessicografico del testo `ast.unparse` dell'operando (dipende dai nomi: è la fragilità che `multimark` corregge con 2D). Documentata come interpretazione.
4. **Suffissi per i nomi di una parola**: il paper dice «context-inferred suffixes (e.g., n → n_count, s → s_str)» senza regola. Regola nostra: suffisso dal **tipo del primo binding** (`int`/`float` → `_count`/`_val`, `str` → `_str`, `list` → `_list`, `dict` → `_map`, `bool` → `_flag`, altro → `_val`), dedotto dal nodo del valore se letterale o costruttore, altrimenti `_val`. Nomi di una lettera esclusi.
5. **Punteggio per il benchmark**: MCSS non ha un punteggio continuo (restituisce il messaggio o `FAIL`). Per calibrare la soglia all'1% come per tutti (D2) si usa lo stesso punteggio di `multimark` a `N_reg = 1` (concordanza dei voti con il messaggio atteso, senza maschera), e `native_decision` = decodifica riuscita e uguale al messaggio atteso. `message_accuracy` viene dalla decodifica, come nel paper.
6. **Correzioni semantiche** ai canali (condizioni di §3.3.1): il paper dichiara «100% AST validity» (p. 8) ma non test funzionali sui marcati; le nostre condizioni sono più strette (es. `+` solo con letterale numerico) e riducono i siti. Si misura quanti siti si perdono rispetto alla lettura senza condizioni (`inventory_sites.py --no-guards`) e si riporta.
7. **Matrice del codice compatto** nostra (§3.8).
8. **Parametri delle funzioni**: non è detto se MCSS li rinomina. Default `names.include_params=true` per `mcss` (la figura 1 del paper rinomina il parametro `num_val`, p. 2) e `false` per `multimark`.

### 4.3 Canale dei nomi V1 (per `mcss`)

Stili: `snake_case` (00) tutte minuscole con `_`; `camelCase` (01) prima parola minuscola, iniziali maiuscole dopo; `PascalCase` (10); `ALL_CAPS` (11). Lettura: stile riconosciuto solo per nomi con ≥ 2 segmenti (§3.6.2); altrimenti `null` (dopo l'estensione con suffisso in inserimento, i nomi hanno sempre ≥ 2 segmenti; un attaccante che li riaccorcia produce `null`, cioè cancellazioni).

### 4.4 Test di autovalidazione (al posto dell'oracle)

1. Round trip su 500 frammenti sintetici × 100 chiavi (P1).
2. **[v1.2]** Riproduzione della **Tabella 3** (p. 8) in forma di distribuzione: selezione dei file CodeNet Python della fascia 32–39 bit (`n_bits_v1`, profilo `mcss` con `names.module_level=true`, `include_params=true`) dal pool L2, **escludendo** i file con ruolo di test (canoniche o negativi di test) e tenendo al più una sottomissione per problema quando ce ne sono abbastanza; fino a 250 file, minimo utile 100. Se dopo la rilettura con le variabili di modulo i file in fascia sono meno di 100: si allarga a `n_bits_v1 ≥ 32` e, se ancora meno di 100, Ivan chiede alla sessione del benchmark da dove viene il pool (`L2_codenet_pool.jsonl.manifest.json`) e se si possono aggiungere altre sottomissioni Python di CodeNet dei soli problemi di sviluppo. **Criterio di accettazione: media di `n_bits_v1` entro ±10% di 34,6**; le medie di variabili e siti strutturali si **riportano** con lo scostamento da 11,9 e 10,9 ma non sono un criterio, perché dentro una fascia definita sui bit le due componenti si compensano (esito di P0: 7,5 e 18,0 con totale 33,0). Il primo tentativo (18 file, senza variabili di modulo) resta in `P0_mcss_selftest.txt` e nella tesi come risultato intermedio.
3. Riproduzione dell'**andamento della Tabella 5** (p. 8) con `t = 2` sugli stessi file (con meno di 100 file le percentuali si riportano con l'intervallo di Wilson e si accettano solo gli ordinamenti): no-attack 100%; `rename 2` e `rename 4` ≥ 95%; `rename 8` < 10%; fra gli attacchi per canale `operand_order` è il **peggiore** e `none_check` il **migliore**; `rename 16` ≈ 0. Gli attacchi si realizzano con `scripts/mcss_paper_attacks.py` (benchmark) (rinomina casuale di r variabili; inversione di tutti i siti di un canale). Si accettano gli ordinamenti, non i valori esatti.
4. Riproduzione della **Tabella 15** (p. 14): inversione casuale del 10% dei siti sulla fascia 32–39 bit dà recupero < 20% (paper: 9,8%).
5. Confronto con il codice ufficiale, se esce (§P4.3): pool, ordine, valori, messaggi su 50 file; ogni differenza nell'audit.

I risultati vanno in `docs/milestone_logs/P2_mcss_selftest.txt` e nel capitolo 4 (tabella «fedeltà della reimplementazione»).

---

## 5. Integrazione nel benchmark: modifiche alle parti comuni

Ogni voce: un commit `[P<n>] common: …`, un test di retrocompatibilità, un ADR. **Da concordare con Simone**: tutte le voci di questa sezione tranne 5.6–5.8 (script nuovi e report additivo). Le voci 5.1–5.3 cambiano file che le sue catene usano (`detect.py`, `metrics.py`): vanno unite su `main` solo dopo il suo via.

### 5.1 `bits_correct` per metodo — `src/bench/pipeline/stages/detect.py::_bits_correct` (riga 352), ADR-017

- Nuovo metodo `Detector.bits_correct(self, result: WorkerResult) -> int | None` in `methods/base.py`, default: comportamento attuale (`None` se `decoded_message` o `score` è `None`, altrimenti `int(score)`). `_bits_correct(result)` diventa `adapter.bits_correct(result)`. `multimark`/`mcss` lo ridefiniscono leggendo `extra["bits_correct"]`.
- Test: `tests/unit/test_detect_bits_correct_compat.py`: per 1.000 `WorkerResult` casuali con `extra` senza `bits_correct`, nuovo = vecchio.

### 5.2 Lunghezza del messaggio per metodo — `metrics.py` (`MESSAGE_BITS`, riga 78; `_capacity`, 698–718), ADR-017

- `Detector.message_bits: ClassVar[int | None] = None`; `McgmarkAdapter.message_bits = 12`; `_capacity(add, boot, positives, message_bits)` con `message_bits = adapter.message_bits`; `_multibit` resta su `message_for`.
- Nuove metriche in `_capacity`: `message_accuracy_detected` = frazione dei positivi **rilevati** con `bits_correct == message_bits` (`detected` con la soglia della cella; Wilson), `n` = numero di rilevati. Vale anche per MCGMark (misura nuova, additiva).
- Test: `tests/unit/test_metrics_capacity_compat.py`: su una tabella sintetica in stile MCGMark i valori di `message_accuracy`, `bit_accuracy`, `embedding_success_rate` sono identici a quelli calcolati dalla funzione **prima** della modifica (copiare la vecchia funzione nel test come `_capacity_legacy`).

### 5.3 Capacità sotto attacco e attribuzioni sbagliate — `metrics.py::_attacked_metrics` (556–622), ADR-017

- In `_attacked_metrics`, dopo i punteggi secondari: `if self._multibit(method): self._capacity(…)` sugli attaccati (stessa definizione: FAILED → 0 bit).
- `wrong_attribution_rate_<nome>` per ogni secondario `nregK` presente in `adapter.secondary_scores`: frazione dei positivi rilevati con quel punteggio (soglia secondaria della cella) il cui `best_nregK` in `extra` ≠ `expected_message`; Wilson. In celle senza attacco e con attacco. Per i metodi senza `best_nreg*` in `extra` la metrica non si emette (nessun cambiamento per gli altri).
- Test: tabelle sintetiche; per una cella MCGMark attaccata le metriche esistenti non cambiano (confronto riga per riga con il parquet prodotto dal codice attuale su una fixture).

### 5.4 `conditional_preservation` per ogni `CodeEmbedder` — `metrics.py` riga 423, ADR-017

`if method == "acw"` → `if isinstance(self.adapter(method), CodeEmbedder)`. Test: ACW invariato (stessa fixture), `multimark` ottiene la metrica.

### 5.5 Attacchi nuovi, ADR-018

**T1.6 `snake_case`** (`attacks/t1/snake_case.py`): solo Python; candidati come T1.4 (stesse esclusioni, stesso `ScopeProvider`); ogni candidato con `norm(n) ≠ n` viene rinominato in `norm(n)` se `norm(n)` non collide con nomi del modulo, riservati o builtin (altrimenti `norm(n) + "_1"`); `APPLIED` se almeno una rinomina, `UNCHANGED` altrimenti; `attack_detail = {n_candidates, n_renamed}`; nessun parametro (`points: [{}]`). Proprietà: canoniche L1 verdi.

**T2.5 `dilution`** (`attacks/t2/dilution.py`): solo Python, livello di file. Parametri `n ∈ {1, 2, 4}` × `position ∈ {before, after, around}` = 9 celle (**da ridurre con Simone** a `{(1, before), (2, around), (4, around)}` se il costo delle rilevazioni lo richiede). Fonte: `data/function_pools/python.parquet` (fase nuova `function_pools`: funzioni Python di CodeSearchNet **train**, filtri delle raccolte di ADR-012 più: `ast.parse` ok, 3 ≤ righe di codice ≤ 40, nessun `import` dentro, nessun decoratore, non ricorsive, senza `global`; 5.000 funzioni; seed `derive_seed(global_seed, "function_pool", "python")`). Per ogni campione si estraggono `n` funzioni con l'RNG dell'attacco, si rinominano se il nome collide con un nome del modulo (`<nome>_ext<k>`), si inseriscono a livello di modulo: `before` = subito dopo le `import` iniziali e prima della prima definizione; `after` = in coda; `around` = metà (arrotondata per eccesso) prima, il resto dopo. `attack_detail = {n_inserted, names, position, added_loc}`. Il codice vuoto è `NOT_APPLICABLE`. Proprietà: canoniche L1 verdi (le funzioni aggiunte non sono chiamate); determinismo.

Perimetro di lancio proposto: **tutti i metodi Python** (`mcgmark`, `acw`, `promptmark`, `stone`, `mcss`, `multimark`) su L1 test; T2.5 anche su L2 test e ClassEval. Decisione condivisa con Simone (costo: rilevazioni di STONE e PromptMark su CPU, nessuna GPU).

### 5.6 Curva per numero di siti — `src/bench/report.py`, ADR-020

Nuova funzione `capacity_by_sites(store, cfg, out)`: per ogni cella senza attacco e per ogni cella con attacco dei metodi multi-bit, unisce `detection` con `watermarked` (colonna `n_sites`) e con `execution` del genitore; fasce di `n_sites`: `[1–7], [8–12], [13–19], [20–31], [32–55], [56+]` (i confini 13, 20, 32 sono quelli della tabella di §3.10.3 e della fascia D32 di MCSS); per fascia: `n`, `tpr_at_fpr` (soglia congelata), `message_accuracy` (decodifica), `bit_accuracy`, `pass_at_1`, con Wilson. Tabella `tables/capacity_by_sites_<livello>[_<attacco>].csv/.tex`; figura con una curva per metodo (asse x = fascia, y = TPR e, in un secondo pannello, `message_accuracy`). Per MCGMark `n_sites` = posizioni marcate (già salvate). Anche per `loc_to_generate` del problema (`tables/capacity_by_loc_…`). Script `scripts/report_capacity.py` con gli stessi calcoli per i controlli su dev.

### 5.7 FPR per l'identificativo peggiore — `scripts/report_worst_id_fpr.py`

Rilevazione separata (fase `detect` con `hparams.registry_mode=fixed_messages`, **solo su `neg_human` dev**, output sotto `_runs/diagnostics/`, mai usato per calibrare): 66 messaggi fissi = tutti 0, tutti 1, `0101…`, `1010…`, i 24 messaggi con un solo 1, i 24 con un solo 0, 14 casuali con seme fisso; per ciascuno la frazione di negativi con `score ≥ τ` (soglia congelata della cella). Tabella e massimo/minimo con Clopper-Pearson. Per `mcss` e `multimark`.

### 5.8 Flip rate per canale — `scripts/report_flip_rate.py`

Per ogni attacco e canale: fra i siti presenti sia nella rilevazione pulita sia in quella attaccata (stesso `(fid, canale, rango)`), frazione con `vote` diverso; più la frazione di siti **spariti** e **comparsi**. Da `extra["sites"]`. Tabella canale × attacco per metodo e livello; è l'input per `channel_weights` dell'ablazione «voto pesato».

### 5.9 Altro (additivo, nessun ADR)

`configs/config.yaml` (`methods_catalog`), `chains.py` (voci dei due metodi), `scripts/check_test.py`, `check_attacks.py`, `report_metrics.py`, `estimate_closing_cost.py`: estensione ai due metodi senza cambiare i casi esistenti; test: `scripts/*.py` esistenti producono lo stesso output su una fixture.

### 5.10 **[v1.2]** Rilevazione aggregata su k campioni — `scripts/report_aggregated.py` (nessuna modifica alle parti comuni)

Risposta al codice corto: se un campione da 2 siti non basta, quanti campioni dello stesso modello servono? Per `mcss` e `multimark` il punteggio è una funzione di `(agreement A, n_votes N)` salvati in `extra` (§3.10.4), quindi si **somma** su k campioni senza rilanciare nulla: `score_k = -log10 P[Bin(ΣN, 1/2) ≥ ΣA]`. Procedura, solo da tabelle `detection` già calcolate: per `k ∈ {1, 2, 4, 8, 16}`, 1.000 gruppi casuali di k campioni (seme fisso `derive_seed(global_seed, "aggregate", metodo, livello, str(k))`) estratti (a) dai positivi del livello (stesso modello, stesso messaggio: nel benchmark il messaggio dipende dal campione — §3.7 — quindi l'aggregazione si fa **con il registro** `N_reg = 1` sul messaggio atteso di ciascun campione, cioè si sommano le concordanze con il proprio messaggio atteso; per `mcss` vale lo stesso), (b) dai negativi umani di sviluppo per la soglia all'1% su gruppi di k (calibrazione separata per k, sempre su dev), (c) dai negativi umani di **test** per l'FPR. Uscita: `tables/aggregated_<livello>.csv` con `k`, TPR@1%FPR, FPR test, Wilson; anche sulle celle attaccate (T1.4 r = 1,0, T2.1 all). Figura F5.5: TPR contro k, `multimark` e `mcss`, L1 e L2. Per MCGMark non si calcola (il suo punteggio non è additivo per campione): si dichiara. Nessun ADR perché non tocca `src/bench`; lo script va in `scripts/` del benchmark con i suoi test su tabelle sintetiche. Si scrive in P4 (dopo i primi `detection` di L1+L2 dev), si usa su test in P6.

---

## 6. Piano degli esperimenti

Tutto su sviluppo fino a P6. Nessuna cella `split=test` prima del congelamento.

### 6.1 Inventario (P0)
Siti per canale, per funzione e per campione su L1 dev (canoniche, baseline Qwen e DeepSeek), L2 dev, ClassEval: tabella 4.1 della tesi.

### 6.2 Configurazione di base (P2–P4)
`mcss` e `multimark` su L1+L2 dev: inserimento, Pass@1, rilevazione sui tre soggetti, soglie, metriche; curva per numero di siti; FPR per identificativo peggiore.

### 6.3 Ablazioni (P5), un fattore alla volta rispetto alla base

| Fattore | Punti (oltre la base) | Cosa misura |
|---|---|---|
| Canale dei nomi | V0, V1, V1b, V2b (base V2) | capacità, TPR sotto T1.4 (r = 1,0 natural), T1.6, T4.1 rename; `adversarial_unixcoder`, `adversarial_logreg` |
| Proponente | `static` (base `neural`) | impercettibilità, Pass@1 |
| Legame | `positional`, `function_single_run` (base `function_channel`) | T2.4k, T2.5, T1.5 |
| Maschera | `off` (base `on`) | FPR per identificativo peggiore, classificatori |
| Forme canoniche | `paper` (base `kind`) | T1.4, flip rate dei canali 2, 3, 6 |
| Codice | t = 0 (B = 24), t = 4 | `message_accuracy` e TPR per fascia di siti |
| Voto | `weighted`, `weighted_erasure` con pesi dalla flip rate di dev | T2.1 (b = all), T1.5 |
| **[v1.2]** Canali | `mcss8` (base `extended`); `extended+str` solo se la decisione P lo ammette | siti per campione per fascia, TPR per fascia, ΔPass@1, `adversarial_logreg` |
| **[v1.2]** Parametri nei nomi | `names.include_params=true` (base `false`) | siti dei nomi guadagnati, ΔPass@1 (atteso: fallimenti dei test che chiamano con argomenti nominati), TPR sotto T1.4 |
| **[v1.2]** Variabili di modulo | il valore opposto a quello della base (decisione O) | siti dei nomi su L2, ΔPass@1 su L2 e ClassEval |

Attacchi di sviluppo per le ablazioni (tutti CPU): T1.1, T1.4 (r ∈ {0,5; 1,0} × natural), T1.5 (k = 5), T1.6, T2.1 (b = all), T2.4k (k = 1, 3; solo L2 dev multi-funzione), T2.5 (2, around), T4.1 (rename = true). Niente T2.2 su dev (GPU).

### 6.4 Scelta della configurazione finale (criterio fissato prima dei risultati)

Il **solo** fattore scelto fuori dall'HPO è il canale dei nomi (decisione di Ivan). Gli altri fattori restano quelli di base, salvo che un'ablazione mostri un bug (non un risultato peggiore): in quel caso si corregge e si registra.

Criterio, nell'ordine:
1. Ammissibili: varianti con ΔPass@1 ≤ 3 pp su L1+L2 dev (vincolo del benchmark) **e** `adversarial_unixcoder` (AUROC out-of-fold, L1 dev, entrambi i modelli, media) ≤ AUROC(V0) + **0,10** (**valore proposto, da confermare con il prof**; motivazione: V0 misura la visibilità dei soli canali strutturali, il limite isola il costo del canale dei nomi, e 0,10 supera l'ampiezza degli IC bootstrap osservati in M12, circa ±0,04).
2. Fra le ammissibili: massima **media del TPR@1%FPR** su L1 dev nelle quattro celle di attacco `{T1.4 r=1,0 natural, T1.6, T2.1 b=all, T2.5 (2, around)}`, entrambi i modelli.
3. Pareggio (differenza < 1 punto): TPR senza attacco su L1 dev; poi la variante con meno variabili rinominate.
Nessuna ammissibile: si sceglie V0 e si dichiara.

La scelta aggiorna `configs/hpo/multimark.yaml` (un solo punto) e `configs/method/multimark.yaml`; `tune` la conferma banalmente; `freeze` passa. Deviazione D4x + ADR-021.

### 6.5 Congelamento e test (P6)
`freeze` per i due metodi → fase 0 su L1 e L2 test → attacchi (SPEC §12 per Python, più T1.6, T2.5; T2.4k su L2 test e ClassEval) → L3 → metriche → report. MCGMark, ACW, STONE, PromptMark: solo i nuovi attacchi T1.6 e T2.5 (concordati con Simone).

### 6.6 Tabelle e figure per i capitoli 4 e 5

**Capitolo 4 (metodo).**
- T4.1 Inventario dei siti per canale e dataset (media, mediana, frazione ≥ 13/20/32).
- T4.2 I 14 canali con forme, condizioni e deviazioni da MCSS; i candidati esclusi e il motivo (§3.3.1b).
- T4.3 Fedeltà della reimplementazione `mcss` (round trip, Tabelle 3/5/15 del paper riprodotte in andamento).
- T4.4 Siti minimi analitici per `N_reg` e frazione di alterazione (tabella di §3.10.3).
- F4.1 Schema inserimento/rilevazione con mascheramento e legame per funzione.
- F4.2 Esempio di funzione prima e dopo (4 siti, maschera).

**Capitolo 5 (risultati).**
- **F5.1 (centrale) Curva per numero di siti**: TPR@1%FPR e `message_accuracy` per fascia di `n_sites`, L1+L2 test, `multimark`, `mcss`, `mcgmark`; pannelli senza attacco e sotto T1.4 r = 1,0.
- T5.1 Tabella principale L1 e L2 test: TPR, FPR umano/LLM, AUROC, Pass@1, ΔPass@1, `message_accuracy`, `message_accuracy_detected`, `bit_accuracy`, `embedding_success_rate`, payload (24/12) per i quattro metodi multi-bit più i binari come riferimento.
- T5.2 Robustezza: TPR e `message_accuracy` per attacco (tutti), con `changed_fraction` e `codebleu_distance`.
- T5.3 Granularità: T2.4k (curva in k) e T2.5 per posizione e n: `mcss` contro `multimark` (falsi negativi e `wrong_attribution_rate`).
- T5.4 Ablazione del canale dei nomi: capacità, TPR sotto i quattro attacchi, AUROC dei classificatori, ΔPass@1, variabili rinominate.
- T5.5 Ablazioni degli altri fattori (una riga per punto).
- T5.6 FPR per identificativo peggiore (`mcss` contro `multimark`).
- T5.7 Flip rate per canale e attacco.
- T5.8 Impercettibilità (CodeBLEU, ΔNLL, AUROC dei due classificatori) e T5.9 efficienza (secondi per campione, CPU).
- F5.2 ROC su L1 test; F5.3 TPR contro intensità per T1.4 e T2.5; F5.4 curva in k (T2.4k) su ClassEval; **[v1.2]** F5.5 rilevazione aggregata: TPR contro numero di campioni k (§5.10), L1 e L2 test, `multimark` e `mcss`.

---

## 7. Punti di decisione ancora aperti

| # | Decisione | Opzioni | Scelta predefinita | Quando | Prof? |
|---|---|---|---|---|---|
| A | Limite di AUROC per l'ammissibilità delle varianti dei nomi | relativo V0 + 0,10; assoluto (es. 0,80); nessun limite | relativo V0 + 0,10 | prima di P5.3 | **sì** |
| B | Modalità «confronto con il registro» come punteggio principale | sì; solo decodifica | sì (coincide con il trattamento di MCGMark) | prima di P2 | sì (una frase) |
| C | Parametri nel canale dei nomi di `multimark` | esclusi; inclusi | **chiusa il 13 novembre: esclusi** (cambiano la firma della funzione e rompono i test di chi chiama con argomenti nominati). Nel pool CodeNet i parametri valgono il 31% dei siti dei nomi: la perdita si dichiara nella tesi; `names.include_params=true` è un punto dell'ablazione (§6.3) | chiusa | no |
| D | Canale `none_check` nella base | tenere; escludere | tenere (fedeltà a MCSS); si decide dopo l'ablazione se `adversarial_logreg` lo usa (feature dei nodi `Compare`/`Is`) | P5 | no |
| E | Griglia `t` di `mcss` | {2}; {2, 4, 8} | {2} (D32 è la fascia che conta; il paper usa t = 8 solo da D56) | P2 | no |
| F | Perimetro degli attacchi nuovi | solo i miei; tutti i Python; tutti | tutti i Python | prima di P3 | no (Simone) |
| G | Griglia T2.5 | 9 celle; 3 celle | 3 se il costo supera 1 giorno-CPU di rilevazioni | prima di P6 | no (Simone) |
| H | Attacco rinomina della funzione (T1.7) | fare; non fare | solo in P7 | fine P6 | no |
| I | Dipendenza da N della permutazione di `mcss` | flusso in ordine (indipendente da N nei primi cicli); altro | flusso in ordine | P1; riverificare con il codice ufficiale | no |
| J | Modello dei nomi | Qwen2.5-Coder-0.5B; 1.5B; statico | 0.5B se nella cache del cluster; altrimenti il più piccolo disponibile; statico come ripiego | P3 | no |
| K | Fonte dei file CodeNet per l'autovalidazione di `mcss` | pool L2 (sviluppo e non selezionati, mai test); altre sottomissioni CodeNet dei problemi di sviluppo | pool L2 rifiltrato con `names.module_level=true` (§4.4 punto 2); se < 100 file in fascia 32–39 bit, prima si allarga a ≥ 32, poi si chiede al benchmark la fonte del pool | P1 passo 0 → P2 | no |
| L | Regola di `message_accuracy` quando la decodifica è ambigua | 0 bit; bit decisi dal voto | bit decisi dal voto (credito parziale, conteggio onesto) | P1 | no |
| M | Soglia di rilascio dell'ambiente: torch nel worker CPU | sì sempre; solo per `neural` | sì (un solo ambiente) | P0 | no |
| N | Dimostratore | CLI sola; CLI + web | CLI sola (`multimark/cli/demo.py` nel repository `multimark`: marca, verifica, mostra siti e p-value); web solo se avanza tempo | P7 | no |
| O **[v1.2]** | Variabili di modulo nel canale dei nomi di `multimark` (`names.module_level`) | `true`; `false` | si decide con `P1_inventory_modlevel.txt`: `true` se su L2 dev i siti dei nomi per campione almeno raddoppiano **e** ΔPass@1 su L2 dev e ClassEval resta ≤ 3 pp in P2 (misurato con entrambi i valori, due `config_hash`); altrimenti `false`. Per `mcss` è `true` in ogni caso (fedeltà, §3.6.1) | P1 passo 0 → fine P2 | no |
| P **[v1.2]** | Canale 15 `str_method` con guardia sul tipo | nella base; solo ablazione; escluso | **solo ablazione** (`channels=extended+str`) finché non si misura: entra nella base solo se su L1 dev `adversarial_logreg` non peggiora di più di 0,05 di AUROC rispetto a `extended` e la frequenza con guardia (da `P1_candidates_modlevel.txt`, forma `g.f0_guarded`) supera 0,3 siti per campione su L2 | P1 passo 0 → P5 | no |
| Q **[v1.2]** | Rilevazione aggregata (§5.10) come risultato della tesi | sì (F5.5); no | sì: è la risposta misurabile al codice corto di L1; si chiede al prof se vuole anche una soglia unica per tutti i k | P4 | **sì** (una frase) |

Regola: dove una decisione dipende da un numero non ancora misurato (D, G, O, P), si misura nella fase indicata e si decide entro il punto di controllo settimanale successivo.

---

## 8. Calendario (oggi: giovedì 12 novembre 2026; laurea 28 gennaio 2027)

| Settimana | Date | Fasi | Punto di controllo (venerdì) |
|---|---|---|---|
| S1 | 12–16 nov | P0 **chiusa il 13 nov** | ambiente creato; `P0_inventory.txt`, `P0_candidates.txt`, `P0_mcss_selftest.txt`; decisione C chiusa |
| S2 | 14–23 nov | P1 (passo 0 subito; Ivan rilancia inventario e selftest) | round trip 100% su 14 canali; invarianza alla formattazione; `P1_selftest.txt`; decisioni O e P chiuse o rinviate a fine P2 |
| S3 | 24–30 nov | P2 | due metodi su L1 dev; modifiche comuni con test verdi; audit `mcss` e `multimark`; richiesta a Simone per 5.1–5.5 |
| S4 | 1–7 dic | P3 | V2 neurale; T1.6, T2.5; figura per siti su L1 dev; autovalidazione `mcss` (Tabelle 3/5/15) |
| S5 | 8–14 dic | P4 | soglie L1+L2 definitive; FPR peggiore; flip rate; confronto con il codice ufficiale se uscito; domanda A al prof fatta |
| S6 | 15–21 dic | P5 | ablazioni complete su dev; `P5_selection.txt`; configurazione finale fissata |
| S7 | 22–28 dic | P6 (1/2) | congelamento; fase 0 L1/L2 test; attacchi T1 e T2.1/T2.4/T2.5/T4 su L1 test |
| S8 | 29 dic–4 gen | P6 (2/2) | T2.2, T3.1 (GPU), L2 test, L3; metriche e report; **tutti i risultati della tesi pronti** |
| S9 | 5–11 gen | scrittura cap. 4 e 5; P7 solo se S8 è chiusa | bozza cap. 4–5 |
| S10 | 12–18 gen | scrittura cap. 3, 6, 7; dimostratore CLI; revisione | tesi completa in bozza |
| S11 | 19–25 gen | revisione finale, consegna secondo le scadenze di segreteria (`TODO(ivan)`: data di caricamento) | PDF consegnato |
| — | 28 gen | discussione | |

**Piano di riserva (cosa si taglia, in ordine, se una fase slitta di più di 3 giorni):**
1. P7 per intero.
2. Ablazioni dei fattori «codice» e «voto» (restano nomi, legame, maschera, canonico).
3. Flip rate per canale e FPR per identificativo peggiore (restano nella sezione «sviluppi futuri»).
4. Proponente neurale (resta `static`; la componente neurale della traccia si dichiara come variante implementata ma non selezionata **solo se** era stata misurata almeno su L1 dev; altrimenti si riduce lo scopo nel capitolo 4).
5. L3 e L2 test per `mcss` (resta L1 test).
**Mai tagliare:** `mcss` su L1 test, `multimark` base su L1 e L2 test, curva per numero di siti, T1.6 e T2.5, capacità sotto attacco, le quattro modifiche comuni con test di retrocompatibilità.

---

## 9. Rischi

| Rischio | Prob. | Impatto | Contromisura |
|---|---|---|---|
| ΔPass@1 > 3 pp per un canale con casi limite semantici (aliasing, tipi) | media | alto: configurazione non ammissibile | condizioni strette di §3.3.1; test con esecuzione in P1; `debug_posthoc_failures.py` in P2; escludere il canale e registrare |
| Scrittura LibCST non trova il nodo (`rewrite_mismatch`) su codice reale | media | medio: siti persi | annullamento del singolo sito, conteggio in `extra`, soglia di allarme 2% dei siti su L1 dev |
| Il modello dei nomi produce nomi poco naturali o lenti | media | medio: impercettibilità, tempi | ripiego `static`; cache; GPU per `embed`; misura di `adversarial_logreg` già in P3 |
| Modifiche comuni cambiano i risultati di Simone | bassa | alto | test di retrocompatibilità con confronto numerico su parquet esistenti; commit `common` separati; unione solo dopo il suo via |
| Coda del cluster (MaxSubmit 10, GPU per T2.2/T3.1) | alta | medio: slittamento di P6 | metodi tutti su CPU; T2.2 e T3.1 per ultimi; stima dei costi prima del lancio; piano di riserva |
| Codice ufficiale di MCSS diverso dalla reimplementazione in punti sostanziali | media | medio | audit con elenco delle differenze; se arriva prima di P6 si valuta se adeguare `mcss` (nuovo `config_hash`, i risultati precedenti restano come superati) |
| T2.1 (b = all) colpisce molti canali insieme: TPR molto basso per `mcss` e `multimark` | alta | medio: lettura dei risultati | dichiararlo prima (è un attacco multi-canale, §4 dell'analisi); flip rate per canale; T2.1 per singolo canale in P7 |
| Attacco T2.5 o T1.6 rompe canoniche o cambia Pass@1 | bassa | medio | test di proprietà sulle canoniche prima del lancio; `UNCHANGED`/`NOT_APPLICABLE` corretti |
| `freeze` rifiuta il metodo (griglia non coincidente, soglia provvisoria) | media | basso | griglia a un punto; controllo `scripts/freeze_method.py` in prova su dev prima di S7 |
| Tempo di scrittura della tesi compresso | alta | alto | risultati chiusi entro S8; tabelle e figure generate dal report, non a mano; capitoli 1–2 già pronti |
| Decisione A (AUROC) non arriva dal prof in tempo | media | basso | valore predefinito V0 + 0,10 dichiarato come proposta; si procede e si annota |

---

## 10. Passi operativi per Ivan (una volta sola, prima di P0)

1. Creare su GitHub il repository `multimark` (privato o pubblico a tua scelta), **vuoto**, senza README generato.
2. Sul tuo computer:
   ```bash
   git clone <url di multimark> multimark
   cd multimark
   # copiare qui PIPELINE_metodo.md e CLAUDE.md (quello del metodo)
   git add PIPELINE_metodo.md CLAUDE.md
   git commit -m "[P0] docs: pipeline e regole del metodo"
   git push -u origin main
   ```
3. Nel benchmark, sul tuo computer:
   ```bash
   cd repo_wm_bench
   git checkout main && git pull
   git checkout -b posthoc-multimark
   git submodule add <url di multimark> third_party/multimark
   git commit -m "[P0] submodule: aggiunto third_party/multimark"
   git push -u origin posthoc-multimark
   ```
4. Sul cluster, nel repository del benchmark: `git fetch && git checkout posthoc-multimark && git submodule update --init third_party/multimark`.
4b. Sul cluster, un clone a parte del metodo per le prove fuori dal benchmark (test della libreria, dimostratore, confronto con il codice ufficiale di MCSS): `git clone <url di multimark> /mnt/beegfs/did_tesi_nlp_330/icipriano/repo_multimark`, poi, una volta creato l'ambiente, `<prefisso>/posthoc/bin/python -m pip install -e . --no-deps` dentro il clone. Lì si fa solo `git pull` ed esecuzione, mai modifiche da committare. `third_party/multimark` e `build/patched/multimark` nel benchmark restano di sola lettura.
5. Avviare Claude Code **nel repository `multimark`** con l'istruzione: «Leggi `CLAUDE.md` e `PIPELINE_metodo.md`; esegui la fase P0, parte del repository `multimark`». Alla fine della fase: commit locali di Claude Code, poi `git push` tuo.
6. Avviare Claude Code **nel benchmark** (ramo `posthoc-multimark`) con l'istruzione: «Leggi `CLAUDE.md`, `SPEC.md`, `docs/cluster_info.md` e `third_party/multimark/PIPELINE_metodo.md`; esegui la fase P0, parte del benchmark». Poi `git push` tuo.
7. Da qui in poi, a ogni fase: prima la sessione nel repository `multimark` (se la fase tocca la libreria), push, poi nel benchmark `git submodule update --remote third_party/multimark` + commit `[P<n>] submodule: multimark → <commit>`, poi la sessione nel benchmark. I lanci sul cluster li fai con i comandi che Claude Code ti scrive nei riepiloghi di fase.
