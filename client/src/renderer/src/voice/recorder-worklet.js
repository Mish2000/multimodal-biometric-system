// H54: the microphone's samples, at the audio context's rate, handed to the page block by block. It writes no
// output, so nothing reaches the speakers, and it keeps nothing.
class Recorder extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel) this.port.postMessage(channel.slice(0))
    return true
  }
}

registerProcessor('mbs-recorder', Recorder)
