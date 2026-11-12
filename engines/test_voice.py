"""Tests of the voice engine (H54), run with the research project environment's Python like the other engine
tests; the engine itself runs in the voice environment (environments/voice.yml).

The recordings here are synthetic, never of a person: tones in bursts, noise and silence. They cover the
protocol, the model pins, the measurements of the checks and the repeatability of ECAPA's values; voices are
tried by hand on the researcher's microphones. The voice environment is found next to this Python's
environment or named by MBS_VOICE_PYTHON, and the model in local/models/voice or in MBS_VOICE_MODELS. Tests
whose requirements are missing are skipped.
"""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ENGINES = Path(__file__).resolve().parent
SYSTEM_ROOT = ENGINES.parent
sys.path[:0] = [str(ENGINES), str(SYSTEM_ROOT / "methods")]

import protocol  # noqa: E402
import research_link  # noqa: E402
import voice  # noqa: E402

VOICE_PYTHON = Path(os.environ.get("MBS_VOICE_PYTHON") or Path(sys.prefix).parent / "multimodal-voice" / "python.exe")
MODELS = Path(os.environ.get("MBS_VOICE_MODELS") or SYSTEM_ROOT / "local" / "models" / "voice")
needs_voice = pytest.mark.skipif(
    not (VOICE_PYTHON.exists() and all((MODELS / name).exists() for name in voice.MODEL_FILES)),
    reason="the voice environment or its model is missing")

RATE = voice.SAMPLE_RATE


