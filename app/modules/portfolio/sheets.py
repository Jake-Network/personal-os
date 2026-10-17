"""Read-only Sheets access with encrypted user OAuth or explicit legacy ADC."""
from decimal import Decimal, InvalidOperation

TABS = ("Cash", "Holdings", "Liabilities", "OtherAssets", "FX", "Closes", "History", "Coverage")


class SheetsClient:
    def __init__(self, session=None, credentials=None):
        import google.auth
        from googleapiclient.discovery import build

        self.source_identity = None
        if credentials is None and session is not None:
            from app.modules.auth.google_oauth_manager import google_oauth_manager
            # A revoked/disconnected user connection raises here. Do not silently
            # read the sheet as an unrelated ADC identity.
            credentials = google_oauth_manager.get_credentials(session)
            self.source_identity = getattr(credentials, "_personal_os_source_identity", None) if credentials is not None else "adc"
        if credentials is None:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        self.service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def read(self, spreadsheet_id: str, ranges: list[str], render="UNFORMATTED_VALUE") -> list[list]:
        response = self.service.spreadsheets().values().batchGet(
            spreadsheetId=spreadsheet_id, ranges=ranges, valueRenderOption=render,
            dateTimeRenderOption="FORMATTED_STRING",
        ).execute()
        return [r.get("values", []) for r in response.get("valueRanges", [])]

    def tables(self, spreadsheet_id: str) -> dict:
        ranges = [f"'{tab}'!A1:Z10001" for tab in TABS]
        values = self.read(spreadsheet_id, ranges)
        formulas = self.read(spreadsheet_id, ranges, "FORMULA")
        if len(values) != len(TABS):
            raise ValueError("Incomplete Sheets response")
        tables = {}
        if len(formulas) != len(TABS):
            raise ValueError("Incomplete Sheets formula response")
        for tab, rows, formula_rows in zip(TABS, values, formulas):
            if len(rows) >= 10001:
                raise ValueError("Worksheet exceeds import limit")
            if not rows:
                tables[tab] = []
                continue
            headers = [str(h).strip() for h in rows[0]]
            if len(headers) != len(set(headers)) or any(not h for h in headers):
                raise ValueError(f"Invalid {tab} headers")
            # The API returns JSON floats. Convert immediately to text; all arithmetic
            # and persisted financial values subsequently use Decimal/string.
            tables[tab] = [{h: str(row[i]).strip() if i < len(row) and row[i] is not None else ""
                            for i, h in enumerate(headers)} for row in rows[1:] if any(v != "" for v in row)]
            # Inspect formulas independently from editable source labels. Missing
            # cached results still occupy their original row, never zip filtered rows.
            parsed = []
            for row_index, row in enumerate(rows[1:], start=1):
                if not any(v != "" for v in row):
                    continue
                record = {h: str(row[i]).strip() if i < len(row) and row[i] is not None else ""
                          for i, h in enumerate(headers)}
                fs = formula_rows[row_index] if row_index < len(formula_rows) else []
                for i, header in enumerate(headers):
                    formula = str(fs[i]) if i < len(fs) else ""
                    if formula.startswith("=") and (tab in ("Closes", "History") or (tab == "FX" and record.get("source") == "historical")):
                        raise ValueError("Historical evidence must contain literal recorded values")
                    if formula.startswith("=") and (header in ("price", "rate") or "GOOGLEFINANCE" in formula.upper()):
                        if tab not in ("Holdings", "FX") or header not in ("price", "rate"):
                            raise ValueError("GOOGLEFINANCE is allowed only for current prices and FX")
                        # Also gate references/wrappers; they can indirectly depend
                        # on GOOGLEFINANCE cells elsewhere in the workbook.
                        record["source"] = "googlefinance"
                        # IFERROR(...,0) must never create a false free security/rate.
                        try:
                            if Decimal(record[header]) <= 0:
                                record[header] = ""
                        except InvalidOperation:
                            record[header] = ""
                parsed.append(record)
            tables[tab] = parsed
        return tables

    def verify(self, spreadsheet_id: str) -> dict:
        formulas = self.read(spreadsheet_id, ["'Verification'!A1:B1"], "FORMULA")
        values = self.read(spreadsheet_id, ["'Verification'!A1:B1"])
        if not formulas or not values or not formulas[0] or not values[0]:
            raise ValueError("Verification cells are missing")
        fs, vs = formulas[0][0], values[0][0]
        if len(fs) != 2 or len(vs) != 2:
            raise ValueError("Verification requires quote and FX cells")
        for index, (formula, value) in enumerate(zip(fs, vs)):
            normalized = str(formula).upper().replace(" ", "")
            if not normalized.startswith('=GOOGLEFINANCE('):
                raise ValueError("Verification must use direct current GOOGLEFINANCE formulas")
            # Current quote: GOOGLEFINANCE("NASDAQ:GOOG","price"); FX:
            # GOOGLEFINANCE("CURRENCY:USDKRW"). Historical calls have >=3 args.
            if normalized.count(",") > (1 if index == 0 else 0):
                raise ValueError("Historical GOOGLEFINANCE is unsupported through the API")
            if index == 0 and ('"PRICE"' not in normalized or 'CURRENCY:' in normalized):
                raise ValueError("A1 must request a current ticker price")
            if index == 1 and 'CURRENCY:' not in normalized:
                raise ValueError("B1 must request a current currency rate")
            try:
                number = Decimal(str(value))
                if not number.is_finite() or number <= 0:
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise ValueError("GOOGLEFINANCE current values unavailable through Sheets API") from exc
        return {"quote": str(vs[0]), "fx": str(vs[1]), "formulas": [str(f) for f in fs]}
