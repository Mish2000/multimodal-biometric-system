"""Mobile phone numbers (H29), kept in E.164 form: a plus sign, the country code and the number, 8 to 15
digits in all. A number written the national way (05X-XXXXXXX) is taken as an Israeli mobile, as the
national ID is Israeli too (H3); an Israeli number in international form must be a mobile as well."""

from __future__ import annotations

import re
import unicodedata

ISRAEL = "+972"
# What people write between the digits: spaces, dashes, dots, brackets and the marks of right to left text.
SEPARATORS = re.compile(r"[\s\-.()\u200e\u200f\u202a-\u202e]")
NATIONAL_MOBILE = re.compile(r"05[0-9]{8}")
INTERNATIONAL = re.compile(r"\+[1-9][0-9]{7,14}")
ISRAELI_MOBILE = re.compile(r"\+9725[0-9]{8}")


class InvalidPhone(ValueError):
    pass


def normalize(text: str) -> str:
    compact = SEPARATORS.sub("", unicodedata.normalize("NFKC", text))
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if compact.startswith(ISRAEL + "0"):  # +972 050 ..., the national form after the country code
        compact = ISRAEL + compact[len(ISRAEL) + 1:]
    if compact.startswith("0"):
        if not NATIONAL_MOBILE.fullmatch(compact):
            raise InvalidPhone("not an Israeli mobile number")
        return ISRAEL + compact[1:]
    if not INTERNATIONAL.fullmatch(compact) or (compact.startswith(ISRAEL) and not ISRAELI_MOBILE.fullmatch(compact)):
        raise InvalidPhone("not a mobile number in international form")
    return compact
