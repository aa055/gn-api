import threading

import pytest

from app import main


def make_member(client, phone="055 123 4567", country="SA", name="Noura Al Harbi"):
    return client.post("/members", json={"name": name, "country": country, "phone": phone})


def error_code(res):
    return res.json()["error"]["code"]


def test_create_member_normalises_phone(client):
    res = make_member(client)
    assert res.status_code == 201
    body = res.json()
    assert body["phone"] == "+966551234567"
    assert body["name"] == "Noura Al Harbi"
    assert body["country"] == "SA"
    assert body["id"]


def test_name_is_trimmed(client):
    assert make_member(client, name="  Noura  ").json()["name"] == "Noura"


@pytest.mark.parametrize("name", ["", "   ", "x" * 121, 5, None])
def test_bad_name_is_validation(client, name):
    res = make_member(client, name=name)
    assert res.status_code == 422
    assert error_code(res) == "VALIDATION"


def test_name_of_120_chars_is_fine(client):
    assert make_member(client, name="x" * 120).status_code == 201


@pytest.mark.parametrize("body", [
    {"country": "SA", "phone": "0551234567"},                    # missing name
    {"name": "A", "country": "QA", "phone": "0551234567"},       # unknown country
    {"name": "A", "country": "sa", "phone": "0551234567"},       # lowercase
    {"name": "A", "country": "SA", "phone": 551234567},          # wrong type
])
def test_malformed_member_is_validation(client, body):
    res = client.post("/members", json=body)
    assert res.status_code == 422
    assert error_code(res) == "VALIDATION"


def test_broken_json_is_validation(client):
    res = client.post("/members", content="{not json", headers={"content-type": "application/json"})
    assert res.status_code == 422
    assert error_code(res) == "VALIDATION"


def test_foreign_sim_is_allowed(client):
    res = make_member(client, phone="+971 50 123 4567", country="SA")
    assert res.status_code == 201
    assert res.json()["phone"] == "+971501234567"


@pytest.mark.parametrize("phone,country", [
    ("0551234567", "BH"),        # national, but not Bahrain's shape
    ("31234567", "SA"),
    ("00966551234567", "SA"),    # 00 prefix
    ("055.123.4567", "SA"),
    ("+966 11 123 4567", "SA"),  # landline
    ("055123456", "SA"),         # too short
    ("", "SA"),
])
def test_invalid_phone(client, phone, country):
    res = make_member(client, phone=phone, country=country)
    assert res.status_code == 422
    assert error_code(res) == "INVALID_PHONE"


def test_same_phone_in_another_spelling_is_taken(client):
    first = make_member(client, phone="0551234567").json()
    res = make_member(client, phone="+966 55 123 4567", name="Someone Else")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "PHONE_TAKEN"
    assert res.json()["error"]["existing_member_id"] == first["id"]


def test_two_racing_writes_only_one_wins(client):
    results = []
    start = threading.Barrier(10)

    def write():
        start.wait()
        results.append(make_member(client, phone="0551234567").status_code)

    threads = [threading.Thread(target=write) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201] + [409] * 9
    assert len(main.members) == 1


@pytest.mark.parametrize("query", [
    "phone=966551234567",
    "phone=%2B966551234567",
    "phone=+966551234567",            # unencoded + arrives as a space
    "phone=055%20123%204567&country=SA",
])
def test_lookup_any_spelling(client, query):
    member = make_member(client).json()
    res = client.get(f"/members/lookup?{query}")
    assert res.status_code == 200
    assert res.json() == member


def test_lookup_national_without_country(client):
    res = client.get("/members/lookup?phone=0551234567")
    assert res.status_code == 422
    assert error_code(res) == "PHONE_NEEDS_COUNTRY"


def test_lookup_national_wrong_country_shape(client):
    res = client.get("/members/lookup?phone=0551234567&country=BH")
    assert error_code(res) == "INVALID_PHONE"


def test_lookup_invalid_national_without_country(client):
    res = client.get("/members/lookup?phone=0451234567")
    assert error_code(res) == "INVALID_PHONE"


def test_lookup_country_disagrees_with_dial_code(client):
    res = client.get("/members/lookup?phone=%2B966551234567&country=AE")
    assert res.status_code == 422
    assert error_code(res) == "PHONE_COUNTRY_MISMATCH"


def test_lookup_not_found(client):
    res = client.get("/members/lookup?phone=%2B966551234567")
    assert res.status_code == 404
    assert error_code(res) == "NOT_FOUND"


def test_lookup_missing_phone_or_bad_country_is_validation(client):
    assert error_code(client.get("/members/lookup")) == "VALIDATION"
    assert error_code(client.get("/members/lookup?phone=0551234567&country=XX")) == "VALIDATION"
