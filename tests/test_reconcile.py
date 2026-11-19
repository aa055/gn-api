import random

import pytest


def error_code(res):
    return res.json()["error"]["code"]


@pytest.fixture
def setup(client):
    """Two agreements, each with invoice 2 due 1 Oct 2026:
    Saudi (total 34385 SAR) and Bahrain (net 24500 + 10% VAT = 26950 BHD)."""
    client.post("/plans", json={"id": "sa", "country": "SA", "monthly": 29900, "joining_fee": 0})
    client.post("/plans", json={"id": "bh", "country": "BH", "monthly": 24500, "joining_fee": 0})
    sa_member = client.post("/members", json={"name": "Noura", "country": "SA", "phone": "0551234567"}).json()
    bh_member = client.post("/members", json={"name": "Ali", "country": "BH", "phone": "31234567"}).json()
    sa = client.post("/agreements", json={"member_id": sa_member["id"], "plan_id": "sa",
                                          "start_date": "2026-09-20", "due_day": 1}).json()
    bh = client.post("/agreements", json={"member_id": bh_member["id"], "plan_id": "bh",
                                          "start_date": "2026-09-15", "due_day": 1}).json()
    return sa["id"], bh["id"]


def row(txn, agreement_id, amount, currency, status="SETTLED", attempted_on="2026-10-01"):
    return {"gateway_txn_id": txn, "agreement_id": agreement_id, "amount": amount,
            "currency": currency, "status": status, "attempted_on": attempted_on}


def run(client, rows, month="2026-10"):
    return client.post("/reconciliation/runs", json={"month": month, "rows": rows})


def test_brief_example(client, setup):
    sa, bh = setup
    res = run(client, [
        row("T-88121", sa, 34385, "SAR"),
        row("T-88122", bh, 26950, "BHD", status="DECLINED", attempted_on="2026-10-02"),
    ])
    assert res.status_code == 201
    body = res.json()
    assert body["month"] == "2026-10"
    assert body["summary"] == {"MATCHED": 1, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                               "MISSING_FROM_LEDGER": 0, "DECLINED": 1}
    assert body["rows"] == [
        {"gateway_txn_id": "T-88121", "verdict": "MATCHED", "invoice": {"agreement_id": sa, "invoice_no": 2}},
        {"gateway_txn_id": "T-88122", "verdict": "DECLINED", "invoice": None},
    ]
    assert body["unmatched_invoices"] == [
        {"agreement_id": bh, "invoice_no": 2, "due_date": "2026-10-01", "total": 26950, "currency": "BHD"},
    ]
    assert client.get(f"/reconciliation/runs/{body['id']}").json() == body


def test_drift_and_tolerance(client, setup):
    sa, _ = setup
    body = run(client, [row("T-1", sa, 34386, "SAR", attempted_on="2026-10-03")]).json()
    assert body["rows"][0]["verdict"] == "DUE_DAY_DRIFT"
    assert body["rows"][0]["invoice"]["invoice_no"] == 2


def test_two_off_is_missing(client, setup):
    sa, _ = setup
    body = run(client, [row("T-1", sa, 34387, "SAR")]).json()
    assert body["rows"][0] == {"gateway_txn_id": "T-1", "verdict": "MISSING_FROM_LEDGER", "invoice": None}


def test_unknown_agreement_is_missing(client, setup):
    body = run(client, [row("T-1", "agr_ghost", 100, "USD")]).json()
    assert body["rows"][0]["verdict"] == "MISSING_FROM_LEDGER"


def test_double_charge_marks_every_row(client, setup):
    sa, _ = setup
    body = run(client, [row("T-1", sa, 34385, "SAR"), row("T-2", sa, 34384, "SAR", attempted_on="2026-10-04")]).json()
    assert [r["verdict"] for r in body["rows"]] == ["DOUBLE_CHARGE_RISK", "DOUBLE_CHARGE_RISK"]
    assert body["summary"]["DOUBLE_CHARGE_RISK"] == 2


