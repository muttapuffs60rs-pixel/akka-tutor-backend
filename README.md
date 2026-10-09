# Tutor Preethi API

The API supplies textbook tutoring, generated practice quizzes, and classroom quizzes to the Flutter application in `../akka_tutor`.

## Apply the application fixes

1. Apply `supabase_app_hardening.sql` in the Supabase SQL editor after the existing schema/setup scripts. It restricts client profile updates, hides quiz answers from students, restricts score writes to the API, and adds atomic daily reset and quiz quota functions. The migration uses a transaction and can be rerun.
2. Configure `SUPABASE_URL` and `SUPABASE_KEY` on the API server. `SUPABASE_KEY` must be a service-role/secret key; the privileged functions and writes intentionally reject client keys. Keep this key exclusively on the server.
3. Deploy the updated API, including `image_security.py` and `prompts.py`.
4. Build and release the updated Flutter client. It reads daily profile state from the authenticated `/profile` endpoint instead of writing counters and subscription fields from the device.

Run the hardening migration last whenever applying older setup scripts. Do not use `patch_main.py` to overwrite the updated API; it contains an older implementation.

Existing daily rollover behavior is preserved for the day pass. Payment verification, payment configuration, and monthly subscription expiry are deferred.

## Validate locally

```powershell
python -m unittest discover -s tests -v
```

These offline regressions exercise the actual quiz route definitions without starting OCR models or connecting to external services. They cover prompt formatting, response validation, quota rejection/refunds, cross-session answers, and image URL/download restrictions.

In the Flutter directory:

```powershell
flutter test test/active_quiz_screen_test.dart --no-pub
flutter test test/live_quiz_entry_screen_test.dart --no-pub
flutter analyze --no-pub
flutter build web --no-pub
```

## Database validation after migration

Use a staging project with a teacher and student account:

- The student can read their profile and update their name/grade, but updating `subscription_tier`, counters, or dates must fail.
- A direct student query to `quiz_questions` must reveal no rows; the teacher can read their own questions. Students receive sanitized questions through the API.
- A direct client insert/update/delete on `quiz_responses` must fail. Valid answers submitted through the API must still update the teacher's response count.
- An answer using a question ID from another session must fail without adding a response.
- After five generated quizzes in an IST day, another request returns 403. Parallel requests must not exceed the five reserved slots. Failed generation releases its slot.
- Set the test profile's `last_active_date` to yesterday through the SQL editor. Calling `/profile` must reset both counters once; repeated calls must preserve today's usage.

The migration has not been applied or integration-tested against the live database by the local regression suite.

## Chat cost controls

Apply `supabase_chat_cost_controls.sql` after the hardening migration, then deploy
`main.py`, `chat_cost_controls.py` and the Flutter client together. `/ask` now
requires the owned conversation's `session_id`; old clients must be upgraded.
The migration seeds existing conversation lengths without inventing historical costs.

- Each conversation accepts at most 10 submissions, including failed/interrupted
  submissions. Reservations and daily counts happen atomically before OCR or paid
  AI calls. Failed submissions retain the slot to prevent retry abuse.
- Each question is limited to 2,000 characters. Only the last six history messages
  are sent, each capped at 1,500 UTF-8 bytes. Textbook context is capped at 12,000
  bytes and extracted image text at 6,000 bytes. Older details can therefore be
  forgotten; students should restate essential details in a follow-up.
- DeepSeek chat replies stop at 900 output tokens; the prompt asks for concise
  completed answers. DeepSeek thinking is disabled, automatic provider retries
  are disabled, and Gemini image descriptions are capped at 700 output tokens.
  Validate teaching quality, especially complex maths, before release.
- `ai_chat_requests` records DeepSeek and Gemini input/output usage separately.
  Missing metadata is NULL, never zero. `reserved`, `failed`, `interrupted`, and
  `usage_missing` records need reconciliation against provider billing.
- This ledger covers chat, not generated quizzes. Monthly token subscriptions,
  weighted credits, plan pricing, and payment changes are not enabled. Existing
  daily allowances still apply; starting another conversation does not reset them.

Before release, test the migration in staging: send 11 concurrent requests in one
owned conversation with sufficient daily allowance; at most 10 must reserve a
slot. Verify another user's session is rejected, deleting a conversation does not
erase its ledger, and daily limits hold across multiple conversations. Complete
one streamed reply and one image reply and compare recorded provider token usage.
The offline tests verify route behavior but do not execute PostgreSQL or live AI.

