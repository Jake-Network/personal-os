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


def test_ai_provider_status_never_exposes_tokens(client):
    r = client.get("/api/settings/ai-provider").json()
    assert r["connected"] is False and r["provider"] == "chatgpt_plan"
    login = client.post("/api/settings/ai-provider/chatgpt/login").json()
    assert login["authorize_url"].startswith("https://auth.openai.com/api/accounts/authorize?")


def test_privacy_settings_roundtrip(client):
    assert client.put("/api/settings/privacy", json={"excluded_categories": ["health"]}).status_code == 200
    assert client.get("/api/settings/privacy").json() == {"excluded_categories": ["health"]}


def test_dashboard_summary_uses_backend_calculation(client):
    client.post("/api/data/accounts", json={"name": "통장", "kind": "checking", "balance": "3000000",
                                            "balance_as_of": "2026-10-01"})
    s = client.get("/api/dashboard/summary").json()
    assert s["data"]["get_accounts_summary"]["computed"]["net_worth"]["net_worth"] == "3000000.00"
    assert "get_profile" not in s["data"]


def test_timestamps_are_serialized_with_utc_offset(client):
    conv = client.post("/api/advisor/conversations", json={"title": "t"}).json()
    assert conv["created_at"].endswith(("Z", "+00:00"))
