# Razorpay live payment setup

Arivora uses the existing merchant account. Approve the public application domain
`https://arivora.onrender.com` in Razorpay before enabling real payments.

Set these private values on the Render backend service only:

- `RAZORPAY_KEY_ID`: the live key ID (`rzp_live_…`).
- `RAZORPAY_KEY_SECRET`: its matching secret.
- `RAZORPAY_WEBHOOK_SECRET`: a separate random secret shared with the live webhook.
- `RAZORPAY_LIVE_ENABLED`: leave `false` until website approval, keys and webhook
  configuration are complete; set `true` for the final switch.

Configure the live Razorpay webhook for `payment.captured` at
`https://akka-tutor-backend.onrender.com/payments/webhook` with the same webhook
secret. Do not change the merchant's other applications or webhook registrations.
Arivora orders are marked with `app=arivora`; notifications for other applications
are ignored. Set payment capture to automatic for the Arivora integration if the
merchant's existing configuration does not already capture payments automatically.

`GET /payments/status` exposes readiness flags without keys or secrets. The
frontend uses it to show the correct Test/Live notice and disables checkout when
status is unavailable or live charging is not explicitly enabled.

Both checkout verification and the signed webhook fetch payment/order records,
check the account owner, server price, currency and captured status, then call the
existing `apply_verified_subscription` transaction. Its payment/order uniqueness
prevents duplicate activation and duplicate referral rewards. No new database
migration is needed for this release; the existing referrals migration is required.

Validation: 14 payment tests, 6 webhook tests, and 94 Flutter tests. These use
synthetic payments; a real captured payment has not been tested by these suites.
The account owner must complete any real-payment test themselves, then verify
captured status, activation, webhook delivery and a single payment ledger entry.
Do not claim a successful live transaction based only on configuration checks.

Support: arivora_support@auxiumsoft.com.