## Reviewed answer library

Apply `supabase_answer_library.sql` **after** both migrations above. Deploy
`answer_cache.py` and `answer_library_api.py` with the updated backend and Flutter
client. Set `ANSWER_CACHE_SYLLABUS_VERSION` to a stable curriculum/edition identifier
(for example `tn-scert-2026-reviewed-v1`). With this variable unset, cache lookup and
candidate collection are disabled; normal tutoring continues. Change the identifier
when updating curriculum editions. Restart the backend after replacing textbook
documents so its existing retrieval LRU cache is refreshed too.

The first eligible text question in a conversation searches for a reviewed exact
match after local textbook retrieval. Keys preserve case, punctuation, numbers and
operators and line breaks; only Unicode NFC and spacing within lines are normalized. Board, grade, subject,
Tanglish response language, curriculum version, prompt digest and retrieved context
digest are part of the key. This deliberately favors missed savings over wrong
matches. Follow-ups, image questions, custom history, missing textbook context, and
obvious personal-information patterns bypass the library. Pattern screening is not
a complete PII detector: reviewers must check both question and answer before
approval. The private candidate queue contains no user IDs or conversation history.

Only successful model streams with `finish_reason=stop` are saved as **pending**
candidates. Concurrent misses use an insert-if-absent operation; they cannot replace
an approved, edited, or rejected answer. The current implementation still pays for
each concurrent miss. Rejected entries stay rejected until an admin reopens them.
Library failures fall back to normal AI tutoring.

Administrators (the server-protected `profiles.subscription_tier = 'admin'`) can open
**Answer library** in the drawer. Select an entry, correct its explanation, provide
chapter and textbook edition/section/page, check accuracy and privacy, then approve.
An approved answer can be returned to pending with **Keep unpublished**, or rejected.
Review writes use optimistic concurrency and retain an audit record. Do not grant
client write access to the library tables or promote students to admin for review.

Saved replies show **Reviewed answer** and **Report answer** in the chat, including
after reopening a saved conversation. Reports require a recorded delivery to the
authenticated student, are idempotent per student/answer, and return the entry to
pending immediately. Existing transcript copies remain visible; future requests
use AI until reapproval. Reviews must check edition validity; old-version entries
may remain visible to admins but cannot match a different current version.

Cache hits record `response_source=cache`, `status=cached`, the entry ID, and zero
DeepSeek/Gemini tokens in `ai_chat_requests`. They still consume one conversation
slot and the existing daily **question** allowance. No monthly token wallet or
payment behavior was added. Daily question limits and AI token charges are distinct.

The authenticated `GET /usage` endpoint reports only the caller's chat ledger,
including vision tokens, paginated across the current IST calendar month. The
drawer displays proposed tracking targets of 1.25M (Standard ₹249, legacy ID
`tier_199`) and 3M (tier_499),
explicitly labelled tracking only; these are not enforced subscription wallets
or subscription-anniversary resets. Free users see their daily question allowance.
Missing usage suppresses the monthly percentage. Quizzes and other non-chat AI
features are not included. The card refreshes every 30 seconds while the drawer
is open and provides manual refresh; errors display unavailable rather than zero.

Premium (`tier_999`) is configured at ₹999 / 30 days with an 8M calendar-month
tracking target. Its purchase button remains coming soon until billing is ready.
Free accounts show a 50,000-token lifetime tracking target using all retained
chat usage, so month changes do not refill it. This is NOT a persisted trial
grant: signup eligibility, atomic token reservations, expiry/renewal enforcement,
and account-abuse controls must be implemented before launch. Existing free
accounts also see this tracking preview; missing legacy counts are flagged.
The new tier uses the same existing daily/quiz guardrails as tier_499. Update
the deployed reservation function to recognise tier_999 before activating it;
no database migration or deployment has been performed for these local edits.

### Free learning credits (new implementation; migration required)

Apply `supabase_learning_credits.sql` after the chat reliability migration,
then deploy this backend and the updated frontend together. This supersedes
the free lifetime tracking preview above. Paid monthly token targets remain
tracking-only; this implementation changes free **chat** access, not quiz quotas.

