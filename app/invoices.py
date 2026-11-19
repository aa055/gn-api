import calendar
from datetime import date

from app.countries import COUNTRIES


def due_date_in(year, month, due_day):
    """Due day 31 lands on 30 Apr, 28/29 Feb and 31 Mar: only the date clamps.
    We always start from the original due_day, so it never drifts down to 28."""
    days_in_month = calendar.monthrange(year, month)[1]
    return date(year, month, min(due_day, days_in_month))


def add_months(year, month, n):
    months = year * 12 + (month - 1) + n
    return months // 12, months % 12 + 1


def round_half_up(numerator, denominator):
    """numerator / denominator rounded half up, in whole minor units.
    Integer maths only: floats drift, and Python's round() rounds 2.5 down to 2."""
    return (2 * numerator + denominator) // (2 * denominator)


def make_invoice(invoice_no, due_date, kind, proration, net, country):
    vat = round_half_up(net * COUNTRIES[country]["vat_percent"], 100)
    return {
        "invoice_no": invoice_no,
        "due_date": due_date.isoformat(),
        "kind": kind,
        "proration": proration,
        "net": net,
        "vat": vat,
        "total": net + vat,
        "currency": COUNTRIES[country]["currency"],
    }


def invoices_between(agreement, plan, date_from, date_to):
    """Every invoice of the agreement whose due date is in [date_from, date_to].
    Numbering always counts from the very first invoice, not from date_from."""
    start = date.fromisoformat(agreement["start_date"])
    due_day = agreement["due_day"]

    # N: the first due date strictly after the start. P: the due date a month before N.
    n_year, n_month = start.year, start.month
    if due_date_in(n_year, n_month, due_day) <= start:
        n_year, n_month = add_months(n_year, n_month, 1)
    next_due = due_date_in(n_year, n_month, due_day)
    previous_due = due_date_in(*add_months(n_year, n_month, -1), due_day)

    result = []

    # Invoice 1: pay for the part of the first cycle that's used, plus the joining fee
    if date_from <= start <= date_to:
        days = (next_due - start).days
        cycle_days = (next_due - previous_due).days
        net = round_half_up(plan["monthly"] * days, cycle_days) + plan["joining_fee"]
        proration = {"days": days, "cycle_days": cycle_days}
        result.append(make_invoice(1, start, "FIRST", proration, net, plan["country"]))

    # Invoice 2 is due on N, then one per month after that. Agreements never end,
    # so we walk forward month by month until we pass date_to.
    invoice_no, year, month = 2, n_year, n_month
    while year <= 9999:
        due = due_date_in(year, month, due_day)
        if due > date_to:
            break
        if due >= date_from:
            result.append(make_invoice(invoice_no, due, "MONTHLY", None, plan["monthly"], plan["country"]))
        invoice_no += 1
        year, month = add_months(year, month, 1)

    return result