def test_earliest_due_date_wins_when_two_invoices_fit(client):
    # Start 5 Sep, due day 20: invoice 1 is 15/31 of 10000 = 4839, plus a 5161
    # joining fee makes net 10000, the same as invoice 2 on 20 Sep. Both total 10500.
    client.post("/plans", json={"id": "ae", "country": "AE", "monthly": 10000, "joining_fee": 5161})
    member = client.post("/members", json={"name": "A", "country": "AE", "phone": "0501234567"}).json()
    agr = client.post("/agreements", json={"member_id": member["id"], "plan_id": "ae",
                                           "start_date": "2026-09-05", "due_day": 20}).json()
    body = run(client, [row("T-1", agr["id"], 10500, "AED", attempted_on="2026-09-20")], month="2026-09").json()
    assert body["rows"][0]["invoice"]["invoice_no"] == 1
    assert body["rows"][0]["verdict"] == "DUE_DAY_DRIFT"  # paid 20 Sep, invoice 1 was due 5 Sep
    assert [i["invoice_no"] for i in body["unmatched_invoices"]] == [2]


def test_declined_only_invoice_is_unmatched(client, setup):
    sa, bh = setup
    body = run(client, [row("T-1", sa, 34385, "SAR", status="DECLINED")]).json()
    assert {i["agreement_id"] for i in body["unmatched_invoices"]} == {sa, bh}


def test_unmatched_sorted_and_empty_rows_ok(client, setup):
    body = run(client, []).json()
    unmatched = body["unmatched_invoices"]
    assert unmatched == sorted(unmatched, key=lambda i: (i["due_date"], i["agreement_id"], i["invoice_no"]))
    assert len(unmatched) == 2
    assert body["summary"] == {v: 0 for v in body["summary"]}


def test_row_order_does_not_change_the_result(client, setup):
    sa, bh = setup
    rows = [
        row("T-1", sa, 34385, "SAR"),
        row("T-2", sa, 34385, "SAR", attempted_on="2026-10-09"),
        row("T-3", bh, 26950, "BHD", attempted_on="2026-10-02"),
        row("T-4", "agr_ghost", 5, "SAR"),
        row("T-5", bh, 26950, "BHD", status="DECLINED"),
    ]
    first = run(client, rows).json()
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    second = run(client, shuffled).json()
    by_txn = lambda body: {r["gateway_txn_id"]: r for r in body["rows"]}
    assert by_txn(first) == by_txn(second)
    assert first["summary"] == second["summary"]
    assert first["unmatched_invoices"] == second["unmatched_invoices"]


def test_invalid_rows_lists_every_problem(client, setup):
    sa, _ = setup
    res = run(client, [
        row("T-1", sa, 34385, "SAR"),
        row("T-1", sa, 34385, "BHD", attempted_on="2026-11-01"),
        row("T-2", "agr_ghost", 1, "XXX"),    # unknown agreement skips the currency check
    ])
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "INVALID_ROWS"
    assert sorted((e["gateway_txn_id"], e["code"]) for e in error["errors"]) == [
        ("T-1", "CURRENCY_MISMATCH"),
        ("T-1", "DUPLICATE_TXN"),
        ("T-1", "DUPLICATE_TXN"),
        ("T-1", "ROW_OUTSIDE_MONTH"),
    ]


@pytest.mark.parametrize("body", [
    {"rows": []},
    {"month": "2026-13", "rows": []},
    {"month": "2026-1", "rows": []},
    {"month": "2026-10"},
    {"month": "2026-10", "rows": [{"gateway_txn_id": "T", "agreement_id": "a", "amount": 0,
                                   "currency": "SAR", "status": "SETTLED", "attempted_on": "2026-10-01"}]},
    {"month": "2026-10", "rows": [{"gateway_txn_id": "T", "agreement_id": "a", "amount": 5,
                                   "currency": "SAR", "status": "PENDING", "attempted_on": "2026-10-01"}]},
    {"month": "2026-10", "rows": [{"gateway_txn_id": "T", "agreement_id": "a", "amount": "5",
                                   "currency": "SAR", "status": "SETTLED", "attempted_on": "2026-10-01"}]},
    {"month": "2026-10", "rows": [{"gateway_txn_id": "T", "amount": 5,
                                   "currency": "SAR", "status": "SETTLED", "attempted_on": "2026-10-01"}]},
])
def test_malformed_run_is_validation(client, body):
    res = client.post("/reconciliation/runs", json=body)
    assert res.status_code == 422
    assert error_code(res) == "VALIDATION"


def test_unknown_run(client):
    res = client.get("/reconciliation/runs/run_nope")
    assert res.status_code == 404
    assert error_code(res) == "NOT_FOUND"