- Each free account receives 15,000 daily credits, reset at midnight IST without
  accumulation. Accounts created at/after the migration's persistent
  `learning_credit_policy.welcome_from` receive 50,000 welcome credits once.
  Existing accounts receive daily credits but no retroactive welcome grant.
- Daily credits are spent before welcome credits. Cached replies cost 3,000
  credits and retain zero provider-token usage. AI replies cost recorded input,
  output and vision tokens. Reopening a transcript and idempotent request replay
  do not create a new charge. Failed/interrupted replies cost zero credits.
- One active free answer per account prevents concurrent requests spending the
  same balance. A cached answer requires 3,000 available credits. An AI answer
  may start with a positive balance and finish past zero; its excess is carried
  against subsequent daily refills instead of cutting the reply off. Rollover
  waits while an answer is active (up to the 10-minute recovery window).
- The final ledger write and debit are one transaction. Duplicate settlement
  returns the original charge. Missing-usage replies are recorded as unmetered
  and waived, not assigned invented provider tokens. Accounting failures retain
  admission for reconciliation and log the request ID; investigate these logs.
- Wallets and credit RPCs are service-role only; the API uses the authenticated
  caller ID. `/usage` includes separate daily/welcome balances for the drawer.
  `/profile` flags credit enforcement to remove the obsolete five-chat client cap.
- Credits are charged when the server completes delivery; transport cannot
  prove the browser read the answer. A retry with the same request ID replays
  the saved answer without a second charge.

Local validation: `test_learning_credits.mjs` in the workspace executes the
migration and checks balances in an isolated PGlite PostgreSQL database. No
production migration, welcome grant or deployment has been performed yet.

Staging acceptance checks (not run against the live database):

1. Configure the version, ask a standalone textbook question, and verify a pending
   entry. Repeat it in another conversation: it must still use AI before approval.
2. Approve through an admin account; repeat in another conversation and verify
   `X-Answer-Source: cache`, identical reviewed text, and zero new provider calls.
3. Change class, subject, textbook content/version, or prompt; the old entry must
   not match. Follow-ups and images must always use the normal tutor flow.
4. Use a student token to list/review or directly access the tables; access must be
   denied. Simultaneous stale reviews must return 409 without overwriting changes.
5. Report a delivered cached answer; verify it becomes pending. A second identical
   report must not inflate the count. A student who never received it cannot report it.
6. Run `flutter test test/answer_library_screen_test.dart --no-pub` along with the
   backend test suite. Review answer quality manually before enabling broad reuse.

To measure hit rate without treating missing usage as free:

```sql
SELECT date_trunc('month', created_at) AS month,
       count(*) FILTER (WHERE status = 'cached') AS cached_replies,
       count(*) FILTER (WHERE status IN ('complete', 'usage_missing', 'cached')) AS delivered_replies,
       count(*) FILTER (WHERE response_source = 'ai' AND input_tokens IS NULL
                        AND status <> 'legacy_unmetered') AS usage_needing_reconciliation
FROM public.ai_chat_requests GROUP BY 1 ORDER BY 1 DESC;
```

This is a count-based reuse metric, not a monetary savings estimate. Actual savings
depend on the input/output mix and the cost of the avoided requests.

## Grade-appropriate teaching

Text and image tutoring both receive the selected class (6–12), subject, and
class-specific teaching instructions: vocabulary, prior knowledge, examples,
mathematical steps, and depth. Class 6 emphasizes simple concrete explanations;
Class 9 adds textbook structures/mechanisms; Class 12 uses relevant higher-secondary
principles and models. Advanced material is included only if supported by that
class's context, not automatically because the grade is higher. The client resolves
the profile grade once and preserves an explicit grade selection during refreshes.

The cache separates grades even for an identical question and context. Its prompt
digest includes all grade guidance, so entries approved under the old generic
prompt cannot be reused after this update; new candidates need fresh approval.
No extra SQL migration is required for this grade update. Offline tests verify the
instructions and grade-specific lookup, not the teaching quality of live AI output.

## Tamil retrieval checks

Tamil and Advance Tamil use a grade-and-subject-scoped lexical index before
semantic retrieval. Titles, poet names and quoted opening lines help identify
the requested work. Matching poetry keeps its line breaks and is not mixed with
unrelated vector matches. Missing named works return the missing-context response.
Formatting cleanup is read-time only; source documents remain unchanged.
Book indexes expire after 15 minutes and at most eight are retained in memory.
Database failures are retried rather than saved as empty indexes.

