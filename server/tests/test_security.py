"""National IDs, phone numbers, sealing, key versions, the key file's permissions and passwords (H3, H14,
H29, H30)."""

from __future__ import annotations

import os
import subprocess

import pytest

from mbs import keys as keyring
from mbs import national_id, passwords, phones


@pytest.mark.parametrize("text, expected", [("123456782", "123456782"), ("18", "000000018"),
                                            (" 12345678-2 ", "123456782")])
def test_valid_national_ids(text, expected):
    assert national_id.normalize(text) == expected


@pytest.mark.parametrize("text", ["123456789", "000000000", "0", "1234567890", "12a456782", "١٢٣٤٥٦٧٨٢", ""])
def test_invalid_national_ids(text):
    with pytest.raises(national_id.InvalidNationalId):
        national_id.normalize(text)


def test_national_id_hmac_depends_on_the_key():
    a, b = keyring.Keys.generate(), keyring.Keys.generate()
    assert keyring.national_id_hmac(a, "123456782") == keyring.national_id_hmac(a, "123456782")
    assert keyring.national_id_hmac(a, "123456782") != keyring.national_id_hmac(b, "123456782")


def test_a_sealed_value_opens_only_for_its_use_and_row():
    keys = keyring.Keys.generate()
    sealed = keyring.seal(keys, keyring.IDENTITY_LINK, b"row-1", b"subject")
    assert keyring.open_sealed(keys, keyring.IDENTITY_LINK, b"row-1", sealed) == b"subject"
    for label, row in ((keyring.IDENTITY_LINK, b"row-2"), ("mbs/other/v1", b"row-1")):
        with pytest.raises(keyring.KeysError):
            keyring.open_sealed(keys, label, row, sealed)
    with pytest.raises(keyring.KeysError):  # changed in storage
        keyring.open_sealed(keys, keyring.IDENTITY_LINK, b"row-1", sealed[:-1] + bytes([sealed[-1] ^ 1]))
    with pytest.raises(keyring.KeysError):  # another key file
        keyring.open_sealed(keyring.Keys.generate(), keyring.IDENTITY_LINK, b"row-1", sealed)


def test_values_sealed_with_an_older_key_version_still_open():
    keys = keyring.Keys.generate()
    old = keyring.seal(keys, keyring.IDENTITY_LINK, b"r", b"x")
    rotated = keyring.Keys(current=2, masters={**keys.masters, 2: os.urandom(32)}, national_id=keys.national_id,
                           database=keys.database)
    assert keyring.open_sealed(rotated, keyring.IDENTITY_LINK, b"r", old) == b"x"
    assert keyring.seal(rotated, keyring.IDENTITY_LINK, b"r", b"x")[4:6] == (2).to_bytes(2, "big")


def test_the_key_file_is_never_replaced_and_only_its_user_can_read_it(tmp_path):
    path = tmp_path / "folder" / "keys.json"
    keys = keyring.create(path)
    assert keyring.load(path) == keys
    with pytest.raises(keyring.KeysError):
        keyring.create(path)
    for target in (path, path.parent):
        listing = subprocess.run(["icacls", str(target)], capture_output=True, text=True, errors="replace").stdout
        entries = [line for line in listing.splitlines() if ":(" in line]
        assert len(entries) == 1 and "(I)" not in entries[0], listing  # one entry, nothing inherited


def test_passwords_use_argon2id_at_rfc_9106_second_option():
    phc = passwords.hash_password("correct horse battery staple")
    assert phc.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert passwords.verify_password("correct horse battery staple", phc)
    assert not passwords.verify_password("correct horse battery stapl", phc)
    assert passwords.verify_password("ｃｏｒｒｅｃｔ horse battery staple", phc)  # the same text in NFKC


@pytest.mark.parametrize("password", ["ABCDEFG1", "Abcdefg1", "Passw0rd!", "סיסמהA1x", "Ａbcdefg１",
                                      "A1" + "x" * 30, "Two words 1"])
def test_passwords_that_follow_the_rules(password):
    passwords.check_new(password)


@pytest.mark.parametrize("password", ["Abcdef1", "A1" + "x" * 31, "abcdefg1", "ABCDEFGH", "סיסמה12345", ""])
def test_passwords_that_break_the_rules(password):
    with pytest.raises(passwords.InvalidPassword):
        passwords.check_new(password)


@pytest.mark.parametrize("text, expected", [("050-123-4567", "+972501234567"), ("0501234567", "+972501234567"),
                                            ("+972 50 123 4567", "+972501234567"), ("00972-50-1234567", "+972501234567"),
                                            ("+972 050 123 4567", "+972501234567"), ("(054) 765.4321", "+972547654321"),
                                            ("\u200e+972-54-765-4321", "+972547654321"), ("０５０１２３４５６７", "+972501234567"),
                                            ("+1 415 555 0100", "+14155550100")])
def test_valid_phone_numbers(text, expected):
    assert phones.normalize(text) == expected


@pytest.mark.parametrize("text", ["", "12345", "03-123-4567", "+97231234567", "+0123456789", "+1234567",
                                  "05012345678", "+1 415 555 01000000000", "050-123-456a", "٠٥٠١٢٣٤٥٦٧"])
def test_invalid_phone_numbers(text):
    with pytest.raises(phones.InvalidPhone):
        phones.normalize(text)
