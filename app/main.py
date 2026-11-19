import re
import threading
import uuid
from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import invoices, phones, reconcile
from app.countries import COUNTRIES

app = FastAPI(title="Gymnation billing API")

Country = Literal["AE", "SA", "BH"]


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# In-memory store. Every run starts empty, as the brief asks.
# Routes are plain `def`, so FastAPI runs them on a thread pool and two
# requests really can interleave. Any "check, then insert" goes under this lock.
# ---------------------------------------------------------------------------
lock = threading.Lock()
members = {}       # member_id -> member
phone_index = {}   # "+966551234567" -> member_id
plans = {}         # plan_id -> plan
agreements = {}    # agreement_id -> agreement
runs = {}          # run_id -> stored reconciliation response


# ---------------------------------------------------------------------------
# Errors. Every error leaves the API as {"error": {"code": ..., "message": ...}}.
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status, code, message, **extra):
        self.status = status
        self.body = {"code": code, "message": message, **extra}


@app.exception_handler(ApiError)
def handle_api_error(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"error": exc.body})


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError):
    # Missing field, wrong type, bad date, out of range, broken JSON...
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    message = f"{where}: {first['msg']}"
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION", "message": message}})


@app.exception_handler(StarletteHTTPException)
def handle_http_error(request: Request, exc: StarletteHTTPException):
    # Unknown routes and wrong methods, so they also use our error shape
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    code = codes.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": str(exc.detail)}})


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL", "message": "Something went wrong"}})


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Request bodies. strict=True stops Pydantic quietly turning "100" or true
# into 100: a wrong type has to be a 422 VALIDATION.
# ---------------------------------------------------------------------------
class Strict(BaseModel):
    model_config = ConfigDict(strict=True)


def example(**values):
    # Pre-fills the request body on the Swagger page (/docs). No effect on validation.
    return ConfigDict(json_schema_extra={"examples": [values]})


def check_date(value):
    # Only YYYY-MM-DD. fromisoformat alone would also accept "20260920".
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    date.fromisoformat(value)  # raises on impossible dates like 2026-02-30
    return value


DateText = Annotated[str, AfterValidator(check_date)]


