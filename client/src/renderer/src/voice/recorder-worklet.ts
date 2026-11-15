// H54: the microphone's samples, at the audio context's rate, handed to the page block by block. It writes no
// output, so nothing reaches the speakers, and it keeps nothing.

// What an audio worklet's own scope offers; TypeScript's libraries describe the page's side only.
declare class AudioWorkletProcessor {
  readonly port: MessagePort
}
declare function registerProcessor(name: string, processor: new () => AudioWorkletProcessor): void

class Recorder extends AudioWorkletProcessor {
  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0]
    if (channel) this.port.postMessage(channel.slice(0))
    return true
  }
}

registerProcessor('mbs-recorder', Recorder)
