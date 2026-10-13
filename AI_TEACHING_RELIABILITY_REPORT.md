# Arivora — AI Teaching Reliability and Accuracy Corrections

Date: 13 October 2026. Status: local implementation and regression verification completed; **not approved for production release**.

The recorded critical pilot failures now have passing local regressions and held-out variants. This does not establish full educational accuracy. No production curriculum data or migrations were changed. Nothing was pushed or deployed. No additional paid AI calls were made.

## Evidence and test boundaries

Baseline: `EDUCATIONAL_ACCURACY_REPORT.txt`, `CURRICULUM_DATA_QUALITY_REPORT.md`, and `curriculum/audit-2026-10-13/{real-pilot-results,pilot-evaluation,observed-guard-gaps}.json`. The baseline contains 12 actual provider generations across 20 scenarios. Those results remain unchanged.

New evidence is under `curriculum/reliability-2026-10-13/`:

- `backend-tests.log`: complete backend suite, **134 passed**; the previous suite had 115 tests.
- `flutter-tests.log`: complete Flutter suite, **39 passed**. No Flutter code changed in this milestone.
- `handler-results.json`: **34 actual-handler scenarios**, original question, selected curriculum, established edition, actual topic retrieval query and source IDs, controlled generation, displayed answer, guard diagnostics, expected critical claims, context outcome, and local response latency.
- `summary.json`: 28 controlled generations: **17 supported candidates displayed, 11 invalid candidates rejected, zero observed false accepts or false rejects within these candidates**. Six additional scenarios use local reviewed examples or clarifications. Local answers are not counted as model generations.
- `tamil-ranking.json` and `tamil-retrieval-fixture.json`: real saved curriculum rows used in lexical ranking tests. The ranking investigation used all 1,171 saved Class 6 Tamil rows; the committed fixture contains the matching section and the previously selected crossword.
- `tamil-source-mapping-candidates.json`: three local candidate correspondences, explicitly **not edition-verified**.
- `source-integrity.json`: all 11 new topic records match the SHA-256 of the locally archived official PDFs.
- `local-performance.json`: bounded local microbenchmarks, not a production load test.

Tests execute the current `perform_chat` function, actual evidence selection and pre-display validation. Provider generation, authentication, storage, billing and generic retrieval services are controlled adapters. The lexical tests separately execute the real Tamil index against saved database rows. This is **not** a newly measured deployed API, device, network, live vector-retrieval or real-provider evaluation. “Supported” in the controlled scenarios means the asserted critical educational claims, not independent educator certification of every sentence.

## Defects, root causes and corrections

