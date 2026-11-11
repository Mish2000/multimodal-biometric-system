// H54: a recording as the server takes it: a WAV of one channel and 16-bit PCM at the model's rate, made in the
// page from the samples the microphone gave, and its level for the meter.

// Web Audio's samples run from -1 to 1; 16-bit PCM is the same scale times 32768, as libsndfile reads it back.
export function toPcm16(samples: Float32Array): Int16Array {
  const pcm = new Int16Array(samples.length)
  for (let i = 0; i < samples.length; i += 1) {
    pcm[i] = Math.max(-32768, Math.min(32767, Math.round(samples[i]! * 32768)))
  }
  return pcm
}

export function wavBytes(pcm: Int16Array, rate: number): Uint8Array {
  const bytes = new Uint8Array(44 + 2 * pcm.length)
  const view = new DataView(bytes.buffer)
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i))
  }
  text(0, 'RIFF')
  view.setUint32(4, 36 + 2 * pcm.length, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true) // the format chunk's size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // one channel
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true) // bytes per second
  view.setUint16(32, 2, true) // bytes per sample frame
  view.setUint16(34, 16, true) // bits per sample
  text(36, 'data')
  view.setUint32(40, 2 * pcm.length, true)
  for (let i = 0; i < pcm.length; i += 1) view.setInt16(44 + 2 * i, pcm[i]!, true)
  return bytes
}

export function base64Of(bytes: Uint8Array): string {
  let text = ''
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(text)
}

// The level of a block of samples in dB of full scale; digital silence is -100.
export function levelOf(samples: Float32Array): number {
  let sum = 0
  for (let i = 0; i < samples.length; i += 1) sum += samples[i]! * samples[i]!
  const power = samples.length ? sum / samples.length : 0
  return power > 1e-10 ? Math.max(-100, 10 * Math.log10(power)) : -100
}

// What the waveform draws: the lowest and highest sample of each of `columns` equal stretches, from -1 to 1.
export function envelope(pcm: Int16Array, columns: number): Array<[number, number]> {
  const out: Array<[number, number]> = []
  if (pcm.length === 0) return out
  for (let c = 0; c < columns; c += 1) {
    const start = Math.floor((c * pcm.length) / columns)
    const end = Math.max(start + 1, Math.floor(((c + 1) * pcm.length) / columns))
    let low = 0
    let high = 0
    for (let i = start; i < end && i < pcm.length; i += 1) {
      const value = pcm[i]! / 32768
      if (value < low) low = value
      if (value > high) high = value
    }
    out.push([low, high])
  }
  return out
}
