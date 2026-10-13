# Arivora — Curriculum Data Quality Report

Date: 13 October 2026 (Asia/Calcutta). Status: audit and controlled pilot completed; not a release approval.

## 1. Decision and scope

The curriculum contains usable teaching material, but this audit does **not** establish that Arivora reliably teaches all selected topics. Science retrieval is promising; Tamil provenance, retrieval and grammar reasoning need targeted work. A full-curriculum accuracy claim is not supported.

- Read every one of the **228,311 production document rows**, excluding embeddings. State Board: **132,641**; CBSE: **95,670**. There are **171 board/class/subject groups**.
- Read-only census count was 228,311 both before and after. Keyset pagination is not a transaction snapshot; unchanged counts cannot exclude concurrent equal-count changes.
- All State Board rows lack source URLs, book codes and language fields. Both boards lack edition, page-identity and educational-review metadata. No row was marked verified.
- Compared **1,704 Class 9 Science chunks** with preserved official chapter PDFs. **1,576** are exact bounded substrings of the identified page extraction; **128** are too short for this verifier. Text-extraction identity is not proof that equations, tables, diagrams or meanings are faithfully represented.
- Ran **20 actual-handler scenarios**, including **12 real-provider generations** and **8 deterministic responses**. Authentication, billing, cache and session persistence used isolated test adapters; curriculum retrieval used live read-only database requests. This is not a deployed HTTP/device acceptance test.
- **115 automated tests passed.** A new formula-boundary test exposed and fixed a defect in the local comparison tool before final results: H₂O must not match a prefix of H₂O₂.
- No production data changes, migrations, deployment, Git push, infrastructure purchase, or work on LearnX. Existing application modules and pending changes were preserved. Paid generation stayed within the explicitly approved US$0.25 limit.

## 2. Curriculum coverage matrix

“Present” means chunks exist. It does not prove that every official textbook, lesson, figure, question or answer is included. “Unknown” is intentional.

| Board | Class | Subject groups | Chunks | Whole-book completeness | Stored edition |
| --- | --- | --- | --- | --- | --- |
| tn | 6 | 5 | 5922 | unknown | unknown |
| tn | 7 | 5 | 6217 | unknown | unknown |
| tn | 8 | 5 | 7429 | unknown | unknown |
| tn | 9 | 5 | 8288 | unknown | unknown |
| tn | 10 | 5 | 11554 | unknown | unknown |
| tn | 11 | 36 | 45146 | unknown | unknown |
| tn | 12 | 39 | 48085 | unknown | unknown |
| cbse | 6 | 7 | 6406 | unknown | unknown |
| cbse | 7 | 7 | 8132 | unknown | unknown |
| cbse | 8 | 7 | 8209 | unknown | unknown |
| cbse | 9 | 7 | 7949 | unknown | unknown |
| cbse | 10 | 5 | 6685 | unknown | unknown |
| cbse | 11 | 20 | 29528 | unknown | unknown |
| cbse | 12 | 18 | 28761 | unknown | unknown |

The complete 171-row subject matrix is in Appendix A and [coverage.csv](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/coverage.csv). The CBSE inventory contains **109 book codes and 933 chapter PDF URLs** (Appendix B). State Board unit/section labels cannot reliably identify individual textbooks or terms.

The 933 CBSE chapter identifiers and row counts match the preserved import manifest and receipts, with zero observed syntactic board/class/subject/book/chapter/page-label mismatches. This is **internal consistency with the import inventory**, not independent proof that the inventory covers the full current NCERT catalogue or syllabus. The old importer’s `verified: true` means uploaded IDs were found, not that teaching content was reviewed.

## 3. Database quality assessment

| Measured field / heuristic | State Board | CBSE |
| --- | --- | --- |
| Missing source URL | 132641 | 0 |
| Missing book code | 132641 | 0 |
| Missing language | 132641 | 0 |
| Rows with edition metadata | 0 | 0 |
| Rows with review status | 0 | 0 |
| Rows with source SHA-256 | 0 | 0 |
| Nonempty metadata objects | 0 | 0 |
| Generic/missing section labels | 23138 | 0 |
| Chunks under 40 characters | 26950 | 9123 |
| Empty chunks | 0 | 0 |
| Extra exact duplicate copies within board/class/subject | 6208 | 6776 |
| Replacement-character flags | 38 | 34 |
| HTML/Office-markup flags | 1474 | 46 |

Duplicate counts include legitimate repeated headings, exercises and boilerplate; **do not delete all flagged rows**. Short chunks may be valid captions or incomplete fragments. Markup and replacement-character flags require source inspection. “No replacement character” is not proof of correct Tamil spelling or formulas. No automatic correction or de-duplication was performed.

The entire `metadata` field is empty across the census. CBSE PDF page numbers exist as text labels (`sub_section_name`), not as reviewed page identities. State Board medium is unknown from stored fields, even when the passage’s script is recognizable. Language detection cannot reconstruct the original medium reliably.

### Pilot group details

