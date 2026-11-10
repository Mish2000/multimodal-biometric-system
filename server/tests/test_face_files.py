"""Face images from files (H27, H51) against a real PostgreSQL, with the face engine replaced by the stand-in of
tests/fakes/fake_face_engine.py. A test file is a real JPEG or PNG header, which the server reads, followed by
the stand-in's label; never a picture of a person."""

from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import keys as keyring
from mbs.models import Attempt

from test_api import auth, error
from test_face import face_client, faces, image, raw, subject_of, taken, user  # noqa: F401
from test_face_identification import other
from test_face_verification import attempts, enrolled


def png_file(columns: int = 1280, rows: int = 960, **spec) -> bytes:
    """A PNG signature and IHDR chunk of this size, then the stand-in's label."""
    ihdr = columns.to_bytes(4, "big") + rows.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + ihdr + bytes(4) + raw(**spec)


def jpeg_file(columns: int = 4000, rows: int = 3000, **spec) -> bytes:
    """A JPEG's start, a JFIF segment and a frame header of this size, then the stand-in's label."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + rows.to_bytes(2, "big") + columns.to_bytes(2, "big") \
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + frame + raw(**spec)


def send(client, route: str, token: str, data: bytes, source: str = "file"):
    return client.post(f"/api/face/{route}", json={"image": base64.b64encode(data).decode(), "source": source},
                       headers=auth(token))


@pytest.mark.parametrize("make", [png_file, jpeg_file])
def test_a_photo_file_is_verified_and_identified_and_its_source_is_saved(face_client, databases, keys, make):
    token = enrolled(face_client)
    file = make(variant=3, width=4000, height=3000, decoded=[4000, 3000], stored=[1920, 1440])
    verified = send(face_client, "verifications", token, file).json()
    assert verified["status"] == "verified" and verified["accepted"] is True and verified["source"] == "file"
    assert verified["size"] == {"decoded": [4000, 3000], "stored": [1920, 1440]}
    identified = send(face_client, "identifications", token, file).json()
    assert identified["status"] == "identified" and identified["accepted"] is True and identified["source"] == "file"
    assert identified["candidates"][0]["own"] is True and identified["size"]["stored"] == [1920, 1440]
    subject = subject_of(face_client, databases, keys, token)
    stored = attempts(databases)
    assert [(a.mode, a.source) for a in stored] == [("verify", "file"), ("identify", "file")]
    for attempt in stored:  # only the pixels the engine made again are kept, never the file itself
        assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == b"PNG:" + file
    camera = face_client.post("/api/face/verifications", json={"image": image(variant=3)}, headers=auth(token)).json()
    assert camera["source"] == "device" and camera["size"] == {"decoded": [1280, 720], "stored": [1280, 720]}
    assert attempts(databases)[-1].source == "device"


@pytest.mark.parametrize("data,failed", [
    (b"GIF89a" + raw(variant=3), ["file_type"]),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 " + raw(variant=3), ["file_type"]),
    (b"\x00\x00\x00\x18ftypheic" + raw(variant=3), ["file_type"]),
    (png_file(320, 200, variant=3, width=320, height=200), ["image_size"]),
    (jpeg_file(8000, 7000, variant=3), ["image_size"]),
])
def test_a_file_is_known_by_its_content_and_its_header_is_checked_before_the_engine(face_client, databases, data, failed):
    token = enrolled(face_client)
    for route in ("verifications", "identifications"):
        result = send(face_client, route, token, data).json()
        assert result["status"] == "rejected" and result["source"] == "file" and result["faces"] == []
        assert [c["name"] for c in result["checks"] if not c["passed"]] == failed
    assert attempts(databases) == []


def test_a_file_without_a_face_is_rejected_with_the_file_checks_and_the_face_checks(face_client, databases):
    token = enrolled(face_client)
    result = send(face_client, "identifications", token, png_file(faces=[], width=1280, height=960)).json()
    assert result["status"] == "rejected"
    assert [(c["name"], c["passed"]) for c in result["checks"]] == [("file_type", True), ("image_size", True),
                                                                    ("one_face", False)]
    assert result["checks"][0]["kind"] == "PNG" and result["checks"][1]["width"] == 1280
    assert attempts(databases) == []


def test_files_may_be_larger_than_camera_images_up_to_10_mb(face_client, databases):
    token = enrolled(face_client)
    label = raw(variant=3, width=1280, height=960)
    padded = png_file(variant=3, width=1280, height=960)[:-len(label)] + b" " * (9 << 20) + label
    assert send(face_client, "verifications", token, padded).json()["status"] == "verified"
    assert error(send(face_client, "verifications", token, padded, source="device")) == (422, "invalid_image")
    too_large = base64.b64encode(b" " * ((10 << 20) + 1)).decode()
    assert face_client.post("/api/face/verifications", json={"image": too_large, "source": "file"},
                            headers=auth(token)).status_code == 422
    assert [a.source for a in attempts(databases)] == ["file"]


def test_enrolment_and_the_live_checks_take_no_files(face_client, databases):
    token = user(face_client)
    file = base64.b64encode(png_file()).decode()
    assert face_client.post("/api/face/checks", json={"image": file, "source": "file"}, headers=auth(token)).status_code == 422
    body = taken(image(), image(variant=1), image(variant=2))
    for item in body["images"]:
        item["source"] = "file"
    assert face_client.post("/api/face/enrolments", json=body, headers=auth(token)).status_code == 422
    assert face_client.post("/api/face/verifications", json={"image": file, "source": "scanner"},
                            headers=auth(token)).status_code == 422


def test_another_users_enrolment_found_from_a_file_stays_anonymous(face_client, databases):
    token = enrolled(face_client)
    other(face_client, "dana", 1, "b")
    answer = send(face_client, "identifications", token, jpeg_file(person="b", variant=3))
    result = answer.json()
    assert result["accepted"] is True and result["candidates"][0]["own"] is False
    assert "dana" not in answer.text and json.loads(answer.text)["source"] == "file"
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt.source)).all() == ["file"]