| Recorded defect | Root cause | Correction and evidence |
|---|---|---|
| Wrong vowel classification accepted after removing quotation marks | No independent count/class-membership check | `factual_claim_errors` checks 12 total vowels, five short/seven long, and the short/long letter membership. Original ta07 plus unquoted, markdown, table, Tamil-digit, Tamil-word, English-word, curly-quote and multiline variants fail. Correct and paraphrased classifications pass. |
| Correct 150 m / 30 s answer withheld | All quoted strings were treated as source quotations | Ordinary explanatory quotes no longer require source-string identity. The **unaltered sc03 generation** is displayed with 5 m/s. A held-out 240 m / 40 s case displays 6 m/s and its quoted explanation. Wrong results and supported unit errors fail. |
| இன்பத்தமிழ் author retrieval selected a crossword | Body keyword scores overpowered title identity and nearby author context | Exact title-aware section filtering, author/biography ranking and bounded same-section selection. Full-snapshot results now begin with the poem introduction, author biography and poem ending. Local reviewed facts provide the author, பாரதிதாசன், from official PDF pages 10–11. Actual-handler original and held-out author questions receive these facts. |
| Tamil follow-up lost the topic | Pronoun recognition missed அவற்றுக்கு and only consulted the immediately preceding message | Retrieval resolves a chain back to the most recent substantive student topic, before history truncation. English and Tamil variants are covered. The original user question stays unchanged. Stored reviewed topic IDs can also supply an anchor after server-side ownership/curriculum checks. |
| Vowel follow-up introduced an unverified word example | Generation extrapolated beyond reviewed examples | Requests for vowel examples use the reviewed letter-pair examples directly. The ta08 replay no longer calls the provider or displays ஔவியம். It displays அ–ஆ, இ–ஈ, உ–ஊ and the verified classification. This is a bounded example set, not a reviewed Tamil vocabulary dictionary. |
| வளர்தமிழ் / homogeneous mixture questions refused before retrieval | Any mention of textbook or பாடத்தில் triggered the exact-source route | General and mixed concept requests now reach teaching. Named/numbered page, question and exercise references remain source-gated. Handler tests confirm both original requests and new wordings reach reviewed topic evidence and display useful controlled explanations. |
| Average-speed explanation made an absolute claim about averaging speeds | Correct formula was available but its qualification was not enforced | Reviewed formula plus a separately labelled algebraic derivation for equal durations. Original sc02's unqualified statement is rejected. The corrected explanation includes the equal-time exception and passes. |
| Water composition sketch looked like a chemical reaction | Source content and explanatory derivation were not distinguished | Water record states two H atoms and one O atom. H₂O₂ and wrong oxygen-count claims fail. Original sc07's unlabelled H + O + H → H₂O sketch fails; an explicitly labelled composition sketch passes. |
| Sodium-ion lookup ranked a solubility table first | Similarity ranking did not prioritize the relevant definition | Within CBSE Class 9 Science, sodium queries first use the reviewed chapter 9 electron-loss facts. Original and held-out questions reach that record without a vector/table lookup. Known electron-gain and wrong electron-loss-count claims are checked. This does not establish improved ranking across the full Science corpus. |
| “Atoms in chapter 1” returned an unhelpful generic refusal | Exact-reference routing lacked an edition-specific correction | A topic-matched chapter conflict receives a local correction: Atomic Foundations of Matter is chapter 9 in Exploration 2026, followed by a clarification. The requested chapter is never silently replaced. |
| “Question 7” lacked targeted guidance | Generic missing-source message | When chapter/exercise/page is absent, the response asks which chapter and exercise contains question 7. If identifiers are supplied but evidence is absent, it requests the full question/page image. |

## Validation responsibilities

The existing pre-display gate remains in `educational_accuracy.py`; no independent accuracy service, second judging model or new database architecture was introduced.

1. **Factual claims:** `source_answers.factual_claim_errors`. Bounded pattern checks for pilot vowel counts/membership, selected author conflicts, water composition/formula, sodium electron loss, and speed-mean qualification. Paraphrases do not have to equal source sentences.
2. **Mathematics:** `source_answers.mathematical_claim_errors`. Exact rational arithmetic for supported plain equalities, including × and ÷. Single-distance/single-time speed problems convert supported m/km and second/minute/hour units, check m/s and km/h results, and reject tested acceleration-unit substitutions. Small numeric rounding tolerance is explicit. General algebra, arbitrary LaTeX and multileg unit reasoning are not comprehensively validated.
3. **Quotation:** `quotation_claim_errors`. Actual literary/source quotation claims retain exact normalized source matching, including single/double quotes, multiline quotes and blockquotes. Ordinary quoted explanatory words and mathematical prose use factual/math checks. This is not permission to invent textbook quotations. Existing exact numbered literary answers remain deterministic.
4. **Curriculum consistency:** topic matching checks board, class, subject, edition, academic-year and term conflicts. `curriculum_claim_errors` checks generated chapter/edition claims against selected sources and preserves canonical-versus-textbook identity. Existing exact reference resolution remains authoritative for numbered questions.
5. **Attribution:** `attribution_claim_errors`. Model-generated URLs and unsupported page/textbook attribution are rejected. The server adds citations for the **core facts** only, from local source metadata. Teaching derivations are labelled separately in evidence and prompts.

`reply_errors` exposes separate diagnostics; `validate_reply` retains the existing boolean interface. The bounded model response is still buffered before display. A rejected generation does not leak partial content into the stream. Existing credit accounting, admission, replay and failure handling remain in place and are covered by the existing tests.

## Reviewed pilot coverage

