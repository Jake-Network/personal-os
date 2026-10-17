# Reliability and privacy review

Branch `fix/reliability-and-privacy-hardening`, based on `main` at `d2dd30b` (after PR #1, Google
portfolios and monthly net worth). Every defect below was confirmed by reading the code at that
commit and, where practical, by a test that fails on the old code. Line references point at `d2dd30b`.

## Summary

| # | Area | Verified defect | Status |
|---|------|-----------------|--------|
| 1 | Privacy | Excluded categories leak through replayed conversation history | Fixed |
| 2 | Build | `Markdown.tsx` imported as `markdown`: Linux typecheck/build fails | Fixed |
| 2b | Build | `tsc --noEmit` fails on a clean checkout (`PageProps` comes from `next typegen`) | Fixed |
| 3 | Finance | Equity market value counted as liquid cash; runway funded by shares | Fixed |
| 4 | Finance | One month of spending divided by three; runway used it silently | Fixed |
| 5 | Finance | Manual balance / quantity / cost edits overwrite history | Fixed |
| 6 | Context | Size budget not enforced: oversized package still sent | Fixed |
| 7 | Safety | Concurrent approvals apply the same proposal twice | Fixed |
| 8 | Safety | No Host/Origin validation: DNS rebinding and CSRF on an unauthenticated API | Fixed |
| 9 | CI | No CI | Added |
| 10 | Advisor | Non-`AdvisorError` provider failure breaks the SSE stream without an error event | Fixed |
| 11 | Schema | No safe way to bring a `create_all` database under Alembic | Added (explicit command) |
| 12 | Finance UI | Value history not visible; holding edits had no trade date | Added |
| 13 | API client | Duplicate operationIds drop ChatGPT provider functions on client regeneration | Fixed |

## 1. Privacy leakage through conversation history

**Defect.** `AdvisorManager.ask` replayed the last 20 complete messages verbatim
(`app/modules/advisor/advisor_manager.py:104-109`). The privacy settings were applied only to the
newly built Context Package. After a user consulted on finances and then excluded `financial`, the
next request still carried the earlier answer ("급여통장 잔고 12,000,000원 …") to the provider.

**Root cause.** Privacy was modelled as a property of the Context Package, not of the outbound
request as a whole. Each message records its `context_snapshot_id`, but nothing consulted it.

**Fix.**
- `app/modules/context/history_privacy_manager.py`: each turn is *tainted* by the categories of its
  snapshot **and of every earlier turn**, because those were replayed to the model when it wrote the
  answer. For example, a career-only answer can repeat a balance it saw two turns earlier. A message
  whose taint intersects the current exclusions (saved settings ∪ per-request `exclude`) is
  withheld. A message whose snapshot is unknown (deleted, or never recorded) counts as tainted by
  every category once anything is excluded. The taint only grows, so what remains is always a
  clean prefix of the conversation and user/assistant pairs stay together.
- `AdvisorManager.build_request` is the only place an outbound request is assembled. It re-checks
  that the package contains no excluded category and fails closed (`privacy_violation`, nothing
  sent). When history was withheld, it adds a developer note that tells the model not to guess
  the missing content.
- The SSE `context` event and the preview endpoint report `history_withheld_messages` and
  `history_withheld_categories`. The Context Inspector shows them.

