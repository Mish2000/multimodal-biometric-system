// H54: one microphone, opened for the voice screens. Its sound comes as it is, without the browser's echo
// cancellation, noise suppression or automatic gain, so an enrolment, a later verification and a file are compared
// alike; an audio context at the model's rate (16 kHz) mixes it down to one channel and resamples it, and a worklet
// hands the samples to the page. Nothing is stored here.

// The worklet stays a file of its own: inlined as a data URL, the page's Content Security Policy would refuse it (H26).
import workletUrl from './recorder-worklet.js?url&no-inline'

export type MicrophoneProblem = 'busy' | 'denied' | 'failed'

export interface MicrophoneInput {
  rate: number
  onBlock(listener: (block: Float32Array) => void): () => void
  onEnded(listener: () => void): void
  close(): void
}

export function problemOf(error: unknown): MicrophoneProblem {
  const name = (error as { name?: string } | null)?.name
  if (name === 'NotReadableError' || name === 'AbortError') return 'busy'
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied'
  return 'failed'
}

export async function openMicrophone(deviceId: string, rate: number): Promise<MicrophoneInput> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { deviceId: { exact: deviceId }, channelCount: { ideal: 1 }, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    video: false,
  })
  const context = new AudioContext({ sampleRate: rate })
  const listeners = new Set<(block: Float32Array) => void>()
  try {
    await context.audioWorklet.addModule(workletUrl)
    const source = context.createMediaStreamSource(stream)
    const node = new AudioWorkletNode(context, 'mbs-recorder', {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1], channelCount: 1, channelCountMode: 'explicit', channelInterpretation: 'speakers',
    })
    node.port.onmessage = (event: MessageEvent<Float32Array>) => listeners.forEach((listener) => listener(event.data))
    source.connect(node)
    node.connect(context.destination) // the worklet writes silence; the connection keeps the graph running
    await context.resume()
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop())
    void context.close()
    throw error
  }
  return {
    rate: context.sampleRate,
    onBlock(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    onEnded(listener) {
      stream.getAudioTracks()[0]?.addEventListener('ended', listener)
    },
    close() {
      listeners.clear()
      stream.getTracks().forEach((track) => track.stop())
      void context.close()
    },
  }
}

// One recording of `seconds`, from the blocks the microphone sends, as Web Audio's samples.
export function record(input: MicrophoneInput, seconds: number, onProgress: (done: number) => void): Promise<Float32Array> {
  const wanted = Math.round(seconds * input.rate)
  const blocks: Float32Array[] = []
  let count = 0
  return new Promise((resolve) => {
    const stop = input.onBlock((block) => {
      blocks.push(block)
      count += block.length
      onProgress(Math.min(1, count / wanted))
      if (count < wanted) return
      stop()
      const samples = new Float32Array(wanted)
      let at = 0
      for (const part of blocks) {
        samples.set(part.subarray(0, Math.min(part.length, wanted - at)), at)
        at += part.length
        if (at >= wanted) break
      }
      resolve(samples)
    })
  })
}