`curriculum/reviewed/pilot-teaching.json` contains **11 source-checked topic records**. These are agent-reviewed factual paraphrases, not verbatim transcriptions or educator-approved full lessons. Each record includes board/class/subject, source title, edition, section/chapter where available, PDF/printed pages where established, official URL, source hash, facts, separate teaching derivations and review status. Missing fields are left null/empty rather than invented.

| Curriculum | Topic | Source identity |
|---|---|---|
| TN Class 6 Tamil, 2024 Term I | இன்பத்தமிழ் and author | Printed pp. 2–3; PDF pp. 10–11 |
| Same | வளர்தமிழ் | Printed pp. 8, 10–11; PDF pp. 16, 18–19 |
| Same | Vowels, குறில் and நெடில் | Printed pp. 18–19; PDF pp. 26–27 |
| CBSE Class 9 Science, Exploration, first edition April 2026, `iesc1` | Distance/displacement | Chapter 4, printed pp. 50–51; PDF pp. 3–4 |
| Same | Average speed | Chapter 4, printed pp. 52–53; PDF pp. 5–6 |
| Same | Average velocity | Chapter 4, printed pp. 53–54; PDF pp. 6–7 |
| Same | Cell membrane | Chapter 2, printed pp. 11–12; PDF pp. 4–5 |
| Same | Homogeneous mixtures | Chapter 5, printed pp. 73–74; PDF pp. 2–3 |
| Same | Water composition | Chapter 9, printed p. 171; PDF p. 10 |
| Same | Sodium ion formation | Chapter 9, printed p. 172; PDF p. 11 |
| Same | Atomic Foundations chapter identity | Chapter 9 title page, PDF p. 1; no printed page inferred |

Existing `class6-tamil-p49.json` remains the reviewed Thirukkural selection/meaning source: TN 2024 Term I selection 7 → canonical 72, printed p. 49/PDF p. 57. Its separate CBSE reader mapping is unchanged. Explicit 2026–27 requests are not silently answered as the 2024 Tamil edition.

The equal-time average-speed statement is a derivation from the verified formula, not represented as a verbatim textbook sentence. Letter-pair examples are labelled teaching examples. The new corpus does not supply full poems, complete chapter exercises, translations, or proof for unrelated model claims.

## Existing Tamil source mapping

Title and author correspondence can be established for selected saved chunks, but their original edition identity is still absent. The saved contents list also differs from the reviewed source's pagination, so topic correspondence cannot establish that all rows came from this edition.

Three local candidate mappings retain document ID/content hash, candidate official source/hash/pages, the comparison basis, and `topic_correspondence_only_not_edition_verified`. No database record was promoted. The existing 1,171-row strict comparison result is not reclassified as verified. The new local facts stand on the official PDF review independently of those legacy rows.

## Conversation and retrieval limits

The retrieval query keeps the substantive user anchor across follow-up chains. It ignores assistant text as evidence and stops at explicit new topics. Saved teaching IDs use the existing context JSON and are rechecked against the current local repository plus board/class/subject. An explicit topic change clears or replaces the topic via the existing write path.

The production context migration remains unapplied. Cross-request durable memory depends on that existing infrastructure being available after a separately approved release; bounded request history works without it. This milestone did not apply a migration to make production persistence appear verified.

The title-aware lexical search only expands within a matched section and the normal result limit. Pilot Science topics use short definition facts with explicit adjacent page identities. Unmatched Science topics still use the existing retrieval path; no full-corpus definition-ranking claim is made.

## False accepts, false rejects and before/after evidence

- Baseline ta07 without quotation marks was accepted. Its unchanged and punctuation-varied incorrect classifications are now rejected for **factual** reasons.
- Baseline sc03 was rejected. Its unchanged correct generation now reaches the displayed answer with the numerical result and ordinary quoted explanation intact.
- Original sc02/sc07 precision issues now fail the targeted gate; corrected candidate explanations pass. A generic rejection is not counted as a useful substantive answer, and no fresh model generation has yet demonstrated the improved prompts in live use.
- ta04, ta06, sc06 and sc08 now receive the intended local evidence in handler tests. These tests demonstrate routing/evidence delivery and display behavior with controlled candidate responses; they do not predict a universal real-provider success rate.
- Zero false accepts/rejects is limited to the 28 controlled candidates listed in `handler-results.json`. Other wording, contradictory statements, negation, complex tables and novel examples can still escape or confuse bounded checks. Do not present this as a production accuracy percentage.

