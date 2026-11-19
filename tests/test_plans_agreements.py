import pytest


def error_code(res):
    return res.json()["error"]["code"]


def make_plan(client, **overrides):
    body = {"id": "anytime-sa", "country": "SA", "monthly": 29900, "joining_fee": 0, **overrides}
    return client.post("/plans", json=body)


def make_member(client, country="SA", phone="0551234567"):
    return client.post("/members", json={"name": "Noura", "country": country, "phone": phone}).json()


def make_agreement(client, member_id, plan_id="anytime-sa", start_date="2026-09-20", due_day=1):
    body = {"member_id": member_id, "plan_id": plan_id, "start_date": start_date, "due_day": due_day}
    return client.post("/agreements", json=body)


def test_create_plan_adds_currency(client):
    res = make_plan(client)
    assert res.status_code == 201
    assert res.json() == {"id": "anytime-sa", "country": "SA", "currency": "SAR", "monthly": 29900, "joining_fee": 0}


def test_duplicate_plan(client):
    make_plan(client)
    res = make_plan(client, country="AE")
    assert res.status_code == 409
    assert error_code(res) == "PLAN_EXISTS"


@pytest.mark.parametrize("overrides", [
    {"monthly": 0},
    {"monthly": -5},
    {"monthly": "29900"},
    {"monthly": 299.5},
    {"monthly": 29900.0},
    {"monthly": True},
    {"joining_fee": -1},
    {"joining_fee": None},
    {"country": "KW"},
    {"id": ""},
    {"id": 7},
])
def test_bad_plan_is_validation(client, overrides):
    res = make_plan(client, **overrides)
    assert res.status_code == 422
    assert error_code(res) == "VALIDATION"


def test_missing_joining_fee_is_validation(client):
    res = client.post("/plans", json={"id": "p", "country": "SA", "monthly": 100})
    assert error_code(res) == "VALIDATION"


def test_create_agreement(client):
    make_plan(client)
    member = make_member(client)
    res = make_agreement(client, member["id"])
    assert res.status_code == 201
    body = res.json()
    assert body["id"]
    assert body["member_id"] == member["id"]
    assert (body["plan_id"], body["start_date"], body["due_day"]) == ("anytime-sa", "2026-09-20", 1)


def test_agreement_business_errors(client):
    make_plan(client)
    make_plan(client, id="anytime-bh", country="BH")
    member = make_member(client)
    assert error_code(make_agreement(client, "mem_nope")) == "UNKNOWN_MEMBER"
    assert error_code(make_agreement(client, member["id"], plan_id="nope")) == "UNKNOWN_PLAN"
    assert error_code(make_agreement(client, member["id"], plan_id="anytime-bh")) == "PLAN_COUNTRY_MISMATCH"


@pytest.mark.parametrize("overrides", [
    {"due_day": 0},
    {"due_day": 32},
    {"due_day": "1"},
    {"start_date": "2026-02-30"},
    {"start_date": "20260920"},
    {"start_date": "2026-09-20T00:00:00"},
    {"start_date": "2026-9-20"},
    {"start_date": 20260920},
])
def test_bad_agreement_is_validation(client, overrides):
    make_plan(client)
    member = make_member(client)
    res = make_agreement(client, member["id"], **overrides)
    assert res.status_code == 422
    assert error_code(res) == "VALIDATION"


def test_list_invoices(client):
    make_plan(client)
    agreement = make_agreement(client, make_member(client)["id"]).json()
    res = client.get(f"/agreements/{agreement['id']}/invoices?from=2026-09-01&to=2026-12-31")
    assert res.status_code == 200
    invoices = res.json()
    assert [i["invoice_no"] for i in invoices] == [1, 2, 3, 4]
    assert invoices[0]["total"] == 12607


def test_invoices_unknown_agreement(client):
    res = client.get("/agreements/agr_nope/invoices?from=2026-09-01&to=2026-12-31")
    assert res.status_code == 404
    assert error_code(res) == "NOT_FOUND"


@pytest.mark.parametrize("query,code", [
    ("from=2026-09-02&to=2026-09-01", "INVALID_RANGE"),
    ("from=2026-01-01&to=2027-01-03", "INVALID_RANGE"),   # 367 days
    ("from=2026-01-01&to=2027-01-02", None),              # exactly 366 days is fine
    ("from=2026-01-01", "VALIDATION"),
    ("from=2026-01-01&to=2026-13-01", "VALIDATION"),
    ("from=20260101&to=2026-02-01", "VALIDATION"),
])
def test_invoice_range_rules(client, query, code):
    make_plan(client)
    agreement = make_agreement(client, make_member(client)["id"]).json()
    res = client.get(f"/agreements/{agreement['id']}/invoices?{query}")
    if code is None:
        assert res.status_code == 200
    else:
        assert res.status_code == 422
        assert error_code(res) == code
