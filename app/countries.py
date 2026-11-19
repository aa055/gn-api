# Everything that differs between countries lives in this one table.
#
# A mobile number is the part after the dial code, e.g. 551234567 in +966551234567.
# The national spelling is trunk + mobile: "0551234567" in UAE/Saudi, while
# Bahrain has no trunk zero, so its national spelling is just "31234567".
COUNTRIES = {
    "AE": {"dial": "971", "currency": "AED", "vat_percent": 5, "trunk": "0", "mobile_start": "5", "mobile_length": 9},
    "SA": {"dial": "966", "currency": "SAR", "vat_percent": 15, "trunk": "0", "mobile_start": "5", "mobile_length": 9},
    "BH": {"dial": "973", "currency": "BHD", "vat_percent": 10, "trunk": "", "mobile_start": "3", "mobile_length": 8},
}
