from app import phones


def test_clean_strips_spaces_hyphens_brackets():
    assert phones.clean("(055) 123-4567") == "0551234567"
    assert phones.clean("+966 55 123 4567") == "+966551234567"


def test_clean_rejects_anything_else():
    assert phones.clean("055.123.4567") is None
    assert phones.clean("++966551234567") is None
    assert phones.clean("96655+1234567") is None
    assert phones.clean("٠٥٥١٢٣٤٥٦٧") is None  # Arabic-Indic digits
    assert phones.clean("055\t1234567") is None


def test_international_spellings():
    assert phones.read_international("+966551234567") == ("SA", "+966551234567")
    assert phones.read_international("966551234567") == ("SA", "+966551234567")
    assert phones.read_international("+971501234567") == ("AE", "+971501234567")
    assert phones.read_international("97331234567") == ("BH", "+97331234567")


def test_international_rejects_bad_shapes():
    assert phones.read_international("00966551234567") is None   # 00 prefix
    assert phones.read_international("+9660551234567") is None   # trunk zero kept
    assert phones.read_international("+96611234567") is None     # landline
    assert phones.read_international("+97355123456") is None     # BH must start 3
    assert phones.read_international("+9665512345678") is None   # too long


def test_national_spellings():
    assert phones.read_national("0551234567", "SA") == "+966551234567"
    assert phones.read_national("0501234567", "AE") == "+971501234567"
    assert phones.read_national("31234567", "BH") == "+97331234567"


def test_national_must_fit_the_country():
    assert phones.read_national("0551234567", "BH") is None
    assert phones.read_national("31234567", "SA") is None
    assert phones.read_national("031234567", "BH") is None     # no trunk zero in BH
    assert phones.read_national("0451234567", "SA") is None    # must be 05
    assert phones.read_national("+0551234567", "SA") is None
