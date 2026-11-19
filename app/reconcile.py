import calendar
from collections import Counter
from datetime import date

from app.invoices import invoices_between

VERDICTS = ["MATCHED", "DUE_DAY_DRIFT", "DOUBLE_CHARGE_RISK", "MISSING_FROM_LEDGER", "DECLINED"]


def find_row_errors(month, rows, agreements, plans):
    """One {gateway_txn_id, code} per broken rule per row. Empty list means all good."""
    errors = []
    txn_counts = Counter(row["gateway_txn_id"] for row in rows)
    for row in rows:
        txn = row["gateway_txn_id"]
        if txn_counts[txn] > 1:
            errors.append({"gateway_txn_id": txn, "code": "DUPLICATE_TXN"})
        if not row["attempted_on"].startswith(month + "-"):
            errors.append({"gateway_txn_id": txn, "code": "ROW_OUTSIDE_MONTH"})
        agreement = agreements.get(row["agreement_id"])
        if agreement and plans[agreement["plan_id"]]["currency"] != row["currency"]:
            errors.append({"gateway_txn_id": txn, "code": "CURRENCY_MISMATCH"})
    return errors


def expected_invoices(month, agreements, plans):
    """Every invoice, from every agreement, due in this month."""
    year, month_no = int(month[:4]), int(month[5:])
    first_day = date(year, month_no, 1)
    last_day = date(year, month_no, calendar.monthrange(year, month_no)[1])
    expected = []
    for agreement in agreements.values():
        for invoice in invoices_between(agreement, plans[agreement["plan_id"]], first_day, last_day):
            expected.append({**invoice, "agreement_id": agreement["id"]})
    return expected


def pick_invoice(row, expected):
    """The invoice a settled row pays for: same agreement, total within 1 minor unit,
    earliest due date. Each row picks on its own, so row order never matters."""
    candidates = [
        invoice for invoice in expected
        if invoice["agreement_id"] == row["agreement_id"] and abs(invoice["total"] - row["amount"]) <= 1
    ]
    return min(candidates, key=lambda invoice: invoice["due_date"]) if candidates else None


def reconcile(rows, expected):
    links = [pick_invoice(row, expected) if row["status"] == "SETTLED" else None for row in rows]

    # How many settled rows point at each invoice
    link_counts = Counter((inv["agreement_id"], inv["invoice_no"]) for inv in links if inv)

    summary = {verdict: 0 for verdict in VERDICTS}
    result_rows = []
    for row, invoice in zip(rows, links):
        if row["status"] == "DECLINED":
            verdict = "DECLINED"
        elif invoice is None:
            verdict = "MISSING_FROM_LEDGER"
        elif link_counts[(invoice["agreement_id"], invoice["invoice_no"])] > 1:
            verdict = "DOUBLE_CHARGE_RISK"
        elif row["attempted_on"] == invoice["due_date"]:
            verdict = "MATCHED"
        else:
            verdict = "DUE_DAY_DRIFT"
        summary[verdict] += 1
        result_rows.append({
            "gateway_txn_id": row["gateway_txn_id"],
            "verdict": verdict,
            "invoice": {"agreement_id": invoice["agreement_id"], "invoice_no": invoice["invoice_no"]} if invoice else None,
        })

    # Declined rows never link, so an invoice only they touched ends up here too
    unmatched = [
        {key: inv[key] for key in ("agreement_id", "invoice_no", "due_date", "total", "currency")}
        for inv in expected
        if (inv["agreement_id"], inv["invoice_no"]) not in link_counts
    ]
    unmatched.sort(key=lambda inv: (inv["due_date"], inv["agreement_id"], inv["invoice_no"]))

    return {"summary": summary, "rows": result_rows, "unmatched_invoices": unmatched}