## Performance and operating-cost estimates

Local 200-iteration microbenchmarks recorded median approximately **0.06 ms** for reviewed-topic lookup, **22.22 ms** for warm lexical search across 1,171 Tamil rows, and **0.03 ms** for the critical vowel guard. Machine-specific samples and p95/max are in `local-performance.json`. Controlled-handler timing is separately recorded in `summary.json`; it excludes real database/provider latency. The baseline real pilot's timing is therefore not an apples-to-apples speed comparison.

Pilot facts are short and local. A matched topic avoids a live vector lookup and sends bounded facts, rather than full chapters. Vowel examples and source clarifications make no generation call. There is no additional verifier-model cost. Pilot generations are excluded from the shared answer cache to avoid presenting them as reviewed reusable answers; that can increase provider usage relative to a cache hit. Persistent cache/economic performance has not been load-tested.

**New provider spend for this milestone: US$0.00.** The official [DeepSeek pricing documentation](https://api-docs.deepseek.com/quick_start/pricing/) checked on 13 October 2026 lists Flash peak uncached input at $0.30/million tokens and output at $1.20/million; off-peak rates are half. Assuming 3,000 uncached input and 300 output tokens, generation costs about **$0.00126 per answer at peak**, or **$1.26 per 1,000 answers**, before hosting, database, embeddings, images and other charges. This is an assumption-based estimate, not observed post-fix billing. Pricing and the model behind the legacy alias can change.

A possible future real-provider verification would replay the 20 baseline questions plus held-out cases with an explicit spending cap and isolated services. **Fresh user approval is required before those paid calls.** The previous milestone's approval has not been reused.

## Files changed in this milestone

- `main.py`: reviewed topic evidence, example route, stored topic anchor, chapter correction, source citations, per-question validation and cache handling.
- `educational_accuracy.py`: narrower exact-source intent; separate quote, attribution and curriculum checks; targeted question clarification; diagnostic aggregation.
- `source_answers.py`: independent bounded factual and mathematical checks.
- `chat_cost_controls.py`: English/Tamil follow-up chain resolution.
- `textbook_retrieval.py`: title-aware Tamil ranking, author context and grammar terms.
- `reviewed_sources.py`: bounded local topic loading/matching/evidence/citations.
- `learning_context.py`: scoped reviewed topic ID reads using existing storage.
- `curriculum/reviewed/pilot-teaching.json`: reviewed source facts and metadata.
- `tests/test_teaching_reliability.py`: 19 test methods, including 34 controlled-handler scenarios and multiple held-out/unit variants.
- `curriculum/reliability-2026-10-13/*`: regression, ranking, source-integrity, mapping and timing evidence.
- This report.

Existing uncommitted work in the workspace was preserved. The whole Git working diff also includes earlier milestones; it must not be mistaken for only this milestone's changes.

## Remaining release blockers and review decision

1. Independent Tamil/Science educator review of the 11 records, examples and displayed teaching is still pending.
2. No **post-fix real-provider** run has been performed. Controlled tests do not establish that the model will consistently choose the supported explanation rather than trigger a refusal. Run an approved bounded live pilot before release.
3. The application still uses unverified legacy material outside this narrow set. Full Tamil edition mapping, damaged text/formulas, unsupported quotations and the 44 blocked canonical records remain unresolved; the latter stay blocked. Do not advertise full curriculum verification.
4. Fact/math patterns are intentionally limited. Complex calculations, multilingual science phrasing, arbitrary equations, nuance/negation and unsupported vocabulary need further evaluation. They are not semantically proven by a passing guard.
5. Production context persistence, deployment configuration, actual network failure behavior and load/cost behavior have not been verified after these changes. Production migrations remain unapplied.
6. Tamil 2026–27 equivalence remains unverified. The controlled Tamil source is the explicitly accepted 2024 edition.

The previously identified critical local regression cases pass. The appropriate next action is review of this report and its evidence, followed by separately approved educator/live-provider verification. **No deployment or push was performed. Educational accuracy is not complete.**
