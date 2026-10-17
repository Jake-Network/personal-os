# Portfolio and monthly net worth

## Connect your Google account

After the one-time server setup below, open `/finance`, choose **Google 계정으로 연결**,
sign in to the Google account that can access your private spreadsheet, and approve the
requested permissions. The account needs at least Viewer access; a service account is
not required for this flow. Save your spreadsheet ID, verify current values, and sync.
Google account access is a separate connection from the existing ChatGPT OAuth provider;
it does not add a Personal OS application login or change ChatGPT authentication.

Tokens are encrypted and stored on the server. The browser receives connection status
and an authorization URL, never Google access or refresh tokens. When Google access is
expired or revoked, use **Google 다시 연결**. **Google 연결 해제** removes the local tokens
and stops Google synchronization. Previously imported records are preserved on the server,
and monthly snapshots remain accessible. The current portfolio requires an import matching
the active Google connection; reconnect and synchronize to display it again.
The server also attempts to revoke the grant at Google. If that request
cannot reach Google, remove the grant using your Google Account's
[third-party connections settings](https://myaccount.google.com/connections).

### One-time server setup

1. Enable **Google Sheets API** in your Google Cloud project.
2. Configure Google Auth Platform branding, audience and data access. For an External
   application in Testing, add your own Google account as a test user. Request
   `https://www.googleapis.com/auth/spreadsheets.readonly` plus the identity scopes
   `openid` and `email` used to display the connected account.
3. Create an OAuth client with application type **Web application**. Add the authorized
   redirect URI `http://127.0.0.1:8000/api/finance/google/callback` for native local
   development. The redirect URI must exactly match the server setting, including host,
   port and path. If using a different local port or Docker's frontend port, register
   that browser-accessible callback URL and set the same value below.
   Use the same hostname as the browser's Personal OS URL so the callback receives the
   login cookie: `localhost` and `127.0.0.1` are different hosts. A callback through the
   frontend `/api/finance/google/callback` proxy can keep the same origin.
4. Set these server environment variables, then restart the backend:

   ```dotenv
   GOOGLE_OAUTH_CLIENT_ID=your-web-application-client-id
   GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
   GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/finance/google/callback
   ```

   Keep the existing token-encryption key (or persisted `data/secret.key`) stable across
   restarts so stored credentials remain readable. See `.env.example` for the encryption
   setting. Environment variables must be passed to the running server; `.env` is not
   automatically loaded in native development. In Docker, pass the Google variables to
   the backend container and persist its data directory.

The authorization flow asks for offline access so the server can refresh tokens. For
External applications in Testing, refresh tokens for Sheets access normally expire after
seven days, so reconnection is expected. Moving out of Testing may require Google's app
verification depending on audience and requested scopes. See Google's
[web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server)
and [refresh-token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

Credentials never belong in `NEXT_PUBLIC_*`, browser storage, the spreadsheet, or an
Advisor message. This remains a local, single-user application; Google connection does
not make the Personal OS HTTP server safe to expose publicly.

### Optional server credentials

Existing Application Default Credentials (ADC) remain an alternative before Google OAuth
has been used. For example, store a service-account JSON file outside the repository,
reference it with `GOOGLE_APPLICATION_CREDENTIALS`, and share the spreadsheet with that
service account as a **Viewer**. In Docker, mount the file read-only and set the variable
to its container path. After OAuth is used, a disconnected or expired OAuth connection
requires reconnection; the app does not switch silently to a different Google account.

Open `/finance`, save the spreadsheet ID (the part between `/d/` and `/edit` in its URL),
verify current GOOGLEFINANCE retrieval, then synchronize. Manual prices work without
GOOGLEFINANCE verification. A failed synchronization retains the previous successful
import, records the error and attempt time, and warns that displayed data may be stale.
Changing spreadsheet IDs resets verification. Synchronization is an explicit action;
there is no background scheduler or brokerage connection.

## Worksheet format

Create all the tabs below, with the exact header names in row 1. Dates must be ISO text
`YYYY-MM-DD` (set cells to **Plain text** before entering dates). Amounts and quantities
may be decimal numbers or plain decimal text. Plain text avoids Sheets' own numeric
precision limit. Blank values and formula errors mean unavailable, never zero. Use an
explicit `0` only when the actual balance or quantity is zero. Use stable unique IDs per
position kind; do not reuse one holding ID for two separate lots/accounts.
Each tab supports at most 9,999 data rows. Values must be nonnegative, below `1e20`,
with at most 12 decimal places; invalid values remain unavailable. Net worth and gains
may be negative. These limits keep Decimal calculations bounded.

| Tab | Headers |
| --- | --- |
| `Cash` | `id,label,currency,balance,as_of` |
| `Holdings` | `id,label,ticker,currency,quantity,avg_cost,asset_class,price,price_as_of,source,as_of` |
| `Liabilities` | `id,label,currency,balance,as_of` |
| `OtherAssets` | `id,label,currency,balance,as_of` |
| `FX` | `currency,rate,as_of,source` |
| `Closes` | `ticker,currency,price,as_of,source,valid_through` |
| `History` | `month,kind,id,label,currency,balance,quantity,avg_cost,ticker,asset_class,as_of` |
| `Coverage` | `month,cash,holding,liability,other` |

`currency` is a three-letter uppercase code. Each FX rate means KRW per one unit of
foreign currency; KRW itself uses 1. Keep dated historical FX records as literal values
in `FX`. `asset_class` is `equity`, `etf`, `bond`, `crypto` or `other`; specify `equity`
for stocks rather than assuming every investment is a stock. `source` records provenance,
such as `manual:exchange-close`; use `googlefinance` for current formula values.

`as_of` in a live holding is the date of the quantity record; `price_as_of` is the market
date of its quote. A fresh synchronization does not make an old quote fresh. Enter
unsupported tickers with literal manual prices and their actual price dates. Edit
synchronized records in Sheets, then synchronize again. Once a spreadsheet is configured,
legacy account/holding/FX/liability/other-asset editing APIs and forms are read-only.
Existing local records are preserved, but are excluded from Sheets valuations.

For current data, put `current,TRUE,TRUE,TRUE,TRUE` in `Coverage` only after checking that
every account, holding, liability and other asset has been included. An empty liability
tab with explicit coverage means no liabilities; an empty tab without coverage is unknown.
The same attestation is required per historical month, with `month` such as `2026-09`.

## Verify current GOOGLEFINANCE values

Create a `Verification` tab with these formulas in row 1 (no header):

```text
A1: =GOOGLEFINANCE("NASDAQ:GOOG","price")
B1: =GOOGLEFINANCE("CURRENCY:USDKRW")
```

The Verify action reads both formulas and evaluated values through the official API.
Both must return finite positive numbers. The backend stores the verification time and
proof for this spreadsheet. Until it passes, GOOGLEFINANCE prices and rates are unavailable
for valuation; the program does not assume that a mock test proves Google accessibility.
Current formulas can then be used in the `Holdings.price` and `FX.rate` columns. Set actual
quote/FX dates independently; retrieval time is recorded separately.

[Google documents](https://support.google.com/docs/answer/3093281?hl=en) that quotes can be
delayed up to 20 minutes, many international exchanges are unsupported, and historical
GOOGLEFINANCE arrays **cannot be accessed through Sheets API or Apps Script**. Exchange-qualified
tickers reduce ambiguity. Dates passed to historical formulas use noon UTC and may shift
market dates. This integration does not query those historical arrays or treat a current
quote as a historical close. [Sheets API batchGet](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchGet)
supports retrieving calculated, unformatted current values; availability is still checked
against the user's spreadsheet.

For an opt-in live integration check using the same credential setup:

```bash
PERSONAL_OS_LIVE_SHEETS=1 GOOGLE_SHEETS_TEST_SPREADSHEET_ID=your_id uv run pytest tests/test_sheets_live.py -q
```

Without those variables, the live test skips. Mock-based transport and API integration
tests run in the normal suite. The live test is read-only and does not populate sheets.

## Create and correct month-end snapshots

Populate `History` with **the quantities and balances actually held at that month-end**.
For September, use `month=2026-09` and `as_of=2026-09-30` on each historical row. `kind` is
`cash`, `holding`, `liability` or `other`. Holdings use `quantity` and `ticker`; other kinds
use `balance`. A row for today's holdings is never copied into a past month.

Record literal closing prices in `Closes` and dated literal rates in `FX`, retaining
provenance in `source`. The valuation selects the latest recorded close on or before the
calendar month-end for that ticker and currency, and the applicable dated FX rate.
`Closes.valid_through` attests that this is the last valid market close through that date;
it must cover month-end for a complete snapshot. This lets an actual Friday close cover
a Sunday month-end without inventing Sunday prices. You must confirm this using your
market records. Without adequate evidence or coverage, the snapshot remains incomplete.
Historical formulas are not a substitute for literal recorded evidence.

Synchronize, then select a completed month on `/finance/history` and create its snapshot.
Repeated creation returns the existing latest revision, even after another synchronization.
The frozen snapshot retains individual balances, quantities, prices/dates, FX/dates,
valuation results and completeness. Today's sheet changes cannot rewrite it.

Review a snapshot's lines and audit history. A correction submits a full replacement set
of historical evidence, explicit coverage and a reason. It appends a revision linked to
the previous one; it does not update the original. Concurrent edits to an old revision
are rejected so the reviewer must reload. Corrections are deliberately separate from
ordinary synchronization and are never performed by the Advisor.

Monthly changes compare consecutive, complete months only. Missing months are gaps, not
zero. A percentage change is unavailable when previous net worth is zero or negative.
Net-worth growth is an observed difference; it does not establish whether deposits,
spending, investment returns or currency movements caused that difference. The Advisor's
read-only history tool makes this distinction and respects financial/investment exclusions.

## Database upgrades

The app never migrates an existing database on startup; it uses the database as it is and only
creates tables that are missing. Upgrading is an explicit command run with the same
`DATABASE_URL` / `PERSONAL_OS_DATA_DIR` as the app:

```bash
uv run python -m app.modules.database.migration_manager          # show the plan, change nothing
uv run python -m app.modules.database.migration_manager --apply  # back up, then migrate
```

For a database created by an earlier version (no `alembic_version` table), its tables and columns
are compared with the schema of every migration revision. Only an exact match is stamped; the
append-only triggers that startup never installs are then added and the remaining migrations run.
If nothing matches exactly, the command lists the differences and changes nothing. SQLite files are
copied to `<file>.bak-<UTC timestamp>` before any change; back up PostgreSQL yourself
(`pg_dump`). Migrations only add tables, columns, indexes, triggers and history rows; existing rows
are never rewritten. `uv run alembic upgrade head` still works for databases already under Alembic. Use a dedicated disposable
database for tests because the test fixtures drop application tables.