| Group | Chunks | Under 40 characters | Exact duplicate excess | Generic sections | Source URLs |
| --- | --- | --- | --- | --- | --- |
| cbse / 9 / Science | 1704 | 128 | 9 | 0 | 1704 |
| tn / 6 / Tamil | 1171 | 527 | 260 | 255 | 0 |

## 4. Authoritative textbook samples and extraction defects

### Tamil Nadu Class 6 Tamil

Reference: official SCERT **2024 reprint, Term I**. This remains the approved local default for the narrowly reviewed selection. It does not establish the edition of the 1,171 database chunks or applicability to 2026–27.

[Official Term I PDF](https://d1e5r329t7a85t.cloudfront.net/syllabuspdf/6th_Tamil%20%26%20English%20Term%201_Text.pdf).

Rendered-page checks:

| Topic | PDF page | Printed page | Established fact / scope |
| --- | --- | --- | --- |
| Inbathamil poetry | 10–11 | 2–3 | Author Bharathidasan; poem and source meaning visible |
| Valartamil prose | 16 | 8 | Prose introduction is present; full lesson not independently transcribed |
| Tamil vowels | 26–27 | 18–19 | Twelve vowels; five short and seven long |
| Thirukkural selection 7 | 57 | 49 | Prior visually reviewed local record maps to canonical 72 and preserves source meaning |

The PDF text layer contains replacement characters on **87 pages** of the combined Tamil/English file, plus repeated letters and interleaved layout. Rendered pages are readable. None of the full database passages matched Term I extraction under the deliberately strict whole-passage comparison. **This does not mean all 1,171 passages are wrong**: missing identities, multiple terms, different representations, chunk boundaries and damaged PDF text all prevent that conclusion. All 1,171 stay `unverifiable` in this automated comparison; the two previously curated local source records remain separate from Supabase.

The author question retrieved a crossword although the matching poem is present in the database and official book. The vowel question retrieved a mix of grammar and unrelated prose; a database equation-like example spells operators as Tamil words and contains distorted letter combinations. This needs image/EPUB alignment rather than unrestricted normalization.

### CBSE Class 9 Science

The represented book is **Exploration**, code `iesc1`, **first edition April 2026**, verified visually from its official imprint. It is not the older Science book with the older chapter sequence. In this edition chapter 4 is Motion, chapter 9 covers atomic foundations, and chapter 1 is an introduction.

[Official imprint](https://ncert.nic.in/textbook/pdf/iesc1ps.pdf), [cell chapter](https://ncert.nic.in/textbook/pdf/iesc102.pdf), [motion chapter](https://ncert.nic.in/textbook/pdf/iesc104.pdf), [mixtures chapter](https://ncert.nic.in/textbook/pdf/iesc105.pdf), [atomic foundations](https://ncert.nic.in/textbook/pdf/iesc109.pdf).

All 13 archived chapter hashes match the preserved import receipts. Four chapters (2, 4, 5, 9) were re-downloaded from NCERT and match those hashes; the imprint was also downloaded. Current server bytes for the other nine chapters were not re-fetched. All eligible text-extraction pages in the 13 chapter files are represented in the sampled subject group; this excludes short/blank pages and does not verify figure/table completeness.

| Visual sample | PDF page / printed page | Finding |
| --- | --- | --- |
| Average speed | chapter 4, p5 / p52 | Fraction and worked example clear on rendering; plain extraction flattens numerator/denominator layout |
| Cell size | chapter 2, p3 / p10 | Fraction and units need layout-aware preservation |
| Cell membrane | chapter 2, p5 / p12 | Selective permeability and membrane composition can support the biology pilot |
| Water composition | chapter 9, p10 / p171 | Subscript 2 and atomic-composition diagram visible; diagram meaning is not recovered from text alone |
| Sodium ion | chapter 9, p11 / p172 | Electron loss and Na+ diagram visible; label-only retrieval can omit explanatory prose |

For this sample, 1,576/1,704 = **92.49% extraction matches**; the other 128 are below the verifier’s 40-character threshold. This percentage is **not educational accuracy**. Formulas that already lost layout during extraction can still match perfectly. The original PDF, page rendering, unmodified text and hashes must remain available for review.

## 5. Reusable verification process

Implemented locally in `audit_curriculum_readonly.py`, `verify_curriculum_text.py` and `compare_curriculum_pilots.py`:

1. Record official publisher, board, class, subject, book/edition, URL, file SHA-256 and acquisition evidence. Keep original PDF bytes.
2. Preserve raw chunk text, ID, hash, declared page/section and source version. Do not overwrite extraction errors.
3. Extract pages with a recorded tool/version; render any equation, table, Tamil or diagram sample.
4. Normalize **NFC and whitespace only**. Do not erase punctuation/signs, repair letters, strip diacritics, collapse subscripts or reorder equations. Require complete word/formula boundaries.
5. Compare only against an identified source and page. Emit `exact_match`, `formatting_only`, `substantive_discrepancy`, or `unverifiable`; preserve evidence and reason. Similarity is diagnostic, never an auto-verification threshold.
6. Keep separate statuses for source identity, text extraction, layout/formulas, meaning and teaching suitability. A text match does not set a production `verification_status`.
7. Require reviewed examples and page/diagram checks before making textbook-confirmed teaching claims. Revalidate when publisher bytes change.

The pilot contains exact and unverifiable cases. Formatting-only and substantive-discrepancy behavior is exercised by controlled local tests; no natural-data counts were fabricated for those categories.

## 6. Real retrieval and conversation measurements

The prepared 20-case plan was approved for paid tests up to US$0.25. The harness executes the **existing `perform_chat`, `_get_context_cached` and `get_context` functions**, with the existing embedding model and live GET requests to `documents` / the stable read-only matching RPC. Only auth, credit accounting, session storage and answer cache are isolated adapters. No fake model response is included in the real-provider results.

There were **12 actual DeepSeek generations**, 2 exact local reviewed-source replies and 6 other deterministic replies. The configured `deepseek-v4-flash` alias was reported by the provider as `deepseek-flash`. The initial embedding-runtime certificate/cache startup issue occurred before any paid call; the harness was corrected without changing application modules.

### Retrieval

- **Science:** 8 answerable concept cases; retrieval ran in 7. All 7 retrieved the expected chapter somewhere in the returned set; **6/7** retrieved the predefined source-page anchor. The remaining calculation retrieved exercises instead of the definition. Across all 8 answerable cases these are **7/8 chapter hits** and **6/8 anchor hits**, because the mixture question was blocked before retrieval.
- **Tamil:** four positive general-retrieval cases; **2/4** contained relevant topic material, while **0/4** had database edition identity established. The author question and vowel follow-up missed their target context. The absent-poem case correctly found no named work.
- Top-ranked material was sometimes irrelevant even when a later chunk was useful: sodium-ion explanation began with a solubility table. Hit-in-returned-set is not precision-at-rank-1 or proof that all context is relevant.
- No cross-board/class passage was observed in this limited pilot. This is not a universal isolation guarantee.

### Explanation and context

Of the 12 generated replies, two were abstentions. Among the ten substantive generations, **eight had source-supported core explanations/calculations**, one contained a definite grammar error, and one included an example that this source review could not validate. Two of the eight supported-core replies still need precision improvements (average-speed exception and atom-composition notation). These are assistant source-based review counts, **not independent teacher ratings or a statistically generalizable accuracy rate**.

The guard withheld three generations: author-answer abstention, incorrect Tamil grammar, and a **correct 5 m/s numerical answer**. Therefore only seven of the eight supported-core generations were actually shown. A correct generation that is withheld is not counted as successful delivery.

For follow-ups: the Kural meaning kept its exact source, and the English speed/velocity follow-up carried the prior topic into retrieval. The Tamil vowel follow-up retained the topic in the generated answer but **lost it in retrieval**, which searched only the follow-up wording. This produced an ungrounded example despite apparent conversational fluency.

Per-case outcomes (full questions, raw generations, displayed replies, retrieved passages/IDs and timings are in linked JSON evidence):

| Case | Topic | Displayed / generation assessment | Context assessment | Seconds |
| --- | --- | --- | --- | --- |
| ta01 | textbook kural 7 | supported | correct | 1.51 |
| ta02 | பொருள் | supported | correct | 0.76 |
| ta03 | 7 | appropriate_clarification | correct | 0.00 |
| ta04 | இன்பத்தமிழ் பாடலை எழுதியவர் யார்? | no_answer | retrieval_miss | 10.06 |
| ta05 | இன்பத்தமிழ் பாடலில் தமிழ் உயிருக்கு இணையாகக் கூறப்படுவது ஏன்? | supported_core | correct | 6.58 |
| ta06 | வளர்தமிழ் பாடத்தில் தமிழ் காலத்திற்கு ஏற்ப எவ்வாறு வளர்கிறது? | unnecessary_abstention | overblocking | 0.01 |
| ta07 | உயிர் எழுத்துகள் எத்தனை? | incorrect_generation_withheld | mixed_retrieval | 1.83 |
| ta08 | அவற்றுக்கு எடுத்துக்காட்டு கொடு | partially_unverifiable | retrieval_context_lost | 2.18 |
| ta09 | “விண்வெளி மிட்டாய் மழை” என்ற பாடலை விளக்குக | appropriate_abstention | correct | 3.46 |
| ta10 | 2026-27 textbook kural 7 | appropriate_abstention | correct | 0.36 |
| sc01 | What is displacement and how is it different from distance? | supported_core | correct | 3.19 |
| sc02 | How do I calculate average speed? | supported_core_with_caveat | correct | 3.21 |
| sc03 | A cyclist travels 150 m in 30 s. What is the average speed? Show the units. | supported_generation_withheld | relevant_chapter_wrong_anchor | 2.69 |
| sc04 | Why is that different from average velocity? | supported_core | correct | 2.70 |
| sc05 | What does the cell membrane do? | supported_core | correct | 2.50 |
| sc06 | What is a homogeneous mixture? Give a textbook example. | unnecessary_abstention | overblocking | 0.01 |
| sc07 | What is the chemical formula of water? What does the 2 mean? | supported_core_with_caveat | correct | 2.35 |
| sc08 | How does sodium form a positive ion in sodium chloride? | supported_core | correct | 2.57 |
| sc09 | Explain atoms from chapter 1 of my Science textbook. | safe_but_incomplete | clarification_incomplete | 0.28 |
| sc10 | Explain question 7 | safe_but_incomplete | clarification_incomplete | 0.27 |

### Cost and latency

12 calls used **33,749 input tokens**, including **16,896 cache-read tokens**, and **4,008 output tokens**. At the checked official prices, usage corresponds to about **US$0.00498–US$0.00997**, depending on peak/off-peak billing; this is an estimate, not a provider invoice. The pre-reserved conservative ceiling for the calls was **US$0.07535**, below the approved US$0.25. No remaining budget was spent on extra trials.

Median end-to-end time for real-provider cases: **2.69 s**; maximum **10.06 s**. This small sequential, partly warm-cache sample excludes model-startup time and is not a production-load benchmark.

[Official DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/): peak input miss $0.30/M, cache hit $0.006/M, output $1.20/M; off-peak half those rates. A persistent results-file guard prevents accidentally rerunning the paid pilot.

## 7. Observed accuracy gaps and recommended fixes

| Observed issue | Evidence | Specific next change |
| --- | --- | --- |
| Correct sources do not ensure correct grammar | ta07 generated 7 short / 5 long vowels; official p19 says 5 / 7 | Add reviewed Tamil grammar facts and contradiction checks; keep classifications tied to a cited source |
| Current guard caught the wrong reply incidentally | Offline replay accepts the same wrong classification after removing quoted example | Separate quote-provenance validation from semantic fact validation; add this exact counterexample to regression fixtures |
| Correct numerical blocked | sc03 correct 150/30 = 5 m/s rejected; same text without quotes passes | Distinguish teaching paraphrases/unit explanations from claimed literary quotations; preserve strict literary quote checks |
| Tamil follow-up retrieval loses topic | ta08 query lacks prior vowel question | Add observed Tamil inflections such as அவற்றுக்கு to reference-follow-up tests and preserve resolved topic for retrieval |
| Named-work author lookup retrieves crossword | ta04 vs ta05 | Prioritize matching title/author metadata and retrieve adjacent author/source notes before generic token overlap |
| Generic textbook wording prevents teaching | ta06 and sc06 never retrieve | Distinguish exact page/selection requests from concept questions that mention a textbook; allow qualified general explanation |
| High-ranked exercise/table fragments | sc02, sc03, sc08 | Evaluate definition-first reranking and source-page/section expansion on these recorded cases |
| Edition cannot be checked for TN data | Every TN row lacks identity metadata | Build a local source/term/edition manifest and reviewed anchors before any backfill proposal |
| Missing review columns | Read-only exact lookup returns PostgreSQL 42703 | Keep migration unapplied; prepare a staging-only validation plan after this review |
| Scientific shorthand needs precision | sc02 and sc07 | Review wording for equal-time average-speed exception and atom-composition diagrams vs chemical reaction equations |

The wrong-year and ambiguous-reference cases did not fabricate a textbook answer. However, safe refusal alone does not demonstrate effective teaching: the wrong-chapter and missing-exercise responses should ask a more targeted clarifying question.

## 8. Automated tests and reproducibility

`python -m unittest discover -s tests`: **115 passed**, including the earlier 112 and three comparison tests. Tests cover exact/NFC-whitespace matching, missing identity, corrupted extraction, formula signs, Tamil letters and formula-boundary prefixes. The initial new test found a local comparator defect, which was fixed; the final complete run passed.

Existing fixture/provider mocks remain clearly separate from this run’s real-provider results. The offline replay demonstrating guard gaps made no additional provider calls. Frontend/mobile/Safari, microphone/camera and staging RLS were not exercised. No application builds were created.

The census uses GET only and reads no student tables or embeddings. Raw snapshots remain in ignored `tmp/curriculum-audit`; the report records a SHA-256 of the complete export. Pilot outputs use synthetic questions. Original PDFs and raw passages were preserved locally; no repaired text was written back.

## 9. Outstanding risks

- This is one small, selected test set, not representative student assessment, adversarial coverage or independent teacher review.
- State Board source identities, terms, editions, chapter boundaries and completeness remain unresolved. Even perfect script detection would not settle them.
- Broad conceptual accuracy, scientific simplification, mathematical reasoning and age-appropriate Tamil remain only partly checked. No second-model agreement is treated as truth.
- Text-only retrieval omits diagram relationships and mathematical layout. A PDF-extraction match can reproduce the same defect in both sources.
- Source URL continuity does not guarantee edition continuity; retain hashes and imprint evidence.
- The existing **44 blocked canonical records** remain blocked. This milestone did not reopen or silently resolve them.
- The pending migration and persistent context table remain unapplied. Live-handler tests used isolated service adapters; production persistence and billing were intentionally not tested.
- Publication/usage rights review from the earlier report remains outstanding; this audit does not change it.

## 10. Recommended next milestone and stopping point

**Pilot Teaching Reliability: Class 6 Tamil + Class 9 Science.** First address the recorded grammar, follow-up, overblocking and ranking failures; create a small reviewed source/fact set with edition/page identities and layout-safe formulas. Then rerun the same fixed questions plus held-out paraphrases under a new approved provider budget and independent teacher review.

A controlled beta need not wait for manual verification of every chunk. It should wait for demonstrated reliability within an explicitly bounded topic set, while unverified explanations remain qualified and exact textbook claims require evidence. Proposed acceptance targets for that next review are zero known critical errors in the curated pilot, preserved follow-up source identity, correct helpful responses to the recorded answerable questions, and explicit provenance/uncertainty. These are future criteria, not achieved results.

Work stops here for review. **No production data was modified, no migration was applied, and nothing was deployed or pushed.**

## Evidence files

- [database-census.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/database-census.json)
- [coverage.csv](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/coverage.csv)
- [mapping-audit.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/mapping-audit.json)
- [pilot-text-comparison.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/pilot-text-comparison.json)
- [pilot-plan.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/pilot-plan.json)
- [real-pilot-results.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/real-pilot-results.json)
- [pilot-evaluation.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/pilot-evaluation.json)
- [observed-guard-gaps.json](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/observed-guard-gaps.json)
- [tests.log](C:/Users/dines/AuxiumSoft/Tutor%20Preethi/Tutor%20AI/curriculum/audit-2026-10-13/tests.log)

Raw export SHA-256: `4ddcfe2fb45109992b0d97a26cba8cbd18d2250442a884e1a4cd14946def854e`.

## Appendix A — Complete subject coverage matrix

Rows indicate content presence only; edition and completeness are unverified for every group.

| Board | Class | Subject | Chunks |
| --- | --- | --- | --- |
| cbse | 10 | English | 1370 |
| cbse | 10 | Health and Physical Education | 908 |
| cbse | 10 | Mathematics | 839 |
| cbse | 10 | Science | 1218 |
| cbse | 10 | Social Science | 2350 |
| cbse | 11 | Accountancy | 2075 |
| cbse | 11 | Biology | 1473 |
| cbse | 11 | Biotechnology | 1731 |
| cbse | 11 | Business Studies | 1779 |
| cbse | 11 | Chemistry | 2423 |
| cbse | 11 | Computer Science | 1353 |
| cbse | 11 | Economics | 1461 |
| cbse | 11 | English | 1386 |
| cbse | 11 | Fine Art | 793 |
| cbse | 11 | Geography | 1537 |
| cbse | 11 | Health and Physical Education | 1677 |
| cbse | 11 | History | 1100 |
| cbse | 11 | Home Science | 1082 |
| cbse | 11 | Informatics Practices | 1001 |
| cbse | 11 | Knowledge Traditions Practices of India | 956 |
| cbse | 11 | Mathematics | 1210 |
| cbse | 11 | Physics | 2287 |
| cbse | 11 | Political Science | 1909 |
| cbse | 11 | Psychology | 1082 |
| cbse | 11 | Sociology | 1213 |
| cbse | 12 | Accountancy | 2854 |
| cbse | 12 | Biology | 1343 |
| cbse | 12 | Biotechnology | 1786 |
| cbse | 12 | Business Studies | 1885 |
| cbse | 12 | Chemistry | 1608 |
| cbse | 12 | Computer Science | 1236 |
| cbse | 12 | Economics | 1398 |
| cbse | 12 | English | 1677 |
| cbse | 12 | Fine Art | 714 |
| cbse | 12 | Geography | 1448 |
| cbse | 12 | History | 2158 |
| cbse | 12 | Home Science | 1484 |
| cbse | 12 | Informatics Practices | 1093 |
| cbse | 12 | Mathematics | 1629 |
| cbse | 12 | Physics | 2233 |
| cbse | 12 | Political Science | 1773 |
| cbse | 12 | Psychology | 913 |
| cbse | 12 | Sociology | 1529 |
| cbse | 6 | Arts | 1860 |
| cbse | 6 | English | 443 |
| cbse | 6 | Mathematics | 1187 |
| cbse | 6 | Physical Education and Well Being | 483 |
| cbse | 6 | Science | 1141 |
| cbse | 6 | Social Science | 818 |
| cbse | 6 | Vocational Education | 474 |
| cbse | 7 | Arts | 782 |
| cbse | 7 | English | 868 |
| cbse | 7 | Mathematics | 1636 |
| cbse | 7 | Physical Education and Well Being | 572 |
| cbse | 7 | Science | 1047 |
| cbse | 7 | Social Science | 2668 |
| cbse | 7 | Vocational Education | 559 |
| cbse | 8 | Arts | 777 |
| cbse | 8 | English | 1087 |
| cbse | 8 | Mathematics | 1593 |
| cbse | 8 | Physical Education and Well Being | 596 |
| cbse | 8 | Science | 1214 |
| cbse | 8 | Social Science | 2378 |
| cbse | 8 | Vocational Education | 564 |
| cbse | 9 | Arts | 816 |
| cbse | 9 | English | 812 |
| cbse | 9 | Mathematics | 1308 |
| cbse | 9 | Physical Education and Well Being | 830 |
| cbse | 9 | Science | 1704 |
| cbse | 9 | Skill Education | 861 |
| cbse | 9 | Social Science | 1618 |
| tn | 10 | English | 919 |
| tn | 10 | Maths | 2558 |
| tn | 10 | Science | 4821 |
| tn | 10 | Social | 1615 |
| tn | 10 | Tamil | 1641 |
| tn | 11 | Accountancy | 1459 |
| tn | 11 | Advance Tamil | 1481 |
| tn | 11 | Basic Automobile Engineering | 857 |
| tn | 11 | Basic Civil Engineering | 980 |
| tn | 11 | Basic Electrical Engineering | 880 |
| tn | 11 | Basic Electronics Engineering | 1163 |
| tn | 11 | Bio Chemistry | 905 |
| tn | 11 | Bio Zoology | 1857 |
| tn | 11 | Botany Volume 1 | 2124 |
| tn | 11 | Business Mathematics and Statistics | 1212 |
| tn | 11 | Chemistry Volume 1 | 607 |
| tn | 11 | Chemistry Volume 2 | 708 |
| tn | 11 | Commerce | 1736 |
| tn | 11 | Communicative English | 611 |
| tn | 11 | Computer Applications | 1456 |
| tn | 11 | Computer Science | 1460 |
| tn | 11 | Economics | 1510 |
| tn | 11 | Employability Skills | 476 |
| tn | 11 | English | 871 |
| tn | 11 | Food Service Management | 1097 |
| tn | 11 | General Nursing | 2516 |
| tn | 11 | Geography | 1300 |
| tn | 11 | History | 2040 |
| tn | 11 | Home Science | 1012 |
| tn | 11 | Mathematics Volume 1 | 1427 |
| tn | 11 | Mathematics Volume 2 | 1171 |
| tn | 11 | Micro Biology | 805 |
| tn | 11 | Nutrition and Dietetics | 996 |
| tn | 11 | Office Management & Typography | 693 |
| tn | 11 | Physics Volume 1 | 1166 |
| tn | 11 | Physics Volume 2 | 1256 |
| tn | 11 | Political Science | 2560 |
| tn | 11 | Statistics | 1338 |
| tn | 11 | Tamil | 923 |
| tn | 11 | Textiles and Dress Designing | 1043 |
| tn | 11 | Zoology | 1450 |
| tn | 12 | Accountancy | 1451 |
| tn | 12 | Advance Tamil | 1716 |
| tn | 12 | Auditing | 1022 |
| tn | 12 | Basic Automobile Engineering | 989 |
| tn | 12 | Basic Civil Engineering | 870 |
| tn | 12 | Basic Electrical Engineering | 830 |
| tn | 12 | Basic Electronics Engineering | 1131 |
| tn | 12 | Basic Mechanical Engineering | 944 |
| tn | 12 | Bio Botany | 2054 |
| tn | 12 | Bio Chemistry | 1123 |
| tn | 12 | Bio Zoology | 1823 |
| tn | 12 | Botany | 1624 |
| tn | 12 | Business Mathematics and Statistics | 1437 |
| tn | 12 | Chemistry Volume 1 | 602 |
| tn | 12 | Chemistry Volume 2 | 554 |
| tn | 12 | Commerce | 1510 |
| tn | 12 | Communicative English | 1218 |
| tn | 12 | Computer Applications | 1122 |
| tn | 12 | Computer Science | 1787 |
| tn | 12 | Economics | 1978 |
| tn | 12 | Employability Skills | 674 |
| tn | 12 | English | 847 |
| tn | 12 | Food Service Management | 947 |
| tn | 12 | General Nursing | 1400 |
| tn | 12 | Geography | 864 |
| tn | 12 | History | 1597 |
| tn | 12 | Home Science | 896 |
| tn | 12 | Mathematics Volume 1 | 1836 |
| tn | 12 | Mathematics Volume 2 | 1414 |
| tn | 12 | Micro Biology | 1402 |
| tn | 12 | Nutrition and Dietetics | 1175 |
| tn | 12 | Office Management and Secretaryship and Typography and Computer Applications | 529 |
| tn | 12 | Physics Volume 1 | 1400 |
| tn | 12 | Physics Volume 2 | 1230 |
| tn | 12 | Political Science | 1521 |
| tn | 12 | Statistics | 790 |
| tn | 12 | Tamil | 1368 |
| tn | 12 | Textiles and Dress Designing | 1036 |
| tn | 12 | Zoology | 1374 |
| tn | 6 | English | 867 |
| tn | 6 | Maths | 1066 |
| tn | 6 | Science | 1122 |
| tn | 6 | Social | 1696 |
| tn | 6 | Tamil | 1171 |
| tn | 7 | English | 701 |
| tn | 7 | Maths | 1179 |
| tn | 7 | Science | 1376 |
| tn | 7 | Social | 1695 |
| tn | 7 | Tamil | 1266 |
| tn | 8 | English | 1021 |
| tn | 8 | Maths | 1627 |
| tn | 8 | Science | 2212 |
| tn | 8 | Social | 1919 |
| tn | 8 | Tamil | 650 |
| tn | 9 | English | 633 |
| tn | 9 | Maths | 1045 |
| tn | 9 | Science | 2880 |
| tn | 9 | Social | 2818 |
| tn | 9 | Tamil | 912 |

## Appendix B — Represented CBSE textbook inventory

Titles/codes below are stored/import-manifest identities; they are not an independently verified complete catalogue. Only the Science pilot edition was checked against its imprint in this milestone. State Board textbook inventory cannot be recovered reliably from current metadata.

| Class | Subject | Book code | Title | Represented chapter files |
| --- | --- | --- | --- | --- |
| 6 | Vocational Education | fekb1 | Kaushal Bodh | 6 |
| 6 | Physical Education and Well Being | feky1 | Khel Yatra | 5 |
| 6 | English | fepr1 | Poorvi | 5 |
| 6 | Mathematics | fegp1 | Ganita Prakash | 10 |
| 6 | Social Science | fees1 | Exploring Society India and Beyond | 14 |
| 6 | Science | fecu1 | Curiosity | 12 |
| 6 | Arts | fekr1 | Kriti-I | 22 |
| 7 | Mathematics | gegp1 | Ganita Prakash | 8 |
| 7 | Mathematics | gegp2 | Ganita Prakash-II | 7 |
| 7 | Arts | gekr1 | Kriti | 20 |
| 7 | Science | gecu1 | Curiosity | 12 |
| 7 | English | gepr1 | Poorvi | 5 |
| 7 | Social Science | gees1 | Exploring Society India and Beyond Part-I | 12 |
| 7 | Social Science | gees2 | Exploring Society India and Beyond Part-II | 8 |
| 7 | Physical Education and Well Being | geky1 | Khel Yatra | 6 |
| 7 | Vocational Education | gekb1 | Kaushal Bodh | 7 |
| 8 | Mathematics | hegp1 | Ganita Prakash Part-I | 7 |
| 8 | Mathematics | hegp2 | Ganita Prakash Part-II | 7 |
| 8 | Arts | hekr1 | Kriti | 19 |
| 8 | Science | hecu1 | Curiosity | 13 |
| 8 | English | hepr1 | Poorvi | 5 |
| 8 | Social Science | hees1 | Exploring Society India and Beyond Part-I | 7 |
| 8 | Social Science | hees2 | Exploring Society India and Beyond Part-II | 8 |
| 8 | Physical Education and Well Being | heky1 | Khel Yatra | 6 |
| 8 | Vocational Education | hekb1 | Kaushal Bodh | 7 |
| 9 | English | iebe1 | Kaveri | 8 |
| 9 | Mathematics | iemh1 | Ganita Manjari | 8 |
| 9 | Mathematics | iemh2 | Ganita Manjari PART-II | 6 |
| 9 | Science | iesc1 | Exploration | 13 |
| 9 | Social Science | iest1 | Understanding Society India and Beyond PART-I | 9 |
| 9 | Social Science | iest2 | Understanding Society India and Beyond PART-II | 6 |
| 9 | Physical Education and Well Being | iehp1 | Khel Praveen | 6 |
| 9 | Skill Education | iekv1 | Kaushal Vikas | 12 |
| 9 | Arts | iemr1 | Madhurima | 17 |
| 10 | Mathematics | jemh1 | Mathematics | 14 |
| 10 | Science | jesc1 | Science | 13 |
| 10 | English | jeff1 | First Flight | 9 |
| 10 | English | jefp1 | Foot Prints Without feet Supp. Reader | 9 |
| 10 | English | jewe2 | Words and Expressions  2 | 7 |
| 10 | Social Science | jess1 | Contemporary India  | 7 |
| 10 | Social Science | jess2 | Understanding Economic Development | 5 |
| 10 | Social Science | jess3 | India and the Contemporary World-II  | 5 |
| 10 | Social Science | jess4 | Democratic Politics | 5 |
| 10 | Health and Physical Education | jehp1 | Health and Physical Education | 10 |
| 11 | Accountancy | keac1 | Financial Accounting-I | 7 |
| 11 | Accountancy | keac2 | Accountancy-II | 2 |
| 11 | Business Studies | kebs1 | Business Studies | 11 |
| 11 | Chemistry | kech1 | Chemistry Part-I | 6 |
| 11 | Chemistry | kech2 | Chemistry Part II | 3 |
| 11 | Mathematics | kemh1 | Mathematics | 14 |
| 11 | Biology | kebo1 | Biology | 19 |
| 11 | Home Science | kehe1 | Human Ecology and Family Sciences Part I  | 7 |
| 11 | Home Science | kehe2 | Human Ecology and Family Sciences Part II  | 4 |
| 11 | Psychology | kepy1 | Introduction to Psychology | 8 |
| 11 | Economics | keec1 | Indian Economic Development | 8 |
| 11 | Economics | kest1 | Statistics for Economics | 8 |
| 11 | Geography | kegy2 | Fundamental of Physical Geography | 14 |
| 11 | Geography | kegy3 | Pratical Work in Geography | 6 |
| 11 | Geography | kegy1 | India Physical Environment | 6 |
| 11 | Physics | keph1 | Physics Part-I | 7 |
| 11 | Physics | keph2 | Physics Part-II | 7 |
| 11 | Sociology | kesy1 | Introducing Sociology | 5 |
| 11 | Sociology | kesy2 | Understanding Society | 5 |
| 11 | English | keww1 | Woven Words | 27 |
| 11 | English | kehb1 | Hornbill | 12 |
| 11 | English | kesp1 | Snapshots Suppl.Reader English | 5 |
| 11 | Political Science | keps1 | Political Theory | 8 |
| 11 | Political Science | keps2 | India Constitution at Work | 10 |
| 11 | History | kehs1 | Themes in World History | 7 |
| 11 | Fine Art | kefa1 | An Introduction to Indian Art Part-I | 8 |
| 11 | Informatics Practices | keip1 | Informatics Practices | 8 |
| 11 | Biotechnology | kebt1 | Biotechnology | 12 |
| 11 | Computer Science | kecs1 | Computer Science | 11 |
| 11 | Health and Physical Education | kehp1 | Health and Physical Education | 11 |
| 11 | Knowledge Traditions Practices of India | keks1 | Knowledge Traditions Practices of India | 9 |
| 12 | Accountancy | leac1 | Accountancy-I | 4 |
| 12 | Accountancy | leac2 | Accountancy Part-II | 6 |
| 12 | Accountancy | leca1 | Computerised Accounting System | 4 |
| 12 | Mathematics | lemh1 | Mathematics Part-I | 6 |
| 12 | Mathematics | lemh2 | Mathematics Part-II | 7 |
| 12 | Physics | leph1 | Physics Part-I | 8 |
| 12 | Physics | leph2 | Physics Part-II | 6 |
| 12 | English | lekl1 | Kaliedoscope | 21 |
| 12 | English | lefl1 | Flamingo | 13 |
| 12 | English | levt1 | Vistas | 6 |
| 12 | Biotechnology | lebt1 | Biotechnology | 13 |
| 12 | Biology | lebo1 | Biology | 13 |
| 12 | History | lehs1 | Themes in Indian History-I | 4 |
| 12 | History | lehs2 | Themes in Indian History-II | 4 |
| 12 | History | lehs3 | Themes in Indian History-III | 4 |
| 12 | Geography | legy1 | Fundamentals of Human Geography | 8 |
| 12 | Geography | legy3 | Practical Work in Geography Part II | 4 |
| 12 | Geography | legy2 | India -People And Economy | 9 |
| 12 | Psychology | lepy1 | Psychology | 7 |
| 12 | Sociology | lesy1 | Indian Society | 7 |
| 12 | Sociology | lesy2 | Social Change and Development in India | 8 |
| 12 | Chemistry | lech1 | Chemistry-I | 5 |
| 12 | Chemistry | lech2 | Chemistry-II | 5 |
| 12 | Political Science | leps1 | Contemporary World Politics | 7 |
| 12 | Political Science | leps2 | Politics in India Since Independence | 8 |
| 12 | Home Science | lehe1 | Human Ecology and Family Sciences Part I  | 7 |
| 12 | Home Science | lehe2 | Human Ecology and Family Sciences Part II  | 7 |
| 12 | Economics | leec2 | Introductory Microeconomics | 5 |
| 12 | Economics | leec1 | Introductory Macroeconomics | 6 |
| 12 | Business Studies | lebs1 | Business Studies-I | 8 |
| 12 | Business Studies | lebs2 | Business Studies-II | 3 |
| 12 | Fine Art | lefa1 | An Introduction to Indian Art Part-II | 8 |
| 12 | Computer Science | lecs1 | Computer Science | 13 |
| 12 | Informatics Practices | leip1 | Informatics Practices | 7 |

## Appendix C — Manifest books without imported chapters

The manifest contains 131 entries, of which 22 have an empty chapter list and no represented source URL in the census. They are not counted among the 109 represented books. This audit did not re-establish why they were unavailable or whether new official files now exist. These known inventory gaps limit coverage claims.

| Class | Code | Manifest title |
| --- | --- | --- |
| 9 | ievc1 | Cashier |
| 9 | ieva1 | Store Operations Assistant |
| 9 | ievs1 | Solanceous Crop Cultivator |
| 9 | ievt1 | Assistant Beauty Therapist |
| 9 | ievw1 | Animal Health Workers (Agriculture) |
| 9 | ieve1 | Hand Embroiderer (Addawala) |
| 9 | ievh1 | Hand Embroiderer |
| 9 | iepg1 | Plumber General |
| 9 | ieeo1 | IT Domestic Data Entry Operator |
| 9 | iees1 | Employability Skill |
| 11 | kepc1 | Floriculturist- Protected Cultivation |
| 11 | kevt1 | Vision Technician |
| 11 | keoc1 | Floriculturist |
| 11 | keda1 | General Duty Assistant |
| 11 | kedf1 | Dairy Farmer Enterpreneur |
| 11 | kefc1 | Floriculturist |
| 11 | kehc1 | Living Craft Traditions of India |
| 11 | kegd1 | The story of graphic design |
| 11 | kect1 | CCT Part-I |
| 11 | kect2 | CCT Part-II |
| 12 | lehc1 | Craft Tradition of India |
| 12 | legd1 | New Age Graphics Design |