**DB-origin context vs. text the user typed.** Category privacy governs *DB-origin* data, meaning
values that reached the model through a Context Package. Text the user types directly (e.g. "my
balance is 5M") is the user's own disclosure. It is not classified by category; it is withheld only
when its turn is tainted as described above. Excluding a category does not scan or redact free text
the user typed into a turn that never used that category. The same applies to confirmed personal
memories, which are sent under `profile`.

**Evidence.** `tests/test_privacy_history.py` (10 tests). The integration test runs a financial
consultation through the HTTP API, disables `financial` through `PUT /api/settings/privacy`, asks a
follow-up, and asserts that none of the account values, the earlier answer or the earlier question
reach the mocked provider. Other tests cover taint propagation, the clean-prefix rule, unrelated
exclusions, per-request exclusions, deleted snapshots, preview reporting, the history limit and the
fail-closed guard.

## 2. Case-sensitive frontend import and clean-checkout typecheck

**Defect.** Git tracks `frontend/src/components/Markdown.tsx`, while
`advisor-chat.tsx:8` imports `@/components/markdown`. On a case-sensitive filesystem (Linux, CI),
`tsc` fails with `TS2307: Cannot find module '@/components/markdown'`. This was verified on an ext4
copy of `d2dd30b`. It went unnoticed because `/mnt/c` and macOS are case-insensitive. Separately,
`yarn typecheck` (`tsc --noEmit`) failed on a clean checkout because the global `PageProps` type is
generated into `.next/types` by Next.

**Fix.** The file was renamed to `markdown.tsx`, matching the kebab-case used for every other
component (`git mv` in two steps so the case change is recorded). `typecheck` now runs
`next typegen && tsc --noEmit`. A script that resolves every relative and `@/` import against the
exact git-tracked filenames found no other mismatch.

**Evidence.** On the ext4 copy, base `TSC_EXIT=2` and branch `TSC_EXIT=0`. Lint, typecheck, Vitest
and `next build` pass. CI now runs all four on `ubuntu-latest`.

## 3. Cash liquidity vs. investment market value

**Defect.** Holdings were valued with `liquid=True`
(`app/modules/context/context_tool_manager.py:93,95`), so `liquid_assets` included 100% of the
market value of equities and ETFs. The dashboard runway was computed from it
(`app/modules/dashboard/dashboard_manager.py:27-29`). Pension accounts flagged liquid and "other"
accounts were counted as cash too.

**Root cause.** One generic `is_liquid` flag stood in for several distinct questions.

**Fix.** `app/modules/finance/liquidity_policy.py` defines an explicit eligible-cash policy
(`eligible_cash_v1`). Each asset falls into exactly one bucket:

- **cash:** checking, savings, deposit, cash and brokerage_cash accounts
- **investment:** holdings at market value
- **retirement:** pension accounts and the holdings inside them
- **other:** other accounts and other assets

`NetWorth.as_dict()` now reports `net_worth`, `investable_assets` (investment + retirement),
`cash_and_equivalents`, `spendable_liquidity`, `restricted_retirement_assets` and `other_assets`.
The ambiguous `liquid_assets` field is removed rather than silently redefined.

Spendable liquidity is the cash bucket restricted to accounts marked liquid. `is_liquid` can only
narrow eligibility (e.g. a term deposit with a break penalty); it never turns equities, pension
money or property into spendable cash. `FinancialCalculator.cash_runway` uses spendable liquidity
only and assumes no income. A cash account that cannot be converted (missing FX) is reported as
`understated: true`, never overstated. The Sheets source carries no account kinds, so its
liquidity fields are `null` and its runway is unavailable rather than guessed. The system prompt
tells the model to keep these figures distinct and to quote `cash_runway` instead of computing it.

**Evidence.** `tests/test_financial_calculator.py` covers cash plus equities, pension accounts and
pension holdings, missing FX, missing stock prices, negative net worth, and the narrowing rule.
`tests/test_runway_api.py` checks the dashboard API: 13.4M spendable / 2M a month = 6.7 months.
The old code reported 7.1 because it included 700k of shares.

## 4. Incomplete expense history

**Defect.** `monthly_average` divided the total by the full window length
(`financial_calculator.py:51`). One recorded month of 3,000,000 became a "3-month average" of
1,000,000, marked `available: true` with only a `partial` hint. The runway consumed it without
checking.

**Fix.** A month with no entries counts as *unrecorded*, not as zero spending. The average is
`available` only when every month in the window has entries. Partial coverage returns
`available: false`, `reason: insufficient_coverage`, `recorded_months` / `missing_months`, and an
`estimate` explicitly labelled `basis: recorded_months_only` together with its assumption. The
runway never uses the estimate (`reason: monthly_expense_insufficient_coverage`). The flag
`monthly_expense_partial` is replaced by `monthly_expense_insufficient_coverage`. The prompt
requires the model to present the estimate as "가정:", and the dashboard shows "기록 부족 (n/3개월)".

**Evidence.** `test_one_recorded_month_is_not_turned_into_a_three_month_average`,
`test_runway_refuses_partial_expense_history`, and
`test_dashboard_runway_is_unavailable_with_one_month_of_expenses`.

## 5. Manual financial update history

**Defect.** `PersonalDataManager.update` overwrote `accounts.balance`, `holdings.quantity` and
`holdings.avg_cost` in place (`personal_data_manager.py:73`). Only an audit row recording that an
update happened survived, not the values.

**Fix.**
- **Append-only log.** A new table, `manual_value_changes` (`ManualValueChange`), stores
  `old_value` / `new_value` as `Numeric(28, 8)`, which holds both Money and Qty without rounding.
  Each row carries an explicit `as_of` date: the account's `balance_as_of`, or the recording date
  for holdings, which have no quantity date. It also records `change_kind`
  (baseline | create | update | delete). `record_id` has no foreign key, so the history outlives
  a deleted record.
- **Unchanged workflow and reads.** The manual-entry workflow, the request schemas and the
  current-state tables are unchanged. Reads still use `accounts` and `holdings`. The log is
  written in the same transaction as the edit, and only when a tracked value or its as-of date
  changes.
- **History endpoint.** `GET /api/data/{accounts|holdings}/{id}/history` returns the log.
  Differences between rows are documented as recorded edits, not realized returns. Nothing
  computes returns from them.
- **Immutability.** Rows are blocked from changing by an ORM guard and by database triggers on
  SQLite and PostgreSQL, in the same way as `monthly_snapshots`.
- **Migration.** `migrations/versions/0005_manual_value_history.py` creates the table, index and
  triggers, and backfills one `baseline` row per existing balance, quantity and average cost.
  Existing rows are never modified. A record created by the `create_all` startup path before the
  table existed gets its `baseline` lazily on its first edit.

**Evidence.** `tests/test_value_history.py` covers the API workflow, Decimal exactness, no-op
edits, deletes, lazy baselines and the ORM guard. Its migration test runs on SQLite: populated
0004 database → head → `alembic check` → triggers → downgrade. The same backfill, trigger and
downgrade sequence was run manually on PostgreSQL 17 (see Test evidence).

## 6. Context size enforcement

**Defect.** `_fit` (`context_builder_manager.py:107-125`) trimmed notes and job-description text
once. If the package was still too large, it only added a `context_over_budget` flag and sent the
oversized package anyway. It also measured with spaced JSON separators while the package is sent
compact, and ignored the snapshot header.

**Fix.** Deterministic steps run in order until the serialized payload, including the snapshot id
and timestamp, fits:

1. Cap long text at 300 characters.
2. Drop free-text fields.
3. Shrink row lists to 5, lowest-priority section first. Rows that match the question are kept
   first, and sections holding matching rows are reduced last.
4. Drop whole non-essential sections.
5. Reduce essential sections (accounts, cashflow, portfolio, `cash_runway`) to their calculated
   numbers.
6. Merge repetitive tool flags.

Every step is reported in `data_quality_flags`: `context_text_trimmed`, `context_text_omitted`,
`context_rows_omitted` (with counts), `context_section_omitted`, `context_records_summarized`, and
`data_quality_flags_omitted`. These flags themselves are never dropped. If even the calculated
numbers do not fit, `BudgetExceeded` is raised and the advisor returns an error event without
storing or sending anything.

**Evidence.** `tests/test_context_budget.py` covers 24k, 12k and 6k budgets, survival of relevant
rows, reported omissions, determinism and fail-closed behaviour.

## 7. Proposal approval race

**Defect.** `approve` / `reject` read the row, checked `status == "pending"` in Python, and then
wrote it later (`proposal_manager.py:80,104`). Two concurrent approvals both saw `pending`, so the
action ran twice (two tasks created). An approve racing a reject could both "win".

**Fix.** `ProposedActionHandler.transition` performs a compare-and-set
`UPDATE … SET status = :to WHERE id = :id AND status = 'pending'` as the first statement of the
transaction. Exactly one request matches the row. The other waits on the row lock (PostgreSQL) or
the database write lock (SQLite), then matches nothing and gets HTTP 409. If applying the action
fails, the transaction rolls back and the proposal is `pending` again.

**Evidence.** `tests/test_proposal_race.py` runs two threads with separate connections and slows
`_apply` down to widen the window. On the old code both race tests fail: two tasks are created and
an approve/reject pair both succeed. On the new code exactly one request wins, on both SQLite and
PostgreSQL.

## 8. Local API trust boundary

**Defect.** The API has no authentication by design (single user, loopback). It did not validate
Host, so a page on `attacker.example` could rebind its hostname to 127.0.0.1 and read
`/api/data/*` same-origin. It also did not validate Origin, so any web page could fire a simple
cross-site `POST /api/proposals/{id}/approve`, through the Next proxy or directly on port 8000.

**Verified proxy behaviour (Next 16.4.2 rewrites, measured with a header-echo backend).** The
proxy rewrites `Host` to the backend address and forwards the browser's `Origin` unchanged. It sets
`X-Forwarded-Host` to the browser's Host and overwrites any client-supplied value. A Host check
alone would therefore miss rebinding through the proxy.

**Fix.** `app/modules/security/local_trust_middleware.py` is a pure ASGI middleware, so streaming
responses are not buffered.
- `Host` and `X-Forwarded-Host` must be loopback, an IP literal (rebinding needs an
  attacker-controlled hostname), or listed in `PERSONAL_OS_ALLOWED_HOSTS`. Otherwise it returns
  421.
- Requests with `POST`, `PUT`, `PATCH` or `DELETE` that carry `Origin` must come from
  `FRONTEND_URL`, a loopback origin, or the same origin they are addressed to (Windows → WSL by IP
  keeps working). Otherwise it returns 403.
- `Origin: null` and `Sec-Fetch-Site: cross-site` are refused. Requests with neither header (curl,
  tests, server-to-server) cannot be forged by a web page and are allowed.

Localhost development, the Docker setup (host ports bound to 127.0.0.1) and both OAuth callbacks
(top-level GET navigations) are unaffected.

**Evidence.** `tests/test_local_trust.py` (13 tests). The full suite runs through the middleware.

### Remote deployment requirements

The middleware is a local trust boundary, **not authentication**. Before the API is reachable from
anything except the local machine:

1. Put an authenticating reverse proxy in front of both Next and FastAPI (SSO / mTLS / at minimum
   HTTP auth) with TLS. Do not publish port 8000 directly.
2. Set `FRONTEND_URL` to the public origin and `PERSONAL_OS_ALLOWED_HOSTS` to its hostname only.
3. Keep the Google and ChatGPT OAuth callbacks on loopback, or register the new redirect URIs and
   accept that they become reachable.
4. Treat `data/secret.key`, the database and backups as secrets. They decrypt OAuth tokens.
5. Run `python -m app.modules.database.migration_manager --apply` (PostgreSQL recommended) so that the append-only triggers
   exist.

## 9. CI

`.github/workflows/ci.yml` runs on `ubuntu-latest` for pushes to `main` and for pull requests.

- **Backend matrix (SQLite, PostgreSQL 17 service).** `uv sync --frozen`, then `pytest`. The
  PostgreSQL leg first runs `alembic upgrade head`, `alembic check`, `downgrade base` and
  `upgrade head`.
- **Frontend.** `yarn install --frozen-lockfile`, then `lint`, `typecheck`, `test` (Vitest) and
  `build`.

Tests use mocked providers only. No OAuth tokens or API keys exist in CI.

## 10. LLM failure handling

**Defect.** `ask` caught only `AdvisorError` (`advisor_manager.py:120`). A transport error such as
`httpx.ReadTimeout`, or a malformed payload, escaped the generator and broke the SSE stream without
an `error` event. The turn was still settled by `finally`.

**Fix.** Unexpected exceptions are logged, the turn is settled (`failed` question, `incomplete`
partial answer, neither replayed), and a generic error event is sent. There is still no fallback to
another provider. Paid API billing is selectable only explicitly, as before.

**Evidence.** `tests/test_llm_failures.py` covers auth errors without fallback (and with the
selection untouched), mid-stream quota exhaustion, a transport timeout and an empty model list. The
existing quota, failed-turn and disconnect tests still pass.

## 11. Explicit migration of existing databases

**Defect.** The app creates tables with `create_all`, which never records an Alembic revision. The
documented upgrade path asked the user to verify the schema by hand and then `stamp 0001_baseline`.
That is wrong for any database created after 0001: the real local database matches 0004, so
stamping it 0001 would re-run 0002–0004 against tables that already exist.

**Fix.** Startup is unchanged on purpose: it uses the existing database as it is.
`app/modules/database/migration_manager.py` is a separate command the user runs explicitly. It is
a read-only plan by default and runs only with `--apply`.
- It compares the database's tables and columns with the schema of every revision, each built in a
  temporary SQLite file.
- Only an exact match is stamped. The append-only triggers that `create_all` never installed are
  then added, and the remaining migrations run.
- Without an exact match it lists the differences and changes nothing.
- SQLite files are copied to `<file>.bak-<UTC timestamp>` first.

**Evidence.** `tests/test_migration_manager.py` (6 tests) covers:
- a `create_all` database: stamped at head, triggers enforced;
- a 0001-era database with data: preserved, baseline history created, backup exists;
- a schema with an extra column: refused, nothing written;
- versioned and empty databases;
- dry run;
- **app startup does not stamp or migrate an existing database**.

A copy of the real local database was also migrated. Its schema matched 0004, so it was stamped
0004 and upgraded to 0005; its 2 messages were preserved, and the triggers were added. The
original file's hash was unchanged before and after.

## 12. Value history UI and holding trade date

- **History dialog.** Account and holding rows have a 이력 button that opens the append-only
  history (`value-history-dialog.tsx`), newest first. It states that differences are edits, not
  returns.
- **Trade date.** `HoldingCreate.trade_date` is optional. It dates the history row of that edit
  and is **not** stored on `holdings`, so the existing schema stays as it is. Without it, the
  recording date is used.
- **No-op history rows.** A trade date alone, or an unchanged empty value, no longer creates a
  history row.
- **Label.** The `is_liquid` label now says that it only applies to cash-kind accounts.

**Evidence.** `test_trade_date_dates_the_history_row_without_a_schema_change`; lint, typecheck and
build.

## 13. Duplicate OpenAPI operationIds

**Defect.** `google_oauth_router` reused the handler names `get_status`, `start_login` and
`disconnect`, which are already the operationIds of the ChatGPT AI Provider router. Regenerating
the orval client silently removed `getStatus` / `startLogin` / `disconnect` from `ai-provider.ts`,
which would break Settings → AI Provider.

**Fix.** The Google routes now have explicit, unique operationIds; the frontend calls them by URL,
so the rename changes nothing at runtime. The client was regenerated: `ai-provider.ts` is
unchanged, and the previously missing portfolio and Google modules are now generated.

**Evidence.** `test_openapi_operation_ids_are_unique` turns FastAPI's duplicate-id warning into a
failure.

## Test evidence

All commands were run in the worktree on WSL2 (Linux 6.18) on 2026-10-18.

| Command | Result |
|---------|--------|
| `uv run pytest -q` (SQLite) | 195 passed, 1 skipped (`test_sheets_live`: needs live Google credentials) |
| `TEST_DATABASE_URL=postgresql+psycopg://… uv run pytest -q` (postgres:17-alpine) | 195 passed, 1 skipped |
| `alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head` (PostgreSQL) | OK, "No new upgrade operations detected" |
| 0005 on populated PostgreSQL: backfill, UPDATE/DELETE blocked by trigger, downgrade keeps data | OK |
| `yarn lint` | exit 0 |
| `yarn typecheck` (`next typegen && tsc --noEmit`) | exit 0. On ext4: base `d2dd30b` exit 2 (TS2307), branch exit 0 |
| `yarn test` (Vitest) | 6 files, 17 tests passed |
| `yarn build` (Next 16.4.2) | exit 0 |
| Race tests against the pre-fix `proposal_manager.py` | 2 failed (bug reproduced) |

Baseline on `d2dd30b` before any change: pytest 133 passed / 1 skipped; `yarn typecheck` failed
(2 errors).

**Not run locally:** the GitHub Actions workflow itself (it needs a push), and the live Google
Sheets test (it needs real credentials, which were deliberately not accessed).

## Remaining risks

- **User-typed text is not classified.** See §1. A user who typed their balance into a career
  conversation still has it replayed after excluding `financial`. Confirmed memories are shared
  under `profile` regardless of their topic.
- **The history taint is conservative.** Once a conversation touched a now-excluded category,
  every later turn is withheld for the rest of that conversation. Starting a new conversation
  restores full context.
- **Coverage is month-granular.** A month counts as recorded once it has a single entry. A month
  recorded only partly (tracking began mid-month) can still lower the average.
- **Sheets liquidity is unknown.** Sheets rows have no account kinds, so spendable liquidity and
  runway are unavailable on the Sheets source until the sheet records an account kind.
- **Triggers until the explicit migration runs.** Startup deliberately leaves the existing database
  as it is, so a database that has not been through `migration_manager --apply` has no append-only
  triggers. The ORM guard still applies; raw SQL can bypass it.
- **Memory proposals.** `memory_manager.decide` keeps a check-then-write pattern. A concurrent
  confirm/reject leaves contradictory audit rows. There is no external side effect, so it is lower
  risk; the same `transition` pattern applies.
- **History UI not exercised in a browser.** The 이력 dialog passed lint, typecheck and the
  production build, but it has not been clicked through in a running app.

## Suggested next PR

Apply the same `transition` compare-and-set to memory confirmations. Record an account kind in the
Google Sheets source so that spendable liquidity and runway work there. Add day-level coverage to
the expense average for months whose tracking started part-way through.
