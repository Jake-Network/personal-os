"""Sheets access with server-held credentials and explicitly authorized writes."""
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
import hashlib
import json

TABS = ("Cash", "Holdings", "Liabilities", "OtherAssets", "FX", "Closes", "History", "Coverage")


class SheetsClient:
    def __init__(self, session=None, credentials=None, require_write=False):
        import google.auth
        from googleapiclient.discovery import build

        self.source_identity = None
        if credentials is None and session is not None:
            from app.modules.auth.google_oauth_manager import google_oauth_manager
            # A revoked/disconnected user connection raises here. Do not silently
            # read the sheet as an unrelated ADC identity.
            credentials = (google_oauth_manager.get_credentials(session, require_write=True) if require_write
                           else google_oauth_manager.get_credentials(session))
            self.source_identity = getattr(credentials, "_personal_os_source_identity", None) if credentials is not None else "adc"
        if credentials is None and require_write:
            raise ValueError("Google write authorization required")
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
                        current_date = (tab == "Holdings" and header == "price_as_of") or (tab == "FX" and header == "as_of" and record.get("source") == "googlefinance")
                        if current_date:
                            continue
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

    def layout(self, spreadsheet_id):
        result = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
        return {s["properties"]["title"]: s["properties"]["sheetId"] for s in result.get("sheets", [])}

    def _write_cells(self, spreadsheet_id, sheet_id, row, values, formulas=()):
        cells = [{"userEnteredValue": {"formulaValue" if index in formulas else "stringValue": str(value)}}
                 for index, value in enumerate(values)]
        self.service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [{
            "updateCells": {"start": {"sheetId": sheet_id, "rowIndex": row, "columnIndex": 0},
                            "rows": [{"values": cells}], "fields": "userEnteredValue"}}]}).execute()

    def initialize(self, spreadsheet_id):
        layout = self.layout(spreadsheet_id)
        # Validate every existing nonempty header before changing anything.
        for tab, headers in HEADERS.items():
            if tab in layout:
                rows = self.read(spreadsheet_id, [f"'{tab}'!A1:Z10001"])[0]
                if rows and (rows[0] != headers) and any(any(cell != "" for cell in row) for row in rows):
                    raise ValueError(f"{tab} has incompatible headers; existing data was preserved")
        missing = [tab for tab in (*TABS, "Verification") if tab not in layout]
        if missing:
            self.service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [
                {"addSheet": {"properties": {"title": tab}}} for tab in missing]}).execute()
            layout = self.layout(spreadsheet_id)
        for tab, headers in HEADERS.items():
            rows = self.read(spreadsheet_id, [f"'{tab}'!A1:Z1"])[0]
            if not rows or not rows[0]:
                self._write_cells(spreadsheet_id, layout[tab], 0, headers)
        verification = self.read(spreadsheet_id, ["'Verification'!A1:B1"], "FORMULA")[0]
        if not verification or not any(verification[0]):
            self._write_cells(spreadsheet_id, layout["Verification"], 0,
                              ['=GOOGLEFINANCE("NASDAQ:GOOG","price")', '=GOOGLEFINANCE("CURRENCY:USDKRW")'], (0, 1))

    def holding_rows(self, spreadsheet_id):
        rows = self.read(spreadsheet_id, ["'Holdings'!A1:Z10001"])[0]
        if not rows or rows[0] != HEADERS["Holdings"]:
            raise ValueError("Initialize worksheet headers first")
        if len(rows) >= 10001:
            raise ValueError("Worksheet exceeds import limit")
        return [{header: str(row[i]) if i < len(row) else "" for i, header in enumerate(rows[0])}
                for row in rows[1:] if any(value != "" for value in row)]

    def upsert_holding(self, spreadsheet_id, body):
        layout = self.layout(spreadsheet_id)
        if any(tab not in layout for tab in (*TABS, "Verification")):
            raise ValueError("Initialize the spreadsheet first")
        raw = self.read(spreadsheet_id, ["'Holdings'!A1:Z10001"], "FORMULA")[0]
        if not raw or raw[0] != HEADERS["Holdings"] or len(raw) >= 10001:
            raise ValueError("Invalid Holdings headers or row limit")
        matches = [i for i, row in enumerate(raw[1:], 1) if row and str(row[0]) == body.position_id]
        if len(matches) > 1:
            raise ValueError("Duplicate position ID; correct the spreadsheet first")
        index = matches[0] if matches else len(raw)
        values = [body.position_id, body.label, body.ticker, body.currency, str(body.quantity),
                  str(body.avg_cost) if body.avg_cost is not None else "", body.asset_class,
                  f'=GOOGLEFINANCE("{body.ticker}","price")' if body.quote_mode == "auto" else str(body.manual_price),
                  f'=TEXT(GOOGLEFINANCE("{body.ticker}","tradetime"),"yyyy-mm-dd")' if body.quote_mode == "auto" else body.price_as_of.isoformat(),
                  "googlefinance" if body.quote_mode == "auto" else "manual", __import__("datetime").date.today().isoformat()]
        if index < len(raw) and raw[index] == values:
            return
        if matches:
            previous = {header: str(raw[index][i]) if i < len(raw[index]) else ""
                        for i, header in enumerate(HEADERS["Holdings"])}
            if not body.expected_version or body.expected_version != holding_version(previous):
                raise ValueError("Holding changed or edit version missing; reload before editing")
        # Never append after an uncertain network response. A retry rereads the same
        # stable position ID and updates that row instead of creating another lot.
        self._write_cells(spreadsheet_id, layout["Holdings"], index, values,
                          (7, 8) if body.quote_mode == "auto" else ())

    def ensure_current_fx(self, spreadsheet_id, currency):
        if currency == "KRW":
            return
        layout = self.layout(spreadsheet_id)
        raw = self.read(spreadsheet_id, ["'FX'!A1:Z10001"], "FORMULA")[0]
        if not raw or raw[0] != HEADERS["FX"] or len(raw) >= 10001:
            raise ValueError("Invalid FX layout")
        # Preserve a recent valid manually recorded FX rate; do not create a
        # competing same-date automatic record that would invalidate both.
        for row in raw[1:]:
            if row and row[0] == currency and len(row) > 3 and row[3] != "googlefinance":
                try:
                    value, observed = Decimal(str(row[1])), date.fromisoformat(str(row[2]))
                    if value.is_finite() and value > 0 and timedelta(0) <= date.today() - observed <= timedelta(days=7):
                        return
                except (InvalidOperation, ValueError):
                    pass
        # Preserve all literal/manual/historical evidence and existing live formulas.
        if any(row and row[0] == currency and len(row) > 3 and row[3] == "googlefinance" for row in raw[1:]):
            return
        self._write_cells(spreadsheet_id, layout["FX"], len(raw),
                          [currency, f'=GOOGLEFINANCE("CURRENCY:{currency}KRW")',
                           '=TEXT(TODAY(),"yyyy-mm-dd")', "googlefinance"], (1, 2))


HEADERS = {
    "Cash": ["id", "label", "currency", "balance", "as_of"],
    "Holdings": ["id", "label", "ticker", "currency", "quantity", "avg_cost", "asset_class", "price", "price_as_of", "source", "as_of"],
    "Liabilities": ["id", "label", "currency", "balance", "as_of"],
    "OtherAssets": ["id", "label", "currency", "balance", "as_of"],
    "FX": ["currency", "rate", "as_of", "source"],
    "Closes": ["ticker", "currency", "price", "as_of", "source", "valid_through"],
    "History": ["month", "kind", "id", "label", "currency", "balance", "quantity", "avg_cost", "ticker", "asset_class", "as_of"],
    "Coverage": ["month", "cash", "holding", "liability", "other"],
}


def holding_version(row):
    keys = ["id", "label", "ticker", "currency", "quantity", "avg_cost", "asset_class", "source", "as_of"]
    if row.get("source") != "googlefinance":
        keys += ["price", "price_as_of"]
    return hashlib.sha256(json.dumps({key: str(row.get(key, "")).strip() for key in keys}, sort_keys=True).encode()).hexdigest()
