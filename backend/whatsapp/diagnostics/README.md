# Isolated Meta diagnostics

No recommendation or production bot behavior is changed. The default run only
performs GET requests, prints HTTP statuses and redacted JSON, and checks local
health/tunnel endpoints. It does not subscribe/unsubscribe apps or edit settings.

```bash
.venv/bin/python -B -m backend.whatsapp.diagnostics.check_meta
```

Reads `backend/whatsapp/.env` without shell execution. Exported environment variables
take precedence. This differs from the bot: the bot reads only its startup process
environment, and changing `.env` alone does not update a running service.

Targets the explicitly requested Review 2 test WABA `3016542835352548` and Phone
Number ID `1302749026256977`. Discovers the token's app through `GET /app`, then
checks app subscriptions and token validity using the configured app secret.
No access tokens, app secrets, recipient numbers, user IDs or message IDs are logged.
Other Graph response fields, including app/WABA IDs and errors, are retained.

Only after explicitly authorizing a message to a recipient, set
`WHATSAPP_TEST_RECIPIENT` to the allowed recipient's country-code-prefixed digits
and run with `--send`. Exactly one diagnostic text is attempted; there is no retry.
The effective `WHATSAPP_PHONE_NUMBER_ID` must match the test ID. Sending changes
external state; the default run never sends. HTTP 200 means Meta accepted the
request, not that a handset received it.

Inspecting the test WABA subscription and the app's `messages` field are separate
checks. A dashboard sample returning 200 does not establish real handset routing.
See Meta's [WABA subscription query](https://www.postman.com/meta/whatsapp-business-platform/request/d1p5l76/get-all-subscriptions-for-a-waba)
and [app subscription operation](https://www.postman.com/meta/whatsapp-business-platform/documentation/du6gzjv/embedded-signup?entity=request-13382743-fa2e2584-cfcf-4ef2-95c3-5f586569ac4f).