`tests/fixtures/tamil_retrieval_cases.json` contains textbook-checked poetry,
prose, grammar and wrong-grade/missing-work cases. To run the full-corpus checks,
export only the indicated subject for each grade as `tamil-corpus-N.json`
(document id, content and chapter fields), then run:

```
python evaluate_tamil_retrieval.py --corpus-dir PATH --output report.json
python -m unittest discover -s tests
```

Retrieval checks confirm supporting passages within the context budget, not that
every generated explanation is correct. Review live answers against the books
before approving them in the answer library, especially literary interpretations.

## Connection reliability and chat admission

Apply `supabase_chat_reliability.sql` before this backend release. It adds a
service-role-only `reserve_chat_request_v2` RPC; the original RPC remains available
for old releases. A stable client request UUID and hash bind each submission to
one user, conversation and payload. Database retries reuse the execution UUID.
Concurrent duplicate HTTP requests cannot start a second generation. Completed
responses can be replayed for 24 hours without another quota increment or AI call.
An hourly pg_cron job removes expired replay text; accounting and identity remain.
Terminal/expired requests are not regenerated automatically. Interrupted AI streams
are not retried: the provider may already have performed billable work.

Supabase uses a TLS-verified HTTP/1.1 pool (40 connections, 20 keepalive, 15-second
read/write timeout, 5-second connect/pool timeout). Only reads, the idempotent
reservation RPC and deterministic usage updates use the bounded transport retry.
Arbitrary writes, payment actions and AI generation are not automatically retried.

Each application process admits 20 chats, holds at most 40 waiters and waits at
most 25 seconds. Admission precedes quota reservation. Overload returns 503 with
Retry-After; waiting disconnects and all response exits release capacity. Slots
cover preparation and the full stream, not just response headers. This is a
per-process limit; multiple workers/instances multiply it and require fresh load
testing. Authentication runs before admission. No subscription limits are raised.

The web client uses one request ID across up to four transport/admission attempts,
shows a waiting message, and distinguishes an in-progress duplicate from the
10-question conversation limit. Old clients without a request ID still receive
safe database retries inside one HTTP request, but cannot replay across HTTP calls.

Named Tamil literature questions use low-effort reasoning with a hard 1,800-token
completion budget shared by reasoning and the visible answer. Ordinary grammar,
Maths and Science retain the 900-token cap. Reasoning tokens are included in
provider-reported output usage; reasoning text is not streamed to students.
This improves evidence handling but does not replace teacher-reviewed literary
glosses. The regression corpus includes quoted novel grammar examples and keeps
unknown-poem and wrong-grade rejection checks.

### ₹49 top-up and saved-answer pricing update

The ₹49 day pass is no longer offered for new orders. `TOPUP_PACKS.topup_49`
configures a one-time 200,000-learning-credit pack valid for 30 days. It is kept
separate from subscriptions: purchase must never replace the existing tier.
The frontend shows Coming soon, and the order API rejects purchases until
payment launch is enabled. Captured-payment verification, an idempotent grant
RPC and expiring top-up balances are implemented locally; no production grants
have been made. Existing legacy day-pass
accounts keep their current expiry behaviour.

Every newly completed saved answer records 3,000 learning credits on the request
ledger, including paid plans, and zero actual AI tokens. Free balances deduct
that amount; paid tracking meters now use learning-credit charges rather than
provider tokens, including actual AI usage for non-cached answers. Old settled
requests retain their historical charge; retries do not reprice them. Paid
monthly blocking is still pending. The underlying input/output/vision usage
remains available separately for company cost analysis.

Top-ups are stored independently in `learning_credit_topups`. A verified ₹49 INR
captured payment grants 200,000 credits once per payment/order, expiring 30 days
after the first grant. Repeat verification never extends expiry or refills the
pack. Free daily/welcome balances and paid monthly tracking allowances are used
before packs; valid packs are spent earliest-expiry first. Paid usage meters
exclude credits deducted from top-ups, avoiding double deduction. Paid monthly
blocking remains pending. Packs valid at answer admission may finish being used
during that answer even if their expiry passes; they cannot start a new answer
after expiry. Never call the grant RPC on a client or before payment validation.
