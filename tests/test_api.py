def test_data_entry_and_advisor_sse_flow(client, fake_provider):
    r = client.post("/api/data/accounts", json={"name": "통장", "kind": "checking", "balance": "3000000",
                                                "balance_as_of": "2026-10-01"})
    assert r.status_code == 201
    conv = client.post("/api/advisor/conversations", json={"title": "테스트"}).json()

    preview = client.post("/api/advisor/context/preview", json={"message": "현재 내 순자산은?"}).json()
    assert "financial" in preview["categories"] and preview["context_snapshot_id"] is None

    with client.stream("POST", f"/api/advisor/conversations/{conv['id']}/messages",
                       json={"message": "현재 내 순자산은?"}) as resp:
        body = "".join(resp.iter_text())
    assert "event: context" in body and "event: done" in body

    detail = client.get(f"/api/advisor/conversations/{conv['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    snap_id = detail["messages"][1]["context_snapshot_id"]
    snap = client.get(f"/api/advisor/snapshots/{snap_id}").json()
    assert any(r.get("table") == "accounts" for r in snap["record_references"])

    # Balance changes after the consultation: the snapshot keeps the old basis.
    client.put("/api/data/accounts/1", json={"name": "통장", "kind": "checking", "balance": "1",
                                             "balance_as_of": "2026-10-17"})
    cmp = client.get(f"/api/advisor/snapshots/{snap_id}/compare").json()
    assert "get_accounts_summary" in cmp["changed_sections"]

    assert client.delete(f"/api/advisor/conversations/{conv['id']}").status_code == 204
    assert client.get(f"/api/advisor/snapshots/{snap_id}").status_code == 404


def test_goal_values_accept_and_preserve_free_form_text(client):
    payload = {
        "title": "하프 마라톤 목표",
        "category": "personal",
        "target_value": "1시간 35분 이내",
        "current_value": "1시간 48분",
        "unit": "기록",
    }
    created = client.post("/api/data/goals", json=payload)
    assert created.status_code == 201
    assert created.json()["target_value"] == payload["target_value"]
    assert created.json()["current_value"] == payload["current_value"]
    assert client.get("/api/data/goals").json()[0]["target_value"] == payload["target_value"]


def test_ai_provider_status_never_exposes_tokens(client):
    r = client.get("/api/settings/ai-provider").json()
    assert r["connected"] is False and r["provider"] == "chatgpt_plan"
    login = client.post("/api/settings/ai-provider/chatgpt/login").json()
    assert login["authorize_url"].startswith("https://auth.openai.com/api/accounts/authorize?")


def test_privacy_settings_roundtrip(client):
    assert client.put("/api/settings/privacy", json={"excluded_categories": ["health"]}).status_code == 200
    assert client.get("/api/settings/privacy").json() == {"excluded_categories": ["health"]}


def test_dashboard_summary_uses_backend_calculation(client):
    from app.modules.finance.clock import local_today
    client.post("/api/data/accounts", json={"name": "통장", "kind": "checking", "balance": "3000000",
                                            "balance_as_of": local_today().isoformat()})
    incomplete = client.get("/api/dashboard/summary").json()
    assert incomplete["data"]["get_accounts_summary"]["computed"]["net_worth"]["net_worth"] is None
    # Unentered asset/debt categories are unknown until the user confirms coverage.
    assert client.put("/api/finance/coverage", json={"kinds": ["cash", "holding", "liability", "other"]}).status_code == 200
    s = client.get("/api/dashboard/summary").json()
    assert s["data"]["get_accounts_summary"]["computed"]["net_worth"]["net_worth"] == "3000000.00"
    assert "get_profile" not in s["data"]


def test_timestamps_are_serialized_with_utc_offset(client):
    conv = client.post("/api/advisor/conversations", json={"title": "t"}).json()
    assert conv["created_at"].endswith(("Z", "+00:00"))


def test_openapi_operation_ids_are_unique():
    # orval names client functions by operationId; a duplicate silently drops one of the endpoints.
    import warnings

    from app.main import app

    app.openapi_schema = None
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        spec = app.openapi()
    ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids))


def test_all_day_calendar_event_round_trips_and_needs_an_end(client):
    body = {"title": "연휴", "all_day": True, "starts_at": "2026-10-16T15:00:00Z", "ends_at": "2026-10-18T15:00:00Z"}
    created = client.post("/api/data/calendar-events", json=body)
    assert created.status_code == 201
    assert created.json()["all_day"] is True
    assert client.post("/api/data/calendar-events", json={**body, "ends_at": None}).status_code == 422
    assert client.post("/api/data/calendar-events", json={"title": "회의", "starts_at": "2026-10-18T05:00:00Z"}).json()["all_day"] is False
