"""H54, H57: the synthetic recordings of the offscreen check, never a person's voice. Run with the voice environment:

    python -I voice_files.py OUT_DIR

voice-synthetic.wav is what Chromium's fake microphone plays in a loop: ten seconds at 16 kHz, one channel, 16-bit
PCM, harmonics of a gliding pitch in syllable-like bursts for four seconds, then one second of quiet room noise, so
any five seconds of it hold about four seconds of "speech" and enough quiet for the noise floor, and its recordings
pass the checks and match each other. voice-synthetic.mp3 is the same sound as a file at 44.1 kHz in two channels,
which the voice engine converts and compares (H57); voice-synthetic-8k.wav is it at 8 kHz, which the server refuses.
"""
import sys
import wave
from pathlib import Path

import numpy as np
import soundfile
from scipy.signal import resample_poly

RATE = 16000


def pcm16(signal: np.ndarray) -> np.ndarray:
    return np.clip(np.round(signal * 32768), -32768, 32767).astype("<i2")


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(54)
    t = np.arange(10 * RATE) / RATE
    pitch = 2 * np.pi * np.cumsum(130 + 30 * np.sin(2 * np.pi * 0.6 * t)) / RATE
    tone = sum(np.sin(k * pitch) / k for k in range(1, 12))
    tone *= 10 ** (-22 / 20) / np.sqrt(np.mean(tone ** 2))
    cycle = t % 5.0
    syllables = (np.sin(2 * np.pi * 3.1 * t) > -0.6).astype(float)
    gate = np.where(cycle < 4.0, syllables, 0.0)
    noise = rng.standard_normal(len(t)) * 10 ** (-58 / 20)
    samples = pcm16(tone * gate + noise)
    write_wav(out / "voice-synthetic.wav", samples, RATE)

    signal = samples.astype(np.float64) / 32768
    stereo = np.repeat(resample_poly(signal, 441, 160)[:, None], 2, axis=1)
    soundfile.write(out / "voice-synthetic.mp3", stereo, 44100, format="MP3")
    write_wav(out / "voice-synthetic-8k.wav", pcm16(resample_poly(signal, 1, 2)), 8000)
    print("wrote the synthetic recordings to", out)


if __name__ == "__main__":
    main()
