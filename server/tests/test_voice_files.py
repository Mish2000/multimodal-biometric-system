"""Voice recordings from files (H27, H57) against a real PostgreSQL, with the voice engine replaced by the stand-in of
tests/fakes/fake_voice_engine.py: a fake file is real first bytes followed by a label and the header that libsndfile
would read. No file here holds a person's voice; the real engine's reading is tested in engines/test_voice.py."""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import keys as keyring
from mbs.models import Attempt

from test_api import auth, error
from test_voice import raw, recording, subject_of, user, voice_client, voices  # noqa: F401
from test_voice_verification import enrol

MP3, OGG, WAV = b"ID3\x04\x00\x00\x00\x00\x00\x00", b"OggS\x00\x02", b"RIFF\x24\x00\x00\x00WAVEfmt "
HEADER = {"format": "MP3", "subtype": "MPEG_LAYER_III", "sample_rate": 44100, "channels": 2, "seconds": 12.0}
OPUS = {"format": "OGG", "subtype": "OPUS", "sample_rate": 48000, "channels": 1, "seconds": 12.0}


def file(prefix: bytes = MP3, header: dict | None = None, **spec) -> bytes:
    return prefix + raw(**spec, **({"file": header} if header is not None else {}))


def send(client, token, route: str, data: bytes, source: str = "file"):
    return client.post(f"/api/voice/{route}", json={"recording": base64.b64encode(data).decode(), "source": source},
                       headers=auth(token))


def attempts(databases) -> list[Attempt]:
    with Session(databases.biometric) as db:
        return db.scalars(select(Attempt).order_by(Attempt.at)).all()


@pytest.fixture
def enrolled(voice_client) -> str:
    token = user(voice_client)
    enrol(voice_client, token)
    return token


@pytest.mark.parametrize("route,status", [("verifications", "verified"), ("identifications", "identified")])
def test_a_file_is_compared_and_saved_with_its_source_and_its_converted_recording(voice_client, enrolled, databases, keys,
                                                                                route, status):
    data = file(MP3, HEADER, variant=7)
    answer = send(voice_client, enrolled, route, data)
    assert answer.status_code == 200, answer.text
    result = answer.json()
    assert result["status"] == status and result["accepted"] is True and result["source"] == "file"
    assert result["file"] == HEADER
    assert base64.b64decode(result["probe"]) == b"RIFFWAV:" + data  # the recording compared, the caller's own
    subject = subject_of(voice_client, databases, keys, enrolled)
    (attempt,) = attempts(databases)
    assert attempt.source == "file" and str(attempt.id) == result["attempt_id"]
    assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == b"RIFFWAV:" + data
    device = voice_client.post(f"/api/voice/{route}", json={"recording": recording(variant=7)}, headers=auth(enrolled)).json()
    assert device["source"] == "device" and "file" not in device and "probe" not in device


@pytest.mark.parametrize("prefix", [b"fLaC\x00\x00\x00\x22", b"FORM\x00\x00\x00\x00AIFF", b"\x00\x00\x00\x20ftypM4A ", b""])
def test_only_wav_mp3_and_ogg_reach_the_engine_and_any_other_file_makes_no_attempt(voice_client, enrolled, databases,
                                                                                  prefix):
    result = send(voice_client, enrolled, "verifications", file(prefix, HEADER, variant=7)).json()
    assert result["status"] == "rejected" and result["source"] == "file" and "file" not in result
    assert [(check["name"], check["passed"]) for check in result["checks"]] == [("file_type", False)]
    assert attempts(databases) == []


@pytest.mark.parametrize("prefix,header,failed", [
    (WAV, {"format": "WAV", "subtype": "PCM_16", "sample_rate": 8000, "channels": 1, "seconds": 12.0}, ["sample_rate"]),
    (WAV, {"format": "WAVEX", "subtype": "PCM_24", "sample_rate": 48000, "channels": 3, "seconds": 12.0}, ["channels"]),
    (MP3, {**HEADER, "seconds": 120.5}, ["length"]),
    (MP3, {**HEADER, "seconds": 2.0}, ["length"]),
    (OGG, {**OPUS, "subtype": "FLAC"}, ["file_type"]),
])
def test_a_file_outside_the_limits_is_refused_by_its_header_and_not_decoded(voice_client, enrolled, databases, prefix,
                                                                           header, failed):
    result = send(voice_client, enrolled, "identifications", file(prefix, header, variant=7)).json()
    assert result["status"] == "rejected" and result["file"] == header
    assert [check["name"] for check in result["checks"]] == ["file_type", "sample_rate", "channels", "length"]
    assert [check["name"] for check in result["checks"] if not check["passed"]] == failed
    assert attempts(databases) == []


def test_a_file_is_compared_whole_up_to_two_minutes(voice_client, enrolled, databases):
    long = {**OPUS, "seconds": 119.5}
    result = send(voice_client, enrolled, "verifications", file(OGG, long, variant=7, duration=119.5, speech=90.0)).json()
    assert result["status"] == "verified" and result["file"] == long
    refused = send(voice_client, enrolled, "verifications", file(OGG, {**long, "seconds": 121.0}, variant=7)).json()
    length = next(check for check in refused["checks"] if check["name"] == "length")
    assert refused["status"] == "rejected" and (length["passed"], length["maximum"]) == (False, 120.0)
    assert [attempt.source for attempt in attempts(databases)] == ["file"]


def test_a_file_whose_first_bytes_and_format_disagree_is_refused(voice_client, enrolled, databases):
    header = {"format": "WAV", "subtype": "PCM_16", "sample_rate": 48000, "channels": 1, "seconds": 12.0}
    result = send(voice_client, enrolled, "verifications", file(MP3, header, variant=7)).json()
    assert result["status"] == "rejected"
    assert [check["name"] for check in result["checks"] if not check["passed"]] == ["file_type"]
    assert attempts(databases) == []


def test_a_decoded_file_must_still_pass_the_checks_of_a_recording(voice_client, enrolled, databases):
    result = send(voice_client, enrolled, "verifications", file(OGG, OPUS, speech=0.5)).json()
    assert result["status"] == "rejected" and result["file"] == OPUS
    assert [check["name"] for check in result["checks"]] == ["file_type", "sample_rate", "channels", "length", "speech",
                                                             "clipping"]
    assert [check["name"] for check in result["checks"] if not check["passed"]] == ["speech"]
    assert attempts(databases) == []


def test_a_file_may_be_larger_than_a_recording_of_the_page_and_an_unreadable_one_is_refused(voice_client, enrolled,
                                                                                            databases):
    large = file(MP3, HEADER, variant=7) + b" " * (2 << 20)  # a file may hold up to 10 MB, the page's recording 1 MB
    assert send(voice_client, enrolled, "verifications", large).json()["status"] == "verified"
    assert error(send(voice_client, enrolled, "verifications", large, source="device")) == (422, "invalid_recording")
    assert voice_client.post("/api/voice/verifications", json={"recording": recording(), "source": "upload"},
                             headers=auth(enrolled)).status_code == 422
    assert error(send(voice_client, enrolled, "identifications", file(MP3, HEADER, unreadable=True))) == (
        422, "invalid_recording")
    assert [attempt.source for attempt in attempts(databases)] == ["file"]