class MemberIn(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    country: Country
    phone: str
    model_config = example(name="Noura Al Harbi", country="SA", phone="055 123 4567")


class PlanIn(Strict):
    id: Annotated[str, StringConstraints(min_length=1)]
    country: Country
    monthly: Annotated[int, Field(gt=0)]
    joining_fee: Annotated[int, Field(ge=0)]
    model_config = example(id="anytime-sa", country="SA", monthly=29900, joining_fee=0)


class AgreementIn(Strict):
    member_id: str
    plan_id: str
    start_date: DateText
    due_day: Annotated[int, Field(ge=1, le=31)]
    model_config = example(member_id="PASTE_MEMBER_ID", plan_id="anytime-sa", start_date="2026-09-20", due_day=1)


def check_month(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) or not 1 <= int(value[5:]) <= 12:
        raise ValueError("month must be YYYY-MM")
    return value


class GatewayRow(Strict):
    gateway_txn_id: str
    agreement_id: str
    amount: Annotated[int, Field(gt=0)]
    currency: str
    status: Literal["SETTLED", "DECLINED"]
    attempted_on: DateText


class RunIn(Strict):
    month: Annotated[str, AfterValidator(check_month)]
    rows: list[GatewayRow]
    model_config = example(month="2026-10", rows=[{
        "gateway_txn_id": "T-88121", "agreement_id": "PASTE_AGREEMENT_ID", "amount": 34385,
        "currency": "SAR", "status": "SETTLED", "attempted_on": "2026-10-01"}])


# ---------------------------------------------------------------------------
# Part 1: members and phones
# ---------------------------------------------------------------------------
@app.post("/members", status_code=201)
def create_member(body: MemberIn):
    cleaned = phones.clean(body.phone)
    if cleaned is None:
        raise ApiError(422, "INVALID_PHONE", "Phone has characters other than digits and a leading +")

    # International numbers can be from any of our countries (foreign SIMs are fine).
    # National numbers are read in the member's own country.
    international = phones.read_international(cleaned)
    phone = international[1] if international else phones.read_national(cleaned, body.country)
    if phone is None:
        raise ApiError(422, "INVALID_PHONE", "Not a valid AE, SA or BH mobile number")

    with lock:
        if phone in phone_index:
            raise ApiError(409, "PHONE_TAKEN", "Another member already has this phone",
                           existing_member_id=phone_index[phone])
        member = {"id": new_id("mem"), "name": body.name, "country": body.country, "phone": phone}
        members[member["id"]] = member
        phone_index[phone] = member["id"]
    return member


@app.get("/members/lookup")
def lookup_member(phone: Annotated[str, Query(openapi_examples={"demo": {"value": "966551234567"}})],
                  country: Optional[Country] = None):
    cleaned = phones.clean(phone)
    if cleaned is None:
        raise ApiError(422, "INVALID_PHONE", "Phone has characters other than digits and a leading +")

    international = phones.read_international(cleaned)
    if international:
        dial_country, e164 = international
        if country and country != dial_country:
            raise ApiError(422, "PHONE_COUNTRY_MISMATCH", f"Number is from {dial_country}, not {country}")
    else:
        # A national number like 0551234567 is valid in both AE and SA,
        # so we can't look it up without knowing which country is meant.
        if not any(phones.read_national(cleaned, c) for c in COUNTRIES):
            raise ApiError(422, "INVALID_PHONE", "Not a valid AE, SA or BH mobile number")
        if country is None:
            raise ApiError(422, "PHONE_NEEDS_COUNTRY", "A national number needs a country")
        e164 = phones.read_national(cleaned, country)
        if e164 is None:
            raise ApiError(422, "INVALID_PHONE", f"Not a valid {country} mobile number")

    member_id = phone_index.get(e164)
    if member_id is None:
        raise ApiError(404, "NOT_FOUND", "No member has this phone")
    return members[member_id]


# ---------------------------------------------------------------------------
# Part 2: plans, agreements and the invoice schedule
# ---------------------------------------------------------------------------
@app.post("/plans", status_code=201)
def create_plan(body: PlanIn):
    plan = {
        "id": body.id,
        "country": body.country,
        "currency": COUNTRIES[body.country]["currency"],
        "monthly": body.monthly,
        "joining_fee": body.joining_fee,
    }
    with lock:
        if body.id in plans:
            raise ApiError(409, "PLAN_EXISTS", f"Plan {body.id} already exists")
        plans[body.id] = plan
    return plan


@app.post("/agreements", status_code=201)
def create_agreement(body: AgreementIn):
    member = members.get(body.member_id)
    if member is None:
        raise ApiError(422, "UNKNOWN_MEMBER", f"No member {body.member_id}")
    plan = plans.get(body.plan_id)
    if plan is None:
        raise ApiError(422, "UNKNOWN_PLAN", f"No plan {body.plan_id}")
    if plan["country"] != member["country"]:
        raise ApiError(422, "PLAN_COUNTRY_MISMATCH",
                       f"Plan is for {plan['country']} but the member is in {member['country']}")

    agreement = {
        "id": new_id("agr"),
        "member_id": body.member_id,
        "plan_id": body.plan_id,
        "start_date": body.start_date,
        "due_day": body.due_day,
    }
    agreements[agreement["id"]] = agreement
    return agreement


@app.get("/agreements/{agreement_id}/invoices")
def list_invoices(agreement_id: str,
                  date_from: Annotated[DateText, Query(alias="from", openapi_examples={"demo": {"value": "2026-09-01"}})],
                  date_to: Annotated[DateText, Query(alias="to", openapi_examples={"demo": {"value": "2026-12-31"}})]):
    agreement = agreements.get(agreement_id)
    if agreement is None:
        raise ApiError(404, "NOT_FOUND", f"No agreement {agreement_id}")

    date_from, date_to = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if date_to < date_from or (date_to - date_from).days > 366:
        raise ApiError(422, "INVALID_RANGE", "to must be on or after from, and at most 366 days later")

    return invoices.invoices_between(agreement, plans[agreement["plan_id"]], date_from, date_to)


# ---------------------------------------------------------------------------
# Part 3: reconciling the gateway file
# ---------------------------------------------------------------------------
@app.post("/reconciliation/runs", status_code=201)
def create_run(body: RunIn):
    rows = [row.model_dump() for row in body.rows]

    # Held for the whole run so a new agreement arriving mid-run can't change
    # the dict while we loop over it. A run never writes members or agreements.
    with lock:
        errors = reconcile.find_row_errors(body.month, rows, agreements, plans)
        if errors:
            raise ApiError(422, "INVALID_ROWS", "Some gateway rows are invalid", errors=errors)

        expected = reconcile.expected_invoices(body.month, agreements, plans)
        run = {"id": new_id("run"), "month": body.month, **reconcile.reconcile(rows, expected)}
        runs[run["id"]] = run
    return run


@app.get("/reconciliation/runs/{run_id}")
def get_run(run_id: str):
    run = runs.get(run_id)
    if run is None:
        raise ApiError(404, "NOT_FOUND", f"No reconciliation run {run_id}")
    return run