def wav_of(samples: np.ndarray, rate: int = RATE, channels: int = 1, width: int = 2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(samples.astype("<i2" if width == 2 else "u1").tobytes())
    return out.getvalue()


def bursts(seconds: float = 5.0, on: tuple[tuple[float, float], ...] = ((0.5, 4.5),), level_db: float = -20.0,
           noise_db: float = -60.0, seed: int = 1, rate: int = RATE) -> np.ndarray:
    """A synthetic recording: harmonics of a gliding pitch, sounding only inside the `on` spans, over steady noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * rate)) / rate
    pitch = 2 * np.pi * np.cumsum(140 + 25 * np.sin(2 * np.pi * 0.8 * t)) / rate
    tone = sum(np.sin(k * pitch) / k for k in range(1, 10))
    tone *= 10 ** (level_db / 20) / np.sqrt(np.mean(tone ** 2))
    gate = np.zeros_like(t)
    for start, end in on:
        gate[(t >= start) & (t < end)] = 1.0
    noise = rng.standard_normal(len(t)) * 10 ** (noise_db / 20)
    return np.clip(np.round((tone * gate + noise) * 32768), -32768, 32767).astype(np.int16)


@pytest.fixture
def engine():
    process = subprocess.Popen([str(VOICE_PYTHON), "-I", str(ENGINES / "voice.py"), str(MODELS)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=research_link.environment(VOICE_PYTHON))
    try:
        yield process
    finally:
        process.stdin.close()
        process.wait(60)


def ask(process: subprocess.Popen, header: dict, data: bytes | list[bytes] = b"") -> tuple[dict, list[bytes]]:
    protocol.write_message(process.stdin, header, data)
    return protocol.read_message(process.stdout)


def test_speech_is_counted_where_it_stands_out_of_the_rooms_noise():
    found = voice.measure(bursts(on=((0.5, 2.0), (2.15, 3.5))))  # a pause of 0.15 s inside the speech
    assert found["duration"] == 5.0
    assert found["speech"] == pytest.approx(3.0, abs=0.05)  # the short pause counts, the silence around it not
    assert found["speech_level"] == pytest.approx(-20.0, abs=1.0)
    assert found["noise_level"] == pytest.approx(-60.0, abs=1.0)
    assert found["clipped"] == 0.0


def test_a_pause_longer_than_two_tenths_of_a_second_is_not_speech():
    found = voice.measure(bursts(on=((0.5, 1.5), (2.5, 3.5))))  # a pause of a whole second
    assert found["speech"] == pytest.approx(2.0, abs=0.05)


def test_silence_and_a_steady_sound_have_no_speech():
    assert voice.measure(np.zeros(5 * RATE, np.int16))["speech"] == 0.0
    steady = voice.measure(bursts(on=((0.0, 5.0),)))  # nothing stands out of a sound that never stops
    assert steady["speech"] == 0.0
    assert voice.measure(np.zeros(100, np.int16)) == {
        "duration": 0.006, "speech": 0.0, "speech_level": voice.SILENCE, "noise_level": voice.SILENCE, "clipped": 0.0}


def test_samples_at_the_16_bit_limits_are_counted_as_clipped():
    samples = bursts()
    samples[:400] = 32767
    samples[400:600] = -32768
    assert voice.measure(samples)["clipped"] == pytest.approx(600 / len(samples), abs=1e-6)


def test_a_model_file_that_differs_from_its_pin_is_refused(tmp_path):
    for name in voice.MODEL_FILES:
        (tmp_path / name).write_bytes(b"not the model")
    with pytest.raises(RuntimeError, match="SHA-256"):
        voice.check_models(tmp_path)
    (tmp_path / "empty").mkdir()
    with pytest.raises(RuntimeError, match="missing"):
        voice.check_models(tmp_path / "empty")


def test_the_stored_recording_is_a_wav_of_its_samples_alone():
    samples = bursts(seconds=1.0)
    data = voice.wav(samples)
    assert data[:4] == b"RIFF" and data[8:16] == b"WAVEfmt " and len(data) == 44 + 2 * len(samples)
    with wave.open(io.BytesIO(data)) as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) == (1, 2, RATE)
        assert np.array_equal(np.frombuffer(reader.readframes(reader.getnframes()), "<i2"), samples)


@needs_voice
def test_the_engine_names_its_pinned_model_and_reads_the_embedding_length(engine):
    ready, _ = protocol.read_message(engine.stdout)  # nothing but the protocol on standard output
    assert ready["ok"] and ready["engine"] == "voice"
    assert ready["ecapa_sha256"] == voice.ECAPA_SHA256 and ready["embedding_length"] == 192
    assert ready["speechbrain"] == "1.1.2" and ready["torch"].startswith("2.13.0")
    assert ready["sample_rate"] == RATE and ready["threads"] == voice.THREADS


@needs_voice
def test_a_recording_gives_its_measurements_its_wav_and_192_values(engine):
    protocol.read_message(engine.stdout)
    samples = bursts()
    reply, parts = ask(engine, {"op": "extract"}, wav_of(samples))
    assert reply["ok"] and reply["sample_rate"] == RATE and reply["embedding_length"] == 192
    assert reply["duration"] == 5.0 and reply["speech"] == pytest.approx(4.0, abs=0.05) and reply["clipped"] == 0.0
    assert parts[0] == voice.wav(samples)
    values = struct.unpack("<192f", parts[1])
    assert all(np.isfinite(values)) and any(values)


@needs_voice
def test_the_same_recording_gives_exactly_the_same_values_again_and_in_another_process(engine):
    protocol.read_message(engine.stdout)
    data = wav_of(bursts(seed=3))
    first = ask(engine, {"op": "extract"}, data)[1][1]
    assert ask(engine, {"op": "extract"}, data)[1][1] == first
    other = subprocess.Popen([str(VOICE_PYTHON), "-I", str(ENGINES / "voice.py"), str(MODELS)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=research_link.environment(VOICE_PYTHON))
    try:
        protocol.read_message(other.stdout)
        assert ask(other, {"op": "extract"}, data)[1][1] == first
    finally:
        other.stdin.close()
        other.wait(60)


@needs_voice
def test_data_that_is_not_such_a_recording_is_refused_and_the_engine_keeps_serving(engine):
    protocol.read_message(engine.stdout)
    for data, reason in ((b"not a recording at all" * 20, "not a recording"),
                         (wav_of(bursts(), rate=48000), "16000 Hz"),
                         (wav_of(np.repeat(bursts(), 2), channels=2), "one channel"),
                         (wav_of(np.full(RATE, 128, np.uint8), width=1), "16-bit PCM")):
        reply, parts = ask(engine, {"op": "extract"}, data)
        assert reply["ok"] and reason in reply["invalid"] and parts == [b""]
    reply, parts = ask(engine, {"op": "extract"}, wav_of(bursts(seconds=0.5)))
    assert reply["ok"] and reply["duration"] == 0.5 and parts == [b""]  # too short to describe
    assert ask(engine, {"op": "extract"}, wav_of(bursts()))[0]["embedding_length"] == 192


# H57: recording files. They are written here by the voice environment's own libsndfile, from the synthetic signal,
# as floats and in blocks: its MP3 encoder garbled 16-bit stereo samples, and its Vorbis encoder overflowed the stack
# when given twelve seconds in one call. Both are writing faults; the system only reads files.
ENCODE = """
import io, sys, numpy as np, soundfile as sf
rate, channels, fmt, subtype = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
samples = np.frombuffer(sys.stdin.buffer.read(), "<i2").reshape(-1, channels).astype(np.float32) / 32768
out = io.BytesIO()
with sf.SoundFile(out, "w", rate, channels, subtype, format=fmt) as file:
    for start in range(0, len(samples), 4096):
        file.write(samples[start:start + 4096])
sys.stdout.buffer.write(out.getvalue())
"""
# SpeechBrain's own load_audio of a file on disk (its audio_io.load and AudioNormalizer), then 16-bit PCM.
LOAD_AUDIO = """
import sys, numpy as np, torch
torch.set_num_threads(8)
from speechbrain.dataio import audio_io
from speechbrain.dataio.preprocess import AudioNormalizer
signal, rate = audio_io.load(sys.argv[1], channels_first=False)
mono = AudioNormalizer(sample_rate=16000)(signal, rate).numpy()
sys.stdout.buffer.write(np.clip(np.round(mono.astype(np.float64) * 32768), -32768, 32767).astype("<i2").tobytes())
"""


def in_voice_environment(script: str, *args: str, data: bytes = b"") -> bytes:
    return subprocess.run([str(VOICE_PYTHON), "-I", "-c", script, *args], input=data, capture_output=True, check=True,
                          env=research_link.environment(VOICE_PYTHON)).stdout


def encoded(samples: np.ndarray, rate: int, fmt: str, subtype: str, channels: int = 1) -> bytes:
    """A synthetic recording file in one of libsndfile's formats; stereo repeats the signal in both channels."""
    frames = np.repeat(samples, channels) if channels > 1 else samples
    return in_voice_environment(ENCODE, str(rate), str(channels), fmt, subtype, data=frames.astype("<i2").tobytes())


def samples_of(wav_data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_data)) as reader:
        assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (RATE, 1, 2)
        return np.frombuffer(reader.readframes(reader.getnframes()), "<i2")


