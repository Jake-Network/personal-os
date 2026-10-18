"""Dedicated app-created file; payloads contain public symbols and formulas only."""

import re

from app.modules.auth.google_checks import WRITE_SCOPE
from app.modules.auth.google_oauth_manager import google_oauth_manager

EXCHANGES = {"NASDAQ", "NYSE", "NYSEARCA", "AMEX", "KRX", "KOSDAQ"}


def quote_rows(symbols):
    result = []
    for symbol in sorted(set(symbols)):
        if (
            not re.fullmatch(r"[A-Z]+:[A-Z0-9][A-Z0-9.-]{0,30}", symbol)
            or symbol.split(":")[0] not in EXCHANGES
        ):
            continue
        result.append(
            [
                symbol,
                f'=GOOGLEFINANCE(A{len(result) + 2},"price")',
                f'=GOOGLEFINANCE(A{len(result) + 2},"currency")',
                f'=GOOGLEFINANCE(A{len(result) + 2},"tradetime")',
                f'=GOOGLEFINANCE(A{len(result) + 2},"datadelay")',
            ]
        )
    return result


class QuotesSheet:
    def __init__(self, session):
        from googleapiclient.discovery import build

        conn = google_oauth_manager.current(session)
        broad = {
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.readonly",
        }
        if (
            not conn
            or conn.status != "connected"
            or WRITE_SCOPE not in conn.scopes
            or broad.intersection(conn.scopes)
        ):
            raise ValueError(
                "Reconnect Google with drive.file permission; revoke the previous broad grant in Google account settings"
            )
        credentials = google_oauth_manager.get_credentials(session, require_write=True)
        self.source_identity = getattr(
            credentials, "_personal_os_source_identity", None
        )
        self.service = build(
            "sheets", "v4", credentials=credentials, cache_discovery=False
        )

    def create(self):
        result = (
            self.service.spreadsheets()
            .create(
                body={
                    "properties": {
                        "title": "Personal OS Public Quotes",
                        "timeZone": "Etc/UTC",
                    },
                    "sheets": [
                        {"properties": {"title": "Quotes"}},
                        {"properties": {"title": "FX"}},
                    ],
                },
                fields="spreadsheetId",
            )
            .execute()
        )
        return result["spreadsheetId"]

    def provision(self, sheet_id, symbols, currencies):
        quotes = quote_rows(symbols)
        fx = []
        for currency in sorted(set(currencies) - {"KRW"}):
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError("Invalid currency")
            pair = currency + "KRW"
            fx.append([pair, f'=GOOGLEFINANCE("CURRENCY:{pair}")'])
        # All ranges are replaced in one request. No account identifiers or local IDs.
        self.service.spreadsheets().values().batchClear(
            spreadsheetId=sheet_id, body={"ranges": ["Quotes!A:E", "FX!A:B"]}
        ).execute()
        self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": [
                    {
                        "range": "Quotes!A1",
                        "values": [
                            [
                                "ticker",
                                "price",
                                "currency",
                                "trade_time",
                                "delay_minutes",
                            ],
                            *quotes,
                        ],
                    },
                    {"range": "FX!A1", "values": [["pair", "rate"], *fx]},
                ],
            },
        ).execute()
        return [r[0] for r in quotes]

    def read(self, sheet_id):
        response = (
            self.service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=sheet_id,
                ranges=["Quotes!A2:E10001", "FX!A2:B10001"],
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        values = response.get("valueRanges", [])
        if len(values) != 2:
            raise ValueError("Incomplete quote response")
        return values[0].get("values", []), values[1].get("values", [])
