# Security fixes — 19 October 2026

Apply `supabase_security_audit.sql` **last**, after the existing app and feature
migrations, then deploy `main.py`, `quiz_security.py` and `image_security.py` with
the updated Flutter client. This migration is transactional and rerunnable.
It requires the existing profiles, live quiz tables/leaderboard, and Supabase
Storage schemas. Keep the service-role key exclusively on the API server.

The migration preserves existing restrictive pre-launch policies and applies
the same gate to the new admission table. It restricts session reads to the teacher and admitted students,
revokes direct client writes and privileged RPC access, and backfills admissions
from historical responses. Joining through `GET /live-quiz/{code}` reserves a
participation slot once, including for students who never answer. Reopening the
same quiz is idempotent. Answer submissions require admission. Hosting and
admission quotas hold a per-account row lock; session and questions are created
in one transaction. Expired/unknown paid tiers receive free-tier quotas.

The `chat-images` bucket becomes private. New uploads use
`chat_uploads/<authenticated-user-uuid>/<128-bit-random-name>.jpg` and are limited
to 5 MB and supported image MIME types. Clients store authenticated object URLs
and send the current student token when displaying them. The backend validates
the origin and exact owner directory before downloading with its server token;
redirects remain disabled. Old public URLs stop working as soon as the migration
commits. Legacy flat objects are retained privately, but cannot be assigned to a
student safely from their old URL alone. Do not reopen the bucket for compatibility.
Old clients must upgrade before uploading images. Plan a maintenance window for
the database/backend/client rollout; the old backend does not understand new
private image paths, and the new backend requires the new quiz RPCs.

Wrong quiz submissions no longer return the correct answer while classmates can
still answer. The student UI handles this omitted field. Quiz requests have a
1 MB actual-byte limit plus bounded structured models (1–50 questions). Internal
database/provider details stay in server logs or are replaced with generic errors.

Run backend regression tests with `python -m unittest discover -s tests -v`.
The workspace `security-audit-2026-10-19/test_database.mjs` executes the real
migrations in isolated PGlite PostgreSQL, including effective RLS, private storage
policies in the presence of a permissive legacy policy, service-only RPC grants,
quota boundaries, rollback, historical backfill and migration reruns.

Before production rollout, verify with synthetic staging accounts:

- An outsider cannot enumerate sessions, read another class's leaderboard,
  submit answers without joining, or directly invoke service-only RPCs.
- Separate simultaneous database connections cannot exceed the last hosting or
  participation slot; aborted transactions release their reservation.
- Teacher start/next/complete and student realtime updates still work; students
  see sanitized questions and can answer only the current question once.
- Anonymous and second-account HTTP downloads of a new student's image fail;
  the owner can upload, preview, reopen a transcript and request OCR tutoring.
- A malformed/oversized quiz returns a safe error without an orphan session.

Local tests do not establish which commit/migrations are running in production.
The migration and application changes have not been deployed by this task.
