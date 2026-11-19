# Notes

A small FastAPI service for Gulf gym memberships: members with normalised phones, plans, agreements, computed invoices, and gateway reconciliation.

## How to run

```bash
docker build -t app .
docker run -p 8080:8080 app          # API on http://localhost:8080, GET /health -> 200
docker build --target test .         # runs the test suite (pytest) inside the build
```

Without Docker:

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (bin/ on macOS/Linux)
.venv/Scripts/python -m pytest -q
.venv/Scripts/uvicorn app.main:app --port 8080
```

## Layout

| File | What it does |
|---|---|
| `app/main.py` | Routes, request models, in-memory store with one lock, error handlers |
| `app/countries.py` | The AE / SA / BH table (dial code, currency, VAT, mobile shape) |
| `app/phones.py` | Clean a phone and read it as international or national |
| `app/invoices.py` | Due dates, proration, half-up rounding, the invoice schedule |
| `app/reconcile.py` | Row validation, expected invoices, matching and verdicts |
| `tests/` | Unit tests for the pure modules and API tests through FastAPI's TestClient |

All money is integer minor units and every calculation uses integer maths (no floats, no `round()`).
Storage is plain dicts in memory. Uvicorn runs with one worker so every request sees the same data.

## What I skipped

- Persistence: data is gone when the container stops. The brief asks for each run to start empty.
- Extra endpoints like `GET /members/{id}` or listing plans. Only what the brief describes is built.

## Assumptions

- Malformed input (`422 VALIDATION`) is checked before any business rule, so a missing `name` wins over a bad phone.
- On `GET /agreements/{id}/invoices`, a malformed `from`/`to` is `VALIDATION` first. Then an unknown agreement is `404`. Then `INVALID_RANGE`.
- On `POST /agreements` the checks run in the brief's order: `UNKNOWN_MEMBER`, `UNKNOWN_PLAN`, `PLAN_COUNTRY_MISMATCH`.
- An agreement `start_date` outside years 2–9998 is `422 VALIDATION`. The first invoice needs the due dates a month either side of the start, and Python dates only cover years 1–9999.
- Only ASCII `0-9` count as digits in a phone. Arabic-Indic digits are `INVALID_PHONE`.
- "Spaces" means the space character only. Tabs or other whitespace in a phone are `INVALID_PHONE`.
- An unencoded `+` in a lookup query arrives as a space. It's stripped, and the number is then read as dial code + mobile, so it still works.
- On lookup, a national number that fits no country's shape is `INVALID_PHONE` (not `PHONE_NEEDS_COUNTRY`).
- `country` must be exactly `AE`, `SA` or `BH`. Lowercase or anything else is `VALIDATION`, in bodies and in the lookup query.
- `name` is trimmed with Python's `str.strip()` and its length is counted in characters.
- Wrong JSON types are `VALIDATION`: `"100"`, `100.0` and `true` are not integers, and `123` is not a string.
- `joining_fee` is required on `POST /plans`.
- A plan `id` must be a non-empty string.
- Unknown extra fields in a JSON body are ignored.
- `to` exactly 366 days after `from` is allowed, and 367 is `INVALID_RANGE`.
- A gateway row's `currency` can be any string. If its agreement exists and the plan's currency differs, it's `CURRENCY_MISMATCH`.
- All three row checks apply to `DECLINED` rows too.
- A row that breaks several rules gets one `errors` entry per rule. Each copy of a duplicated `gateway_txn_id` gets its own `DUPLICATE_TXN` entry.
- `rows: []` is a valid run. Every expected invoice comes back unmatched.
- A reconciliation run is a snapshot. `GET` returns exactly what `POST` returned, even if agreements were added afterwards.
- A run holds the store lock while it computes, so agreements created at the same moment are either fully in or fully out.
- Unknown routes are `404 NOT_FOUND` and wrong methods are `405 METHOD_NOT_ALLOWED`, both in the standard error shape.
- Generated ids are `mem_`, `agr_` and `run_` followed by a random UUID hex.
