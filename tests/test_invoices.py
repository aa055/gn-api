from datetime import date

from app.invoices import due_date_in, invoices_between, round_half_up

SA_PLAN = {"id": "anytime-sa", "country": "SA", "monthly": 29900, "joining_fee": 0}
AE_PLAN = {"id": "anytime-ae", "country": "AE", "monthly": 24900, "joining_fee": 9900}


def agreement(start_date, due_day):
    return {"id": "agr_1", "start_date": start_date, "due_day": due_day}


def test_round_half_up():
    assert round_half_up(5, 2) == 3          # 2.5 -> 3 (Python's round() gives 2)
    assert round_half_up(1, 2) == 1          # 0.5 -> 1
    assert round_half_up(328900, 30) == 10963   # 10963.33
    assert round_half_up(164445, 100) == 1644   # 1644.45
    assert round_half_up(1235, 10) == 124       # 123.5


def test_due_day_31_clamps_but_keeps_its_anchor():
    assert due_date_in(2026, 4, 31) == date(2026, 4, 30)
    assert due_date_in(2027, 2, 31) == date(2027, 2, 28)
    assert due_date_in(2028, 2, 31) == date(2028, 2, 29)  # leap year
    assert due_date_in(2027, 3, 31) == date(2027, 3, 31)


def test_worked_example_1_saudi():
    result = invoices_between(agreement("2026-09-20", 1), SA_PLAN, date(2026, 9, 1), date(2026, 12, 31))
    assert result[0] == {
        "invoice_no": 1, "due_date": "2026-09-20", "kind": "FIRST",
        "proration": {"days": 11, "cycle_days": 30},
        "net": 10963, "vat": 1644, "total": 12607, "currency": "SAR",
    }
    assert result[1] == {
        "invoice_no": 2, "due_date": "2026-10-01", "kind": "MONTHLY", "proration": None,
        "net": 29900, "vat": 4485, "total": 34385, "currency": "SAR",
    }
    assert [i["due_date"] for i in result] == ["2026-09-20", "2026-10-01", "2026-11-01", "2026-12-01"]


def test_worked_example_2_uae_with_joining_fee():
    result = invoices_between(agreement("2026-09-05", 20), AE_PLAN, date(2026, 9, 1), date(2026, 9, 30))
    first, second = result
    assert first["proration"] == {"days": 15, "cycle_days": 31}
    assert (first["net"], first["vat"], first["total"]) == (21948, 1097, 23045)
    assert second["invoice_no"] == 2
    assert second["due_date"] == "2026-09-20"  # September has two invoices


def test_start_on_a_due_date_is_full_price():
    first = invoices_between(agreement("2026-10-01", 1), SA_PLAN, date(2026, 10, 1), date(2026, 10, 31))[0]
    assert first["proration"] == {"days": 31, "cycle_days": 31}
    assert first["net"] == 29900


def test_start_on_clamped_due_date_is_full_price():
    # 28 Feb 2027 is the due date for due day 31, so N is 31 March
    first = invoices_between(agreement("2027-02-28", 31), SA_PLAN, date(2027, 2, 1), date(2027, 2, 28))[0]
    assert first["proration"] == {"days": 31, "cycle_days": 31}


def test_due_day_31_schedule_across_short_months():
    result = invoices_between(agreement("2027-01-15", 31), SA_PLAN, date(2027, 1, 1), date(2027, 5, 31))
    assert [i["due_date"] for i in result] == [
        "2027-01-15", "2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30", "2027-05-31",
    ]
    assert result[0]["proration"] == {"days": 16, "cycle_days": 31}  # 31 Dec -> 31 Jan


def test_invoice_numbers_keep_counting_inside_a_later_range():
    result = invoices_between(agreement("2026-09-20", 1), SA_PLAN, date(2026, 12, 1), date(2027, 1, 31))
    assert [(i["invoice_no"], i["due_date"]) for i in result] == [(4, "2026-12-01"), (5, "2027-01-01")]


def test_range_before_start_is_empty():
    assert invoices_between(agreement("2026-09-20", 1), SA_PLAN, date(2026, 1, 1), date(2026, 9, 19)) == []


def test_bahrain_vat_stays_in_fils():
    plan = {"id": "bh", "country": "BH", "monthly": 5790, "joining_fee": 0}
    monthly = invoices_between(agreement("2026-10-01", 1), plan, date(2026, 11, 1), date(2026, 11, 1))[0]
    assert (monthly["vat"], monthly["total"], monthly["currency"]) == (579, 6369, "BHD")