@needs_voice
def test_recording_files_are_converted_as_speechbrains_load_audio_converts_them(engine, tmp_path):
    protocol.read_message(engine.stdout)
    files = [
        ("WAV", "PCM_16", 44100, 2, encoded(bursts(12, seed=4, rate=44100), 44100, "WAV", "PCM_16", 2)),
        ("WAVEX", "PCM_24", 48000, 1, encoded(bursts(12, seed=5, rate=48000), 48000, "WAVEX", "PCM_24")),
        ("OGG", "VORBIS", 48000, 2, encoded(bursts(12, seed=6, rate=48000), 48000, "OGG", "VORBIS", 2)),
        ("OGG", "OPUS", 48000, 1, encoded(bursts(12, seed=7, rate=48000), 48000, "OGG", "OPUS")),
        ("MP3", "MPEG_LAYER_III", 44100, 2, encoded(bursts(12, seed=8, rate=44100), 44100, "MP3", "MPEG_LAYER_III", 2)),
    ]
    for fmt, subtype, rate, channels, data in files:
        reply, parts = ask(engine, {"op": "extract", "file": True}, data)
        assert reply["ok"] and reply["decoded"] is True, (fmt, reply)
        assert reply["file"] == {"format": fmt, "subtype": subtype, "sample_rate": rate, "channels": channels,
                                 "seconds": 12.0}
        assert reply["sample_rate"] == RATE and reply["duration"] == 12.0 and reply["speech"] > 2.0
        converted = samples_of(parts[0])
        path = tmp_path / f"file.{fmt.lower()}"
        path.write_bytes(data)
        assert np.array_equal(converted, np.frombuffer(in_voice_environment(LOAD_AUDIO, str(path)), "<i2")), fmt
        # The stored WAV is the recording compared: read again as a recording, it gives the same 192 values.
        assert ask(engine, {"op": "extract"}, parts[0])[1][1] == parts[1], fmt


@needs_voice
def test_a_file_outside_the_limits_is_not_decoded_and_one_that_is_not_a_recording_is_refused(engine):
    protocol.read_message(engine.stdout)
    for data, expected in ((encoded(bursts(12), RATE, "FLAC", "PCM_16"), {"format": "FLAC"}),
                           (wav_of(bursts(12, rate=8000), rate=8000), {"sample_rate": 8000}),
                           (wav_of(np.repeat(bursts(12), 3), channels=3), {"channels": 3}),
                           (wav_of(bursts(121, on=((0.5, 120.0),))), {"seconds": 121.0}),
                           (wav_of(bursts(2.5, on=((0.2, 2.3),))), {"seconds": 2.5})):
        reply, parts = ask(engine, {"op": "extract", "file": True}, data)
        assert reply["ok"] and reply["decoded"] is False and parts == [b""], reply
        assert {key: reply["file"][key] for key in expected} == expected
        assert "duration" not in reply and "embedding_length" not in reply
    reply, parts = ask(engine, {"op": "extract", "file": True}, b"OggS" + bytes(range(256)) * 8)
    assert reply["ok"] and "not a recording" in reply["invalid"] and parts == [b""]
    reply = ask(engine, {"op": "extract", "file": True}, wav_of(bursts(90, on=((0.5, 89.5),))))[0]
    assert reply["decoded"] is True and reply["duration"] == 90.0  # a file is compared whole up to two minutes
