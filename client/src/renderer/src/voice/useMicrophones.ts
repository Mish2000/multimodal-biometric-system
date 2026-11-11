// H54: the microphones of this computer, as the voice screens see them, kept up to date as devices are plugged in
// or out (the browser's devicechange). Cameras are listed too, only to know which microphone belongs to one.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { microphonesFrom, ranked, rememberMicrophone, rememberedMicrophone, type Microphone } from './microphone'

async function listMicrophones(): Promise<Microphone[]> {
  if (!navigator.mediaDevices) return [] // a page without the media interface has no microphone
  return microphonesFrom(await navigator.mediaDevices.enumerateDevices())
}

// Names stay hidden until the page has used a microphone once; one short request reveals them, and the
// microphone it opens is stopped at once, before any sound is read.
async function readableMicrophones(): Promise<Microphone[]> {
  const microphones = await listMicrophones()
  if (microphones.length === 0 || microphones.some((m) => m.name !== '')) return microphones
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    stream.getTracks().forEach((track) => track.stop())
  } catch {
    // the microphone's own opening reports the reason
  }
  return listMicrophones()
}

export interface Microphones {
  microphones: Microphone[] | null // null while they are being looked for
  usable: Microphone[] // in the order they are tried
  current: Microphone | null
  markSilent(microphone: Microphone): void
  pick(microphone: Microphone): void
  retry(): void
}

export function useMicrophones(): Microphones {
  const [microphones, setMicrophones] = useState<Microphone[] | null>(null)
  const [silent, setSilent] = useState<ReadonlySet<string>>(new Set())
  const [remembered, setRemembered] = useState<string | null>(rememberedMicrophone)
  const [picked, setPicked] = useState<string | null>(null) // chosen in this screen: tried first
  const [search, setSearch] = useState(0)

  useEffect(() => {
    let active = true
    const load = () => {
      readableMicrophones()
        .then((found) => {
          if (!active) return
          setMicrophones(found)
          setSilent(new Set()) // a device came or went: every microphone may be tried again
        })
        .catch(() => {
          if (active) setMicrophones([])
        })
    }
    load()
    navigator.mediaDevices?.addEventListener('devicechange', load)
    return () => {
      active = false
      navigator.mediaDevices?.removeEventListener('devicechange', load)
    }
  }, [search])

  const usable = useMemo(() => {
    if (microphones === null) return []
    const order = ranked(microphones, { remembered, silent })
    const chosen = order.find((m) => m.key === picked)
    return chosen ? [chosen, ...order.filter((m) => m !== chosen)] : order
  }, [microphones, remembered, silent, picked])

  const markSilent = useCallback((microphone: Microphone) => {
    setSilent((current) => new Set([...current, microphone.key]))
  }, [])

  const pick = useCallback((microphone: Microphone) => {
    rememberMicrophone(microphone.key)
    setRemembered(microphone.key)
    setPicked(microphone.key)
    setSilent((current) => new Set([...current].filter((key) => key !== microphone.key)))
  }, [])

  const retry = useCallback(() => {
    setSilent(new Set())
    setSearch((count) => count + 1)
  }, [])

  return { microphones, usable, current: usable[0] ?? null, markSilent, pick, retry }
}
