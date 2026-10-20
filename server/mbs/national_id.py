"""Israeli national ID numbers: checked by their check digit, then only their HMAC is kept (H3)."""

from __future__ import annotations

import re

DIGITS = re.compile(r"[0-9]{1,9}")


class InvalidNationalId(ValueError):
    pass


def normalize(text: str) -> str:
    """The number as nine digits with leading zeros, or InvalidNationalId."""
    digits = re.sub(r"[\s-]", "", text)
    if not DIGITS.fullmatch(digits):
        raise InvalidNationalId("a national ID has up to nine digits")
    digits = digits.zfill(9)
    if digits == "000000000" or not check_digit_ok(digits):
        raise InvalidNationalId("the check digit does not match")
    return digits


def check_digit_ok(digits: str) -> bool:
    """The Israeli rule: weights 1, 2, 1, 2, ...; a product above 9 counts its digit sum; the total
    is a multiple of 10."""
    total = 0
    for i, ch in enumerate(digits):
        n = int(ch) * (1 if i % 2 == 0 else 2)
        total += n - 9 if n > 9 else n
    return total % 10 == 0
