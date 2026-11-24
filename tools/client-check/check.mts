// End-to-end check of the client skeleton (H26) and of sign-up and sign-in after H29-H32 against the
// throwaway server, offscreen: the built page (or the development server's), the real preload, bridge and
// window security, and nothing on the desktop.
//   electron check.mts CLIENT_DIR RUN_DIR OUT_DIR [PAGE_URL]   (run.py starts the server and this check: README.md)
// Electron runs this file as it is: Node.js removes the types when it loads it, so they are checked by the client's
// `npm run typecheck` (tsconfig.json, beside this file), not here.
// Every failure is printed and ends the process: with its own 'uncaughtException' listener, Electron never
// opens its blocking "A JavaScript error occurred in the main process" window. The mbs:// link of H32 is
// not registered with Windows here: the check hands the outbox's link to the bridge as the main process does.
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { app, BrowserWindow, nativeTheme, session } from 'electron'

function fail(what: string, e: unknown): never {
  console.log('FAIL', what, (e instanceof Error && e.stack) || String(e))
  process.exit(1)
}
process.on('uncaughtException', (e) => fail('uncaught', e))
process.on('unhandledRejection', (e) => fail('unhandled', e))
// With MBS_CHECK_SHOTS every screenshot is taken four times, so the check takes longer.
const WATCHDOG_S = process.env.MBS_CHECK_SHOTS ? 1200 : 420
setTimeout(() => fail('watchdog', `gave up after ${WATCHDOG_S} s`), WATCHDOG_S * 1000).unref()

const [client, run, out, pageUrl] = process.argv.slice(2)
if (!client || !run || !out) fail('arguments', 'electron check.mts CLIENT_DIR RUN_DIR OUT_DIR [PAGE_URL]')
// H48: Chromium's own synthetic camera instead of the PC's cameras, so the check never films anyone.
app.commandLine.appendSwitch('use-fake-device-for-media-stream')
// H54: the fake microphone plays a synthetic recording in a loop (voice_files.py), never a person's voice.
if (process.env.MBS_CHECK_VOICE_WAV) app.commandLine.appendSwitch('use-file-for-fake-audio-capture', process.env.MBS_CHECK_VOICE_WAV)
app.setPath('userData', path.join(path.dirname(path.resolve(run)), `electron-profile-${path.basename(run)}`))
fs.mkdirSync(out, { recursive: true })

// What run.py's throwaway server writes about itself (server.json).
interface ServerDescription {
  url: string
  administrator: string
  one_time_password: string
  outbox: string
  fingerprint: boolean
  face: boolean
  voice: boolean
}
// One identification as the bridge's client ran it: its method and the progress events it sent to the page.
interface IdentifyEvent {
  type: string
  completed?: number
  total?: number
}
interface IdentifyRun {
  algorithm: unknown
  captureFrom: unknown // H59: the earlier attempt whose capture is searched again
  events: IdentifyEvent[]
}

const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))
const layout: { shot: string; theme: string; size: string; problems: string[] }[] = []
if (process.env.MBS_CHECK_SHOTS) fs.mkdirSync(path.join(out, 'matrix'), { recursive: true })
// What would look broken in a screenshot: the page running wider than the window, text outside the window, and text
// cut by its box (an ellipsis included, so that every cut is looked at). Tables and drawings scroll or scale by design.
const LAYOUT_PROBLEMS = `
  const problems = []
  const root = document.documentElement
  if (root.scrollWidth > innerWidth + 1) problems.push('the page is ' + (root.scrollWidth - innerWidth) + ' px wider than the window')
  for (const el of document.querySelectorAll('h1, h2, h3, h4, p, button, a, label, legend, li, th, td, strong, span, summary')) {
    if (el.closest('.visually-hidden, .table-wrap, svg, .match-plates, .camera-view')) continue
    const style = getComputedStyle(el)
    if (style.display === 'none' || style.visibility === 'hidden' || style.display === 'contents') continue
    const box = el.getBoundingClientRect()
    if (box.width === 0 || box.height === 0) continue
    const text = (el.textContent ?? '').trim().replace(/\\s+/g, ' ').slice(0, 70)
    if (box.right > innerWidth + 1 || box.left < -1) problems.push('outside the window: ' + el.tagName.toLowerCase() + ' ' + text)
    if ((style.overflowX === 'hidden' || style.textOverflow === 'ellipsis') && el.scrollWidth > el.clientWidth + 1)
      problems.push('cut: ' + el.tagName.toLowerCase() + ' ' + text)
  }
  return [...new Set(problems)].slice(0, 30)`
const results: { name: string; passed: boolean; detail?: unknown }[] = []
function check(name: string, passed: unknown, detail?: unknown): void {
  results.push({ name, passed: Boolean(passed), ...(detail === undefined ? {} : { detail }) })
  console.log(passed ? 'ok  ' : 'FAIL', name, detail === undefined ? '' : JSON.stringify(detail))
}
async function until<T>(test: () => T | Promise<T>, what: string, ms = 10_000): Promise<NonNullable<T>> {
  const end = Date.now() + ms
  while (Date.now() < end) {
    const value = await test()
    if (value) return value
    await pause(100)
  }
  throw new Error('timed out waiting for ' + what)
}

// Page helpers, installed in each new document: fields by their label, buttons and links by their text.
const HELPERS = `
window.__t = {
  field(label, scope = document) {
    for (const l of scope.querySelectorAll('label')) {
      if (l.textContent.trim() === label) return l.htmlFor ? document.getElementById(l.htmlFor) : l.querySelector('input')
    }
    const named = [...scope.querySelectorAll('input[aria-label]')].find((i) => i.getAttribute('aria-label') === label)
    if (named) return named
    throw new Error('no field ' + label)
  },
  fill(label, value, scope) {
    const input = this.field(label, scope)
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  },
  button(name, scope = document) {
    return [...scope.querySelectorAll('button, a')].find((b) => b.textContent.trim() === name && !b.disabled) ?? null
  },
  named(name, scope = document) {
    return [...scope.querySelectorAll('button[aria-label]')].find((b) => b.getAttribute('aria-label') === name) ?? null
  },
  row(text) {
    return [...document.querySelectorAll('tbody tr')].find((r) => r.innerText.includes(text)) ?? null
  },
  choose(label) {
    [...document.querySelectorAll('label')].find((l) => l.textContent.trim() === label).querySelector('input').click()
  },
}`

app.whenReady().then(async () => {
  let bridge: typeof import('../../client/src/main/bridge.ts')
  let security: typeof import('../../client/src/main/window.ts')
  let server: ServerDescription
  try {
    bridge = await import(pathToFileURL(path.join(client, 'out/main/bridge.js')).href)
    security = await import(pathToFileURL(path.join(client, 'out/main/window.js')).href)
    server = JSON.parse(fs.readFileSync(path.join(run, 'server.json'), 'utf8'))
  } catch (e) {
    fail('loading the built main process and the server description', e)
  }
  app.on('web-contents-created', (_event, contents) => security.confine(contents))
  security.permitMedia(session.defaultSession, security.appPageMatcher(pageUrl)) // H48, H54, as the app's main process
  const serverClient = bridge.registerBridge(server.url)
  const identifyRuns: IdentifyRun[] = []
  if (process.env.MBS_CHECK_IDENTIFY_METHODS) {
    const identify = serverClient.identify.bind(serverClient)
    serverClient.identify = (runId, emit, algorithm, captureFrom) => {
      const trace: IdentifyRun = { algorithm, captureFrom, events: [] }
      identifyRuns.push(trace)
      return identify(runId, (event) => {
        const { type, completed, total } = event as IdentifyEvent
        trace.events.push({ type, ...(completed === undefined ? {} : { completed }), ...(total === undefined ? {} : { total }) })
        emit(event)
      }, algorithm, captureFrom)
    }
  }
  await session.defaultSession.clearCache()

  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    show: false,
    useContentSize: true,
    webPreferences: {
      ...security.webPreferences(path.join(client, 'out/preload/index.cjs')),
      offscreen: true,
      backgroundThrottling: false,
    },
  })
  win.webContents.setFrameRate(30)
  const messages: string[] = []
  win.webContents.on('console-message', (event) => {
    if (event.level === 'error' || event.level === 'warning') messages.push(`${event.level}: ${event.message}`)
  })

  const page = (code: string) => win.webContents.executeJavaScript(`(async () => { ${code}\n})()`)
  const has = (text: string): Promise<boolean> => page(`return document.body.innerText.includes(${JSON.stringify(text)})`)
  const waitText = (text: string, ms?: number) => until(() => has(text), JSON.stringify(text), ms)
  const fill = (label: string, value: string, scope = 'document') =>
    page(`window.__t.fill(${JSON.stringify(label)}, ${JSON.stringify(value)}, ${scope})`)
  const click = async (name: string, scope = 'document') => {
    const find = `window.__t.button(${JSON.stringify(name)}, ${scope})`
    await until(() => page(`return Boolean(${find})`), 'the control ' + name)
    await page(`${find}.click()`)
  }
  const capture = async (file: string) => {
    for (let attempt = 1; ; attempt += 1) {
      try {
        fs.writeFileSync(path.join(out, `${file}.png`), (await win.webContents.capturePage()).toPNG())
        return
      } catch (e) {
        // An offscreen window that was just resized may have no frame to give for a moment.
        if (attempt >= 4) throw e
        await pause(400)
      }
    }
  }
  // MBS_CHECK_SHOTS (the review of a visual change, H22): each screenshot is also taken in both themes at the client's
  // default window (1280 x 820) and its smallest (1024 x 680), into matrix/, and the page is searched for anything
  // that runs off the window or is cut; the findings go to layout.json. The theme and the size are put back after.
  const shot = async (name: string) => {
    await pause(500)
    await capture(name)
    if (!process.env.MBS_CHECK_SHOTS) return
    const theme = nativeTheme.themeSource
    const [width, height] = win.getContentSize() as [number, number]
    for (const each of ['light', 'dark'] as const) {
      nativeTheme.themeSource = each
      for (const [w, h] of [[1280, 820], [1024, 680]] as const) {
        win.setContentSize(w, h)
        await pause(400)
        layout.push({ shot: name, theme: each, size: `${w}x${h}`, problems: await page(LAYOUT_PROBLEMS) })
        await capture(path.join('matrix', `${name}--${each}-${w}x${h}`))
      }
    }
    nativeTheme.themeSource = theme
    win.setContentSize(width, height)
    await pause(300)
  }
  const loaded = () => new Promise<void>((resolve) => win.webContents.once('did-finish-load', () => resolve()))
  const direction = () => page(`return document.documentElement.dir`)
  // H44: a pore method's result shows its counted pore pairs, one line per point of the deciding score.
  // H22: a 1:1 result on its stage: the moment plays to its end, the verdict's words are shown, the count is the
  // deciding score, and the arrow keys and the pointer follow single pairs. The count reads 0 before the moment
  // starts, so the moment has ended only once the verdict is shown and the pair line has its hint, or, for a
  // comparison without pairs, the count is still 0.
  const stageSettled = () => until(() => page(`return Boolean(document.querySelector('.match-headline h2.shown')) &&
    ((document.querySelector('.match-pair')?.textContent ?? '') !== '' ||
    document.querySelector('.match-count strong')?.textContent === '0')`), 'the result moment to end', 15_000)
  const checkStage = async (what: string) => {
    await stageSettled()
    await pause(400)
    check(`${what}: the stage shows the verdict and counts the deciding score`, await page(`
      const canvas = document.querySelector('.match-stage canvas')
      const score = Number(document.querySelector('.match-count strong').textContent)
      const saved = Number((document.body.innerText.match(/highest of the three scores is ([0-9]+)/) ?? [])[1])
      return canvas.width > 0 && canvas.height > 0 && score === saved &&
        document.querySelector('.match-headline h2').classList.contains('shown')`))
    // After the motion review: the stage faded in as one, the explanation entered with the verdict, and the
    // verdict is read out once from its own status line, never the climbing count.
    check(`${what}: the stage faded in, the explanation entered with the verdict, and only the verdict is read out`, await page(`
      const status = document.querySelector('.match-result [role=status]')
      return document.querySelector('.match-stage').classList.contains('ready') &&
        [...document.querySelectorAll('.match-later')].every((line) => line.classList.contains('shown')) &&
        status !== null && status.textContent.startsWith(document.querySelector('.match-headline h2').textContent) &&
        document.querySelector('.match-count').getAttribute('aria-hidden') === 'true'`))
  }
  const checkPoreView = async (method: string, name: string) => {
    await checkStage(method)
    await page('document.querySelector(".match-stage").scrollIntoView({ block: "center" })')
    await shot(`${name}-matches-light`)
    nativeTheme.themeSource = 'dark'
    await shot(`${name}-matches-dark`)
    nativeTheme.themeSource = 'light'
    await page('window.scrollTo(0, 0)')
  }
  const strength = () => page(`return document.querySelector('.meter [role=status]')?.textContent ?? ''`)
  const signInPage = 'Sign in with your username or email.'

  try {
    if (pageUrl) await win.loadURL(pageUrl)
    else await win.loadFile(path.join(client, 'out/renderer/index.html'))
    await page(HELPERS)

    // 1. Before anyone signs in: the sign-in screen, in English (H31) and Windows' setting.
    await waitText(signInPage, 20_000)
    check('the window opens at sign-in, in English, left to right', (await direction()) === 'ltr')
    await pause(600)
    check('the server answers the health check', !(await has('The server is not running')))
    check("before sign-in the window follows Windows' setting", nativeTheme.themeSource === 'system', nativeTheme.themeSource)
    await until(() => win.getTitle() === 'Identification System', 'the English title').catch(() => {})
    check('the window title is the English name', win.getTitle() === 'Identification System', win.getTitle())
    await shot('01-sign-in')

    // 2. What the page can and cannot reach.
    const probe = await page(`
      const opened = window.open('http://127.0.0.1:9/')
      let direct
      try { await fetch(${JSON.stringify(server.url)} + '/api/health'); direct = 'reached' } catch { direct = 'blocked' }
      const unknown = await window.mbs.call('constructor')
      let camera, microphone
      try { (await navigator.mediaDevices.getUserMedia({ video: true })).getTracks().forEach((t) => t.stop()); camera = 'granted' } catch (e) { camera = e.name }
      try { (await navigator.mediaDevices.getUserMedia({ audio: true })).getTracks().forEach((t) => t.stop()); microphone = 'granted' } catch (e) { microphone = e.name }
      let both
      try { (await navigator.mediaDevices.getUserMedia({ video: true, audio: true })).getTracks().forEach((t) => t.stop()); both = 'granted' } catch (e) { both = e.name }
      const displays = await window.mbs.displays()
      return { require: typeof require, process: typeof process, bridge: Object.keys(window.mbs).sort(),
               opened: opened === null ? 'denied' : 'opened', direct, unknown: unknown.error, camera, microphone, both, displays }`)
    check('the page has no Node.js', probe.require === 'undefined' && probe.process === 'undefined', probe)
    check('the bridge offers only its eighteen named functions (H41, H48, H60)', JSON.stringify(probe.bridge) ===
      '["call","cancelEnrolment","cancelFusion","cancelIdentification","cancelVerification","displays","enrolFingerprint","fuse","identifyFingerprint","onDisplays","onEnrolment","onFusion","onIdentification","onLink","onVerification","setTheme","takeLink","verifyFingerprint"]', probe.bridge)
    check('the page cannot reach the server directly (CSP)', probe.direct === 'blocked', probe.direct)
    check('the bridge refuses a route outside its list', probe.unknown === 'unknown_route', probe.unknown)
    check('the page cannot open windows', probe.opened === 'denied' && BrowserWindow.getAllWindows().length === 1)
    check('the camera alone and the microphone alone are granted to the app page, never both at once (H48, H54)',
      probe.camera === 'granted' && probe.microphone === 'granted' && probe.both !== 'granted',
      { camera: probe.camera, microphone: probe.microphone, both: probe.both })
    // With the lid closed and two external monitors, Windows has no internal display (WMI, 2026-11-09).
    check('the main process reports the built-in screen as off while the lid is closed (H48)',
      probe.displays && probe.displays.internalDisplay === false, probe.displays)
    const address = win.webContents.getURL()
    await page(`location.href = 'http://127.0.0.1:9/'`).catch(() => {})
    await pause(800)
    check('the page cannot navigate away', win.webContents.getURL() === address, win.webContents.getURL())

    // 3. Registration with the mobile phone (H29) and the meter (H30) signs the new account in.
    await click('Register')
    await waitText('New account')
    await fill('Username', 'dana')
    await fill('Email', 'dana@example.com')
    await fill('Mobile phone', '050-123-4567')
    const levels: string[] = []
    for (const typed of ['dana', 'DANA2026', 'Dana2026', 'Dana password 1']) {
      await fill('Password', typed)
      levels.push(await strength())
    }
    check('the meter shows invalid, weak, medium and strong while typing', JSON.stringify(levels) ===
      JSON.stringify(['Password strength: Invalid', 'Password strength: Weak', 'Password strength: Medium', 'Password strength: Strong']), levels)
    const eye = "window.__t.named('Show password')"
    const before = await page(`return window.__t.field('Password').type`)
    await page(`${eye}.click()`)
    const after = await page(`return window.__t.field('Password').type`)
    check('the eye shows the password, and shows it is shown', before === 'password' && after === 'text' &&
      (await page(`return Boolean(window.__t.named('Hide password'))`)), { before, after })
    await fill('National ID', '000000018')
    await shot('02-register')
    await page(`window.__t.named('Hide password').click()`)
    await click('Create the account')
    await waitText('Hello, dana')
    check('registration signs the new account in, to the home screen', true)
    // The greeting comes first; the modalities follow the home screen's own request to the server.
    const countUnenrolled = () => page(`return document.body.innerText.split('Not enrolled yet').length - 1`)
    const unenrolled = await until(async () => ((await countUnenrolled()) === 3 ? 3 : false), "the home screen's modalities")
      .catch(countUnenrolled)
    check('the home screen shows the three modalities, none enrolled', unenrolled === 3, unenrolled)
    // The token is the client's own, private field: the check looks inside it on purpose.
    const token = (serverClient as unknown as { token: string | null }).token
    const leak = await page(`return { storage: localStorage.length + sessionStorage.length, cookie: document.cookie,
      found: document.documentElement.outerHTML.includes(${JSON.stringify(token)}) ||
             JSON.stringify(await window.mbs.call('me')).includes(${JSON.stringify(token)}) }`)
    check('the session token stays in the main process', typeof token === 'string' && token.length > 20 &&
      leak.storage === 0 && leak.cookie === '' && !leak.found, leak)
    await shot('03-home')

    // H60: the combined test's card and page; with nothing enrolled it asks for a finger and one more modality first.
    await page(`[...document.querySelectorAll('.card')].find((c) => c.querySelector('h2')?.textContent === 'Combined test').querySelector('a').click()`)
    await waitText('The combined test needs an enrolled finger and at least one more modality')
    const weights = await page(`return [...document.querySelectorAll('.points-list__weight b')].map((b) => b.textContent).join(',')`)
    check('the combined test shows each modality’s points and asks for its enrolments first (H60)', weights === '55,25,20', weights)
    await shot('03f-fusion')
    await click('Back home')
    await waitText('Hello, dana')

    // 3b. Fingerprint enrolment (H33), when the throwaway server has the real engines and stored captures
    // (MBS_CHECK_CAPTURES): only the scanner is replaced, by one that hands over three placements of a finger.
    if (server.fingerprint) {
      await click('Open')
      await waitText('Choose a finger. Verify an enrolled finger')
      if (process.env.MBS_CHECK_IDENTIFY) {
        await click('Identify a fingerprint (1:N)')
        await waitText('Enrol at least one of your fingers')
        check('identification offers enrolment before the caller has an enrolled finger', !await has('Start identification'))
        await click('Choose a finger to enrol')
      }
      const leftHand = `[...document.querySelectorAll('fieldset')].find((f) => f.querySelector('legend')?.textContent === 'Left hand')`
      await until(() => page(`return Boolean(${leftHand})`), 'the hands')
      await page(`${leftHand}.querySelectorAll('button')[1].click()`)
      await shot('03a-fingers')
      await click('Enrol this finger')
      await waitText('How your fingerprint is stored', 90_000)
      check('three stored placements enrol the finger with the real engines and open the template screen', true)
      await shot('03b-journey-1-captures')
      const quality = await page(`return [...document.querySelectorAll('.checks li')].map((li) => li.innerText).join(' | ')`)
      check("the captures show H7's checks and the NFIQ 2 score", quality.includes('Quality (NFIQ 2)') && quality.includes('NFIQ 2 score'), quality)
      for (const name of ['2-points', '3-vector', '4-template', '5-database', '6-accepted']) {
        await click('Next')
        if (name === '3-vector') {
          await page(`const c = document.querySelector('.print canvas'); const r = c.getBoundingClientRect();
            c.dispatchEvent(new PointerEvent('pointermove', { clientX: r.left + r.width * 0.52, clientY: r.top + r.height * 0.48, bubbles: true }))`)
          await waitText('Show the 128 numbers')
          check('a point under the pointer shows its 128-number vector', await has('Point '))
        }
        if (name === '5-database') check('the database step shows the sealed row', (await has('opencv-sift')) && (await has('MBS1 header: 4 bytes')))
        if (name === '6-accepted') check('the last step shows the three pair scores above 57', (await page(`return document.querySelectorAll('.pairs li.met').length`)) === 3)
        await shot(`03b-journey-${name}`)
      }
      if (await has('Show the 128 numbers')) check('unexpected', false)
      await click('Done')
      await waitText('Enrol this finger again')
      check('after the enrolment the finger shows as enrolled', await has('enrolled'))
      await click('Home')
      await waitText('Enrolled: left index')
      check('the home card lists the enrolled finger', true)
      // H34: deleting the finger's enrolment, after a confirmation, with no new enrolment.
      await click('Open')
      await until(() => page(`return Boolean(${leftHand})`), 'the hands')
      await page(`${leftHand}.querySelectorAll('button')[1].click()`)
      // H35: a different finger, the same finger, cancellation and retry, with real engines.
      const captures = process.env.MBS_CHECK_CAPTURES
      if (!captures) throw new Error('the fingerprint steps need MBS_CHECK_CAPTURES')
      const captureFiles = fs.readdirSync(captures)
      // A stored capture by finger position and placement, named as ScannerCapture names them (SESSION_fNN_pN_...).
      const captureFile = (finger: number, placement: number) => {
        const label = `_f${String(finger).padStart(2, '0')}_p${placement}_`
        const name = captureFiles.find((file) => file.includes(label) && file.endsWith('.png'))
        if (!name) throw new Error(`MBS_CHECK_CAPTURES has no capture of finger ${finger}, placement ${placement}`)
        return path.join(captures, name)
      }
      const nextScan = (file: string) => fs.writeFileSync(path.join(run, 'scanner.json'), JSON.stringify([{ wait: 'finger', file }]))
      nextScan(captureFile(2, 1))
      await click('Verify this finger (1:1)')
      check('choosing a method does not start the scanner', await has('Choose how to compare') && !await has('Place the selected finger'))
      await click('Start verification')
      await waitText('Fingerprint does not match', 90_000)
      check('a different finger is a completed non-match', await has('The result and its encrypted capture were saved.'))
      check('all three comparison scores are shown', await page('return document.querySelectorAll("tbody tr").length === 3'))
      await shot('03d-verification-non-match')
      if (process.env.MBS_CHECK_MATCH_VIEW) {
        await checkStage('a completed non-match')
        await page('document.querySelector(".match-stage").scrollIntoView({ block: "center" })')
        await shot('03m-non-match')
      }
      nextScan(captureFile(7, 3))
      await click('Verify again')
      await waitText('Fingerprint matches', 90_000)
      if (process.env.MBS_CHECK_MATCH_VIEW) {
        // H22: Escape anywhere on the page plays out the rest of the moment, here one that skips the tilt because
        // a result was shown before it, and ends in 800 ms on its own.
        const pressed = Date.now()
        await page(`document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`)
        await until(() => page(`return (document.querySelector('.match-pair')?.textContent ?? '') !== ''`), 'the moment to end after Escape', 5_000)
        const ended = Date.now() - pressed
        check('Escape on the page plays out the rest of the moment at once', ended < 500, `${ended} ms`)
      }
      check('the same finger matches the stored templates', await has('The result and its encrypted capture were saved.'))
      nativeTheme.themeSource = 'light'
      await shot('03e-verification-match-light')
      await page('document.querySelector(".verification-details").open = true')
      await shot('03f-verification-details')
      nativeTheme.themeSource = 'dark'
      await shot('03g-verification-match-dark')
      nativeTheme.themeSource = 'light'
      if (process.env.MBS_CHECK_MATCH_VIEW) {
        await checkStage('a match')
        await page('document.querySelector(".match-stage").scrollIntoView({ block: "center" })')
        await shot('03m-matches-light')
        const key = (name: string) => page(`document.querySelector('.match-stage').dispatchEvent(new KeyboardEvent('keydown', { key: ${JSON.stringify(name)}, bubbles: true }))`)
        await key('ArrowRight')
        await key('ArrowRight')
        await waitText('Pair 2 of')
        const chosenBefore = await page('return document.querySelector(".match-pair").textContent')
        check('the arrow keys follow one pair, with its places in the native image frames', /^Pair 2 of \d+: new \(\d+, \d+\), stored \(\d+, \d+\)$/.test(chosenBefore), chosenBefore)
        await page(`const stage = document.querySelector('.match-stage'); const box = stage.getBoundingClientRect();
          stage.dispatchEvent(new PointerEvent('pointermove', { clientX: box.left + box.width * 0.3, clientY: box.top + box.height * 0.5, bubbles: true }))`)
        await pause(300)
        const chosenAfter = await page('return document.querySelector(".match-pair").textContent')
        check('the pointer follows the pair nearest to it', chosenAfter.startsWith('Pair ') && chosenAfter !== chosenBefore, chosenAfter)
        nativeTheme.themeSource = 'dark'
        await shot('03m-highlight-dark')
        nativeTheme.themeSource = 'light'
      }
      await click('Back to the fingers')
      if (process.env.MBS_CHECK_PORE) {
        fs.writeFileSync(path.join(run, 'enable-pore'), 'yes')
        await click('Home')
        await click('Open')
        await until(() => page(`return Boolean(${leftHand})`), 'the fingers before method choice')
        await page(`${leftHand}.querySelectorAll('button')[1].click()`)
        await click('Verify this finger (1:1)')
        const poreRadio = `document.querySelector('input[value="pore-sift"]')`
        // Reopening the page reloads availability after the test server enables the new method.
        await until(async () => {
          if (await page(`return ${poreRadio} && !${poreRadio}.disabled`)) return true
          await click('Home')
          await click('Open')
          await until(() => page(`return Boolean(${leftHand})`), 'the fingers before refreshed method choice')
          await page(`${leftHand}.querySelectorAll('button')[1].click()`)
          await click('Verify this finger (1:1)')
          return false
        }, 'Pore SIFT availability')
        await page(`${poreRadio}.click()`)
        check('method choices fit the page and keep native radio sizes', await page(`return document.documentElement.scrollWidth <= innerWidth &&
          [...document.querySelectorAll('.method-choice input')].every((input) => input.getBoundingClientRect().width < 40)`))
        await shot('03p-method-choice')
        nextScan(captureFile(7, 3))
        await click('Start verification')
        await waitText('Creating Pore SIFT templates', 90_000)
        await shot('03p-preparing-existing')
        await waitText('Fingerprint matches', 90_000)
        check('Pore SIFT prepares existing captures and saves its own verification', await has('Matching pores'))
        check('Pore SIFT marks its threshold provisional', await has('This threshold is provisional'))
        await shot('03p-result-light')
        nativeTheme.themeSource = 'dark'
        await shot('03p-result-dark')
        nativeTheme.themeSource = 'light'
        if (process.env.MBS_CHECK_MATCH_VIEW) await checkPoreView('Pore SIFT', '03q-pore-sift')
        nextScan(captureFile(2, 1))
        await click('Verify again')
        await waitText('Fingerprint does not match', 90_000)
        check('Pore SIFT rejects a different finger', await has('The result and its encrypted capture were saved.'))
        if (process.env.MBS_CHECK_MATCH_VIEW) await checkStage('a Pore SIFT non-match')
        // H59: a non-match offers another method too, which compares the same capture again: no scan is queued, so a
        // new scan would wait for a finger that never comes.
        await click('Change method')
        await waitText('The capture from')
        check('a result\'s capture is offered to another method, marked with the method that compared it',
          await has('Pore SIFT: no match') && await has('already compared'))
        await page(`document.querySelector('input[value="opencv-sift"]').click()`)
        await shot('03r-capture-again')
        const scans = JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length
        await click('Compare the same capture')
        await waitText('Fingerprint does not match', 90_000)
        check('OpenCV SIFT compares the same capture again without the scanner (H59)',
          JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length === scans &&
          await has('The same capture as at') && await has('(Pore SIFT).'))
        await shot('03r-capture-again-result')
        await click('Back to the fingers')
      }
      if (process.env.MBS_CHECK_LEARNED) {
        await click('Verify this finger (1:1)')
        await page(`document.querySelector('input[value="learned-pore"]').click()`)
        await shot('03l-method-choice-light')
        nativeTheme.themeSource = 'dark'
        await shot('03l-method-choice-dark')
        nativeTheme.themeSource = 'light'
        nextScan(captureFile(7, 3))
        await click('Start verification')
        await waitText('Creating Pore CNN templates', 90_000)
        await shot('03l-preparing-existing')
        await waitText('Fingerprint matches', 90_000)
        check('Pore CNN prepares existing captures and matches its own native templates', await has('Matching pores') && await has('Match above 21'))
        await shot('03l-result-light')
        nativeTheme.themeSource = 'dark'
        await shot('03l-result-dark')
        nativeTheme.themeSource = 'light'
        if (process.env.MBS_CHECK_MATCH_VIEW) await checkPoreView('Pore CNN', '03q-learned')
        nextScan(captureFile(2, 1))
        await click('Verify again')
        await waitText('Fingerprint does not match', 90_000)
        check('Pore CNN rejects a different finger', await has('The result and its encrypted capture were saved.'))
        await click('Back to the fingers')
        const placements = captureFiles.filter((name) => /_f07_p[123]_.*\.png$/.test(name)).sort()
        if (placements.length !== 3) throw new Error('expected three stored left-index placements')
        const steps = placements.flatMap((name) => [{ wait: 'finger', file: path.join(captures, name) }, { wait: 'lift' }])
        fs.writeFileSync(path.join(run, 'scanner.json'), JSON.stringify(steps.slice(0, -1)))
        await click('Enrol this finger again')
        await waitText('How your fingerprint is stored', 90_000)
        check('a new generic enrolment stores templates for all three methods', await has('Templates stored for: OpenCV SIFT, Pore SIFT, Pore CNN.'))
        await click('The points')
        check('the point and vector demonstration explicitly names OpenCV SIFT', await has('Template demonstration: OpenCV SIFT'))
        await shot('03l-template-label')
        await click('In the database')
        await shot('03l-three-methods-stored')
        await click('Why it was accepted')
        check('enrolment approval and the other two methods have separate pair scores', await page('return document.querySelectorAll(".pairs li").length === 9 && document.querySelectorAll(".method-comparison").length === 2'))
        await shot('03l-enrolment-comparisons-light')
        nativeTheme.themeSource = 'dark'
        await shot('03l-enrolment-comparisons-dark')
        nativeTheme.themeSource = 'light'
        await click('Done')
      }
      await click('Settings')
      await page(`window.__t.choose('עברית')`)
      await waitText('הגדרות')
      await click('מסך הבית')
      await click('פתיחה')
      const leftHebrew = `[...document.querySelectorAll('fieldset')].find((f) => f.querySelector('legend')?.textContent === 'יד שמאל')`
      await until(() => page(`return Boolean(${leftHebrew})`), 'the Hebrew hands')
      await page(`${leftHebrew}.querySelectorAll('button')[1].click()`)
      nextScan(captureFile(7, 3))
      await click('אימות האצבע הזו (1:1)')
      if (process.env.MBS_CHECK_LEARNED) await page(`document.querySelector('input[value="learned-pore"]').click()`)
      else if (process.env.MBS_CHECK_PORE) await page(`document.querySelector('input[value="pore-sift"]').click()`)
      await shot('03l-method-choice-hebrew')
      // H22 after the motion review: with reduced motion the result is drawn finished, and the lines that explain
      // it appear with the verdict by their fade alone, without rising or waiting. Chromium's own emulation sets it.
      const reduce = (on: boolean) => win.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',
        { features: [{ name: 'prefers-reduced-motion', value: on ? 'reduce' : 'no-preference' }] })
      if (process.env.MBS_CHECK_MATCH_VIEW) {
        win.webContents.debugger.attach('1.3')
        await reduce(true)
      }
      await click('התחלת האימות')
      await waitText('נמצאה התאמה לטביעת האצבע', 90_000)
      if (process.env.MBS_CHECK_MATCH_VIEW) {
        const arrived = Date.now()
        await until(() => page(`return (document.querySelector('.match-pair')?.textContent ?? '') !== ''`), 'the result with reduced motion', 5_000)
        const settled = Date.now() - arrived
        check('with reduced motion the result is drawn finished, and its lines neither rise nor wait', settled < 600 && await page(`
          const lines = [...document.querySelectorAll('.match-later')]
          return lines.length > 0 && lines.every((line) => line.classList.contains('shown') && getComputedStyle(line).transitionDelay === '0s')`),
        `${settled} ms`)
        await reduce(false)
        win.webContents.debugger.detach()
      }
      check('verification runs in Hebrew and right to left', await direction() === 'rtl')
      if (process.env.MBS_CHECK_PORE) check('Pore SIFT result is explained in Hebrew', await has('נקבוביות תואמות') && await has('הסף הזה זמני'))
      await shot('03g-verification-hebrew-light')
      nativeTheme.themeSource = 'dark'
      await shot('03g-verification-hebrew-dark')
      if (process.env.MBS_CHECK_MATCH_VIEW) {
        await stageSettled()
        check('the Hebrew stage keeps both captures in their own left and right', await page('return getComputedStyle(document.querySelector(".match-plates")).direction === "ltr"'))
        await page('document.querySelector(".match-stage").scrollIntoView({ block: "center" })')
        await shot('03m-matches-hebrew-dark')
      }
      nativeTheme.themeSource = 'light'
      await click('הגדרות')
      await page(`window.__t.choose('English')`)
      await waitText('Settings')
      await click('Home')
      await click('Open')
      await until(() => page(`return Boolean(${leftHand})`), 'the hands again')
      await page(`${leftHand}.querySelectorAll('button')[1].click()`)
      fs.writeFileSync(path.join(run, 'scanner.json'), JSON.stringify([{ hang: true }]))
      await click('Verify this finger (1:1)')
      await click('Start verification')
      await waitText('Place the selected finger on the scanner')
      await shot('03h-verification-capture')
      await click('Cancel')
      await waitText('Verification cancelled.')
      check('cancelling a real stream ends the scanner wait', true)
      nextScan(captureFile(7, 3))
      await click('Try again')
      await waitText('Fingerprint matches', 90_000)
      check('a verification after cancellation completes', true)
      win.setContentSize(1024, 680)
      check('the result fits the minimum window width', await page('return document.documentElement.scrollWidth <= innerWidth'))
      await shot('03i-verification-small')
      win.setContentSize(1280, 820)
      await click('Back to the fingers')
      if (process.env.MBS_CHECK_IDENTIFY) {
        nextScan(captureFile(7, 3))
        await click('Identify a fingerprint (1:N)')
        await waitText('Find the closest enrolled fingerprint')
        check('identification waits for an explicit start without selecting a finger',
          JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length === 1)
        await shot('03n-ready')
        await click('Start identification')
        await waitText('A matching fingerprint was found', 90_000)
        check('1:N finds the callers finger in the real two-account gallery',
          await has('Your left index') && await has('2 finger enrolments, 6 templates'))
        check('the ranking contains anonymous candidates without other account details',
          await has('Another registered user') && !await has('gallery-user') && !await has('gallery@example.org') &&
          await page('return document.querySelectorAll("tbody tr").length === 2'))
        await shot('03n-own-result-light')
        nativeTheme.themeSource = 'dark'
        await shot('03n-own-result-dark')
        nativeTheme.themeSource = 'light'
        // H45: the drawing shows the caller's own highest-ranked print, one line per point of its score.
        const ownDrawing = (rank: number) => page(`
          const row = [...document.querySelectorAll('tbody tr')].find((tr) => tr.innerText.includes('Your left index'))
          const score = Number(row?.querySelectorAll('td')[2]?.textContent ?? -1)
          const paths = document.querySelector('.match-connections')?.getAttribute('d') ?? ''
          return document.body.innerText.includes('rank ${rank} in the list') && score >= 0 &&
            (paths.match(/M/g) ?? []).length === score && document.querySelectorAll('.match-drawing image').length === 2
        `)
        if (process.env.MBS_CHECK_MATCH_VIEW) {
          check('the 1:N result draws the caller’s own leading print', await ownDrawing(1))
          await page('document.querySelector(".match-view").scrollIntoView({ block: "start" })')
          await shot('03r-own-matches-light')
          await page('window.scrollTo(0, 0)')
        }
        nextScan(captureFile(2, 3))
        await click('Identify again')
        await waitText('A matching fingerprint was found', 90_000)
        check('1:N can match a different account while keeping it anonymous',
          await page('return document.querySelector(".verification-result").innerText.includes("Another registered user")'))
        await shot('03n-other-result')
        if (process.env.MBS_CHECK_MATCH_VIEW) {
          check('when another user leads, only the caller’s own print is drawn', await ownDrawing(2))
          await page('document.querySelector(".match-view").scrollIntoView({ block: "start" })')
          await shot('03r-other-leads')
          await page('window.scrollTo(0, 0)')
        }
        nextScan(captureFile(4, 1))
        await click('Identify again')
        await waitText('No matching fingerprint was found', 90_000)
        check('1:N saves a completed non-match', await has('The result and its encrypted capture were saved.'))
        await shot('03n-not-found')
        fs.writeFileSync(path.join(run, 'scanner.json'), JSON.stringify([{ hang: true }]))
        await click('Identify again')
        await waitText('Place the finger you want to identify')
        await shot('03n-capture-progress')
        await click('Cancel')
        await waitText('Identification cancelled.')
        check('1:N cancellation ends the real streamed capture', !await has('The result and its encrypted capture were saved.'))
        await pause(300)
        nextScan(captureFile(7, 3))
        await click('Try again')
        await waitText('A matching fingerprint was found', 90_000)
        check('1:N completes after cancellation', await has('Your left index'))
        if (process.env.MBS_CHECK_IDENTIFY_METHODS) {
          const poreRadio = 'document.querySelector(\'input[value="pore-sift"]\')'
          const learnedRadio = 'document.querySelector(\'input[value="learned-pore"]\')'
          const lastRun = () => {
            const trace = identifyRuns.at(-1)
            if (!trace) throw new Error('no identification ran')
            return trace
          }
          const preparation = () => lastRun().events.filter((event) => event.type === 'preparing_templates')
          await click('Change method')
          await until(() => page(`return Boolean(${poreRadio} && ${learnedRadio})`), 'the identification methods')
          check('identification disables the unavailable pore engines', await page(`return ${poreRadio}.disabled && ${learnedRadio}.disabled`))
          fs.writeFileSync(path.join(run, 'enable-pore'), 'yes')
          await until(async () => {
            const result = await serverClient.call('fingerprintMethods')
            return result.ok && (result.data as { methods: { available: boolean }[] }).methods.filter((method) => method.available).length === 3
          }, 'all three engines to be configured')
          await click('Back to the fingers')
          await click('Home')
          await click('Open')
          await click('Identify a fingerprint (1:N)')
          await until(() => page(`return ${poreRadio} && !${poreRadio}.disabled && ${learnedRadio} && !${learnedRadio}.disabled`), 'all three identification choices')
          nextScan(captureFile(7, 3))
          const count = identifyRuns.length
          await page(`${poreRadio}.click()`)
          check('choosing Pore SIFT does not start identification or the scanner',
            identifyRuns.length === count && JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length === 1)
          await shot('03n-pore-method-choice-light')
          nativeTheme.themeSource = 'dark'
          await shot('03n-pore-method-choice-dark')
          nativeTheme.themeSource = 'light'
          await click('Start identification')
          await waitText('Creating Pore SIFT templates', 90_000)
          await until(() => preparation().some((event) => event.completed === 1), 'a completed pore template', 90_000)
          await shot('03n-pore-gallery-preparation')
          await click('Cancel')
          await waitText('Identification cancelled.')
          check('cancelling 1:N gallery preparation leaves the scanner unused',
            JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length === 1 &&
            !lastRun().events.some((event) => event.type === 'identified'))
          await pause(350)
          await click('Try again')
          await waitText('A matching fingerprint was found', 120_000)
          check('Pore SIFT prepares both accounts and finds the enrolled finger on retry',
            lastRun().algorithm === 'pore-sift' && preparation().at(-1)?.completed === 6 &&
            await has('Your left index') && await has('Match above 37') && await has('Matching pores') &&
            await has('This threshold is provisional'))
          await shot('03n-pore-identification-light')
          nextScan(captureFile(2, 3))
          await click('Identify again')
          await waitText('A matching fingerprint was found', 90_000)
          check('Pore SIFT reuses prepared templates and finds another account anonymously',
            preparation().length === 0 && await page('return document.querySelector(".verification-result").innerText.includes("Another registered user")'))
          await click('Change method')
          await until(() => page(`return ${learnedRadio} && !${learnedRadio}.disabled`), 'the Pore CNN choice')
          check('the change-method shortcut keeps the previous choice until it is changed', await page(`return ${poreRadio}.checked`))
          // H59: Pore CNN searches the same capture again instead of a new scan.
          check('the search\'s capture is offered to another method', await has('The capture from') && await has('already compared'))
          await page(`${learnedRadio}.click()`)
          await shot('03s-capture-again-identification')
          const scans = JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length
          await click('Compare the same capture')
          await waitText('A matching fingerprint was found', 90_000)
          check('Pore CNN prepares its own gallery and shows its threshold and ranking',
            lastRun().algorithm === 'learned-pore' && preparation().at(-1)?.completed === 6 &&
            await has('Pore CNN') && await has('Match above 21') && await has('Matching pores') &&
            await page('return document.querySelector(".verification-result").innerText.includes("Another registered user")'))
          check('Pore CNN searches the same capture again without the scanner (H59)',
            typeof lastRun().captureFrom === 'string' &&
            JSON.parse(fs.readFileSync(path.join(run, 'scanner.json'), 'utf8')).length === scans &&
            await has('The same capture as at') && await has('(Pore SIFT).'))
          await shot('03n-learned-identification-light')
          nextScan(captureFile(4, 1))
          await click('Identify again')
          await waitText('No matching fingerprint was found', 90_000)
          check('Pore CNN records a non-match and reuses prepared templates',
            preparation().length === 0 && await has('The result and its encrypted capture were saved.'))
        }
        await click('Settings')
        await page(`window.__t.choose('עברית')`)
        await click('מסך הבית')
        await click('פתיחה')
        nextScan(captureFile(2, 3))
        await click('זיהוי טביעת אצבע (1:N)')
        if (process.env.MBS_CHECK_IDENTIFY_METHODS) {
          const radio = 'document.querySelector(\'input[value="learned-pore"]\')'
          await until(() => page(`return ${radio} && !${radio}.disabled`), 'the Pore CNN choice in Hebrew')
          await page(`${radio}.click()`)
        }
        await click('התחלת הזיהוי')
        await waitText('נמצאה טביעת אצבע תואמת', 90_000)
        check('1:N is anonymous and right to left in Hebrew', await direction() === 'rtl' && await has('משתמש רשום אחר'))
        if (process.env.MBS_CHECK_IDENTIFY_METHODS) check('the Hebrew result shows the selected method, pore score and threshold',
          await has('Pore CNN') && await has('נקבוביות תואמות') && await has('התאמה מעל 21'))
        check('the Hebrew identification heading preserves the 1:N notation', await page(`const notation = document.querySelector('.identification h1 bdi'); return notation?.textContent === '(1:N)' && getComputedStyle(notation).direction === 'ltr'`))
        await shot('03n-result-hebrew-light')
        nativeTheme.themeSource = 'dark'
        await shot('03n-result-hebrew-dark')
        win.setContentSize(1024, 680)
        check('1:N results fit the minimum window width', await page('return document.documentElement.scrollWidth <= innerWidth'))
        await shot('03n-result-hebrew-small')
        win.setContentSize(1280, 820)
        nativeTheme.themeSource = 'light'
        await click('הגדרות')
        await page(`window.__t.choose('English')`)
        await click('Home')
        await click('Open')
        await until(() => page(`return Boolean(${leftHand})`), 'the fingers after identification')
        await page(`${leftHand}.querySelectorAll('button')[1].click()`)
      }
      // H33, H35 (step 0, b1): reloading the page during an enrolment cancels it in the main process, so the
      // scanner's wait ends at once (the stand-in scanner writes scanner.closed when its input is closed) and the
      // next enrolment finds the scanner free.
      const closedMark = path.join(run, 'scanner.closed')
      fs.rmSync(closedMark, { force: true })
      fs.writeFileSync(path.join(run, 'scanner.json'), JSON.stringify([{ hang: true }]))
      await click('Enrol this finger again')
      await waitText('Place the finger on the scanner and hold it still until it is kept.')
      await shot('03c-enrolment-waiting')
      check('an enrolment waits for the finger before the reload', !fs.existsSync(closedMark))
      const reloadedDuringEnrolment = loaded()
      const reloadAt = Date.now()
      win.webContents.reload()
      await reloadedDuringEnrolment
      await page(HELPERS)
      await until(() => fs.existsSync(closedMark), 'the scanner wait to end after the reload', 10_000)
      check('a reload during an enrolment ends the scanner wait at once', Date.now() - reloadAt < 10_000, `${Date.now() - reloadAt} ms`)
      await until(() => page(`return Boolean(${leftHand})`), 'the fingers after the reload')
      await page(`${leftHand}.querySelectorAll('button')[1].click()`)
      const againSteps = captureFiles.filter((name) => /_f07_p[123]_.*\.png$/.test(name)).sort()
        .flatMap((name) => [{ wait: 'finger', file: path.join(captures, name) }, { wait: 'lift' }])
      fs.writeFileSync(path.join(run, 'scanner.json'), JSON.stringify(againSteps.slice(0, -1)))
      await click('Enrol this finger again')
      await waitText('How your fingerprint is stored', 90_000)
      check('an enrolment after the reload finds the scanner free and completes', !await has('busy'))
      await click('Why it was accepted')
      await click('Done')
      await waitText('Enrol this finger again')
      await click('Delete this finger’s enrolment')
      await waitText('Delete the enrolment of the left index?')
      await shot('03c-delete-confirm')
      await click('Delete')
      await waitText('The enrolment of the left index was deleted.')
      check('a finger’s enrolment is deleted after a confirmation (H34)', await has('Enrol this finger'))
      await click('Home')
      await waitText('Not enrolled yet')
      const none = await page(`return document.body.innerText.split('Not enrolled yet').length - 1`)
      check('after the deletion no modality is enrolled', none === 3, none)
    }

    // 3c. The face (H48), when the throwaway server has the real face engine (MBS_CHECK_FACE). The camera is
    // Chromium's synthetic one, which shows no face: the live view must open it, have the engine look at its
    // frames and keep the button off. Enrolling a real face is the researcher's manual check.
    if (server.face) {
      const openCard = (name: string) => page(`[...document.querySelectorAll('.card')].find((c) => c.querySelector('h2')?.textContent === ${JSON.stringify(name)}).querySelector('a').click()`)
      await waitText('Not enrolled yet')
      await openCard('Face')
      await waitText('The face is recognised by SFace')
      await waitText('Accepts above 0.363')
      check('the face screen shows SFace, its threshold and the enrolment state (H48)',
        (await has('Accepts above 0.363')) && (await has('Not enrolled yet.')) && (await has('99.4%')))
      await shot('h48-a-face-light')
      nativeTheme.themeSource = 'dark'
      await shot('h48-a-face-dark')
      nativeTheme.themeSource = 'light'
      await click('Enrol my face')
      await waitText('Enrolling your face')
      await waitText('Look at the camera.', 30_000)
      await pause(1500)
      const view = await page(`
        const video = document.querySelector('.camera-view video')
        const button = [...document.querySelectorAll('.camera button')].find((b) => b.textContent.trim() === 'Take the image')
        return { width: video.videoWidth, height: video.videoHeight, playing: !video.paused,
                 mirrored: getComputedStyle(video).transform, disabled: button.disabled,
                 pickers: document.querySelectorAll('.camera-picker select').length,
                 guidance: document.querySelector('.guidance').textContent }`)
      check('the live view opens the camera at 1280 x 720, mirrored (H48)',
        view.width === 1280 && view.height === 720 && view.playing && view.mirrored === 'matrix(-1, 0, 0, 1, 0, 0)', view)
      check('the engine answers the live frames: no face in the synthetic picture, so no image can be taken',
        view.disabled === true && view.guidance === 'Look at the camera.', view)
      await shot('h48-b-face-camera-light')
      nativeTheme.themeSource = 'dark'
      await shot('h48-b-face-camera-dark')
      nativeTheme.themeSource = 'light'
      await click('Cancel')
      await waitText('Enrol my face')
      check('cancelling stops the camera', await page(`return document.querySelector('.camera-view video') === null`))
      // H49: verification before an enrolment offers the enrolment first (H15).
      await click('Verify my face (1:1)')
      await waitText('Face verification is not available yet')
      check('face verification before enrolment offers the enrolment first (H15, H49)',
        (await has('Enrol my face')) && (await page(`return document.querySelector('.camera-view video') === null`)))
      await shot('h49-a-face-verify-not-enrolled')
      await click('Enrol my face')
      await waitText('Enrolling your face')
      await waitText('Look at the camera.', 30_000)
      await click('Cancel')
      await waitText('Enrol my face')
      // H50: identification before an enrolment offers the enrolment first (H15), in both themes.
      await click('Identify (1:N)')
      await waitText('Face identification is not available yet')
      check('face identification before enrolment offers the enrolment first (H15, H50)',
        (await has('Enrol my face')) && (await has('Face identification (1:N)')) &&
        (await page(`return document.querySelector('.camera-view video') === null`)))
      await shot('h50-a-face-identify-not-enrolled-light')
      nativeTheme.themeSource = 'dark'
      await shot('h50-a-face-identify-not-enrolled-dark')
      nativeTheme.themeSource = 'light'
      await click('Enrol my face')
      await waitText('Enrolling your face')
      await waitText('Look at the camera.', 30_000)
      await click('Cancel')
      await waitText('Enrol my face')
      // H51: an enrolment of synthetic numbers (no image of a person) opens the 1:1 and 1:N camera screens. There
      // the file stays in a closed menu, a dragged file shows the drop target, and a dropped image without a face
      // is refused with its checks; enrolment offers no file.
      fs.writeFileSync(path.join(run, 'seed-face'), 'dana')
      await until(() => fs.existsSync(path.join(run, 'seed-face.done')), 'the seeded face enrolment', 20_000)
      check('the throwaway server seeded a synthetic face enrolment (H51)',
        fs.readFileSync(path.join(run, 'seed-face.done'), 'utf8') === 'ok', fs.readFileSync(path.join(run, 'seed-face.done'), 'utf8'))
      await click('Home')
      await pause(500)
      await openCard('Face')
      await waitText('Enrol my face again', 20_000)
      await click('Verify my face (1:1)')
      await waitText('Upload an existing image')
      check('verification opens on a choice between the camera and an existing image, with no camera yet (H53)',
        (await has('Live verification')) && (await page(`return document.querySelector('.camera-view video') === null`)))
      await shot('h53-a-choice-light')
      nativeTheme.themeSource = 'dark'
      await shot('h53-a-choice-dark')
      nativeTheme.themeSource = 'light'
      await click('Live verification')
      await waitText('Look at the camera.', 30_000)
      check('the camera screen offers no file (H53)', !(await has('Choose an image file')) &&
        (await page(`return document.querySelector('.drop-zone') === null`)))
      await click('Cancel')
      await waitText('Upload an existing image')
      await click('Upload an existing image')
      await waitText('Drag an image here, or choose a file.')
      check('the file screen shows its drop zone and no camera (H53)',
        (await has('Choose an image file')) && (await page(`return document.querySelector('.camera-view video') === null`)))
      await shot('h53-b-file-screen')
      await page(`
        const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480
        const context = canvas.getContext('2d'); context.fillStyle = '#808080'; context.fillRect(0, 0, 640, 480)
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
        const transfer = new DataTransfer(); transfer.items.add(new File([blob], 'grey.png', { type: 'image/png' }))
        window.__transfer = transfer
        window.dispatchEvent(new DragEvent('dragenter', { dataTransfer: transfer, bubbles: true, cancelable: true }))`)
      await pause(300)
      const target = await has('Drop the image to use it')
      await shot('h53-c-dragging')
      await page(`window.dispatchEvent(new DragEvent('drop', { dataTransfer: window.__transfer, bubbles: true, cancelable: true }))`)
      await waitText('The image did not pass its checks', 20_000)
      const refused = await page(`return document.querySelector('.rejected').innerText`)
      check('a dropped image without a face ends on an outcome screen with its checks and "Verify again" (H51, H53)',
        target && refused.includes('A JPEG or PNG image: PNG') && refused.includes('640 × 480 pixels') &&
        refused.includes('One face: 0 found') && (await has('Verify again')), refused)
      await shot('h53-d-refused')
      await click('Verify again')
      await waitText('Live verification')
      check('"Verify again" returns to the choice (H53)', await has('Upload an existing image'))
      await click('Back')
      await waitText('Enrol my face again')
      await click('Identify (1:N)')
      await waitText('Live identification')
      check('identification opens on the same choice (H53)', await has('Upload an existing image'))
      await click('Back')
      await waitText('Enrol my face again')
      await click('Enrol my face again')
      await waitText('Look at the camera.', 30_000)
      check('enrolment offers no file (H27, H53)', !(await has('Upload an existing image')) && !(await has('Choose an image file')))
      await click('Cancel')
      await waitText('Enrol my face again')
      // The seeded enrolment is deleted, so the Hebrew steps start from a face that is not enrolled.
      await click('Delete the face enrolment')
      await click('Delete')
      await waitText('The face enrolment was deleted')
      // Hebrew, right to left, through the account's language and a reload (the address keeps the screen).
      await page(`await window.mbs.call('changeLanguage', { language: 'he' })`)
      let reloaded = loaded()
      win.webContents.reload()
      await reloaded
      await page(HELPERS)
      await waitText('רישום הפנים שלי', 20_000)
      check('the face screen in Hebrew is right to left (H31, H48)', (await direction()) === 'rtl' && (await has('מקבל מעל 0.363')))
      check('the Hebrew face screen offers identification (H50)', await has('זיהוי (1:N)'))
      await shot('h48-c-face-hebrew-light')
      await click('רישום הפנים שלי')
      await waitText('מסתכלים למצלמה.', 30_000)
      check('the Hebrew live view guides in Hebrew', await has('רישום הפנים'))
      nativeTheme.themeSource = 'dark'
      await shot('h48-d-face-camera-hebrew-dark')
      nativeTheme.themeSource = 'light'
      await click('ביטול')
      await waitText('רישום הפנים שלי')
      await page(`await window.mbs.call('changeLanguage', { language: 'en' })`)
      reloaded = loaded()
      win.webContents.reload()
      await reloaded
      await page(HELPERS)
      await waitText('Enrol my face', 20_000)
      await click('Home')
      await waitText('Not enrolled yet')
    }

    // 3d. The voice (H54), when the throwaway server has the real voice engine (MBS_CHECK_VOICE). The microphone is
    // Chromium's synthetic one, playing a synthetic recording in a loop (MBS_CHECK_VOICE_WAV: tones in bursts, never
    // a person's voice), so its recordings pass the checks and match each other: the check enrols that synthetic
    // voice through the real engine, looks at the result, and deletes the enrolment again.
    if (server.voice) {
      const openCard = (name: string) => page(`[...document.querySelectorAll('.card')].find((c) => c.querySelector('h2')?.textContent === ${JSON.stringify(name)}).querySelector('a').click()`)
      await waitText('Not enrolled yet')
      await openCard('Voice')
      await waitText('The voice is recognised by ECAPA-TDNN')
      await waitText('Accepts above 0.25')
      check('the voice screen shows ECAPA-TDNN, its threshold and the enrolment state (H54)',
        (await has('Accepts above 0.25')) && (await has('Not enrolled yet.')) && (await has('0.80%')))
      await shot('h54-a-voice-light')
      nativeTheme.themeSource = 'dark'
      await shot('h54-a-voice-dark')
      nativeTheme.themeSource = 'light'
      await click('Enrol my voice')
      await waitText('Enrolling your voice')
      await waitText('Each recording lasts 5 seconds', 30_000)
      const meter = await until(() => page(`
        const meter = document.querySelector('.level')
        const now = Number(meter?.getAttribute('aria-valuenow'))
        return now > -60 ? { now, lit: meter.querySelectorAll('i.on').length } : null`), 'the level meter', 15_000)
      check('the level meter follows the microphone (H54)', meter.lit > 0, meter)
      const inputs: string[] = await page(`return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput').map((d) => d.label)`)
      check('the page sees the microphones, and the permission is audio only for the voice (H54)', inputs.length > 0 && inputs.every((label) => label !== ''), inputs)
      const sentences: string[] = []
      for (let n = 1; n <= 3; n += 1) {
        sentences.push(await page(`return document.querySelector('.sentence q').textContent`))
        await click('Record')
        await waitText('Recording…', 5_000)
        if (n === 1) {
          await pause(1500)
          await shot('h54-b-voice-recording-light')
          nativeTheme.themeSource = 'dark'
          await shot('h54-b-voice-recording-dark')
          nativeTheme.themeSource = 'light'
        }
        if (n < 3) await waitText(`Recording ${n} was kept.`, 30_000)
      }
      check('each recording shows another sentence (H54)', new Set(sentences).size === 3, sentences)
      await waitText('Your voice is enrolled', 60_000)
      const result = await page(`return {
        waveforms: document.querySelectorAll('.voice-result svg.waveform').length,
        play: [...document.querySelectorAll('.voice-result button')].filter((b) => b.textContent.trim() === 'Play' && !b.disabled).length,
        pairs: [...document.querySelectorAll('.voice-result .checks li')].map((li) => li.innerText.replace(/\\s+/g, ' ')),
        stored: document.body.innerText.includes('Stored: 3 recordings, each sealed with AES-256-GCM, and 3 embeddings of 192 numbers each') }`)
      check('three synthetic recordings enrol the voice through the real engine, with their waveforms and pairs (H54)',
        result.waveforms === 3 && result.play === 3 && result.stored && result.pairs.filter((line: string) => line.includes('above the threshold')).length === 3, result)
      await shot('h54-c-voice-saved-light')
      nativeTheme.themeSource = 'dark'
      await shot('h54-c-voice-saved-dark')
      nativeTheme.themeSource = 'light'
      await click('Done')
      await waitText('Enrolled on', 10_000)
      check('the voice page shows the new enrolment (H54)', (await has('Enrol my voice again')) && (await has('Delete the voice enrolment')))
      // H55: verification of the same synthetic microphone through the real engine, then "Verify again" to the choice.
      await click('Verify my voice (1:1)')
      await waitText('Live verification')
      check('voice verification opens on the choice, before any microphone (H55)', await page(`return document.querySelector('.level') === null`))
      await click('Live verification')
      await waitText('Each recording lasts 5 seconds', 30_000)
      check('the verification reads the last sentence (H55)', await has('The numbers seven, four and nine are written on the board.'))
      // The status line under the microphone is empty until the comparison starts, and then takes no room at all.
      const emptyPrompt = (screen: string) => page(`const p = document.querySelector('.${screen} .prompt')
        return { text: p.textContent, height: p.getBoundingClientRect().height, background: getComputedStyle(p).backgroundColor }`)
      const verifyPrompt = await emptyPrompt('voice-verification')
      check('the empty status line of live verification takes no room (H55)', verifyPrompt.text === '' && verifyPrompt.height === 0, verifyPrompt)
      await shot('h55-b-voice-live-light')
      await click('Record')
      await until(async () => (await has('Your voice matches')) || (await has('Your voice does not match')), 'the verification', 60_000)
      const verified = await page(`return {
        heading: document.querySelector('h1').textContent,
        waveforms: document.querySelectorAll('.voice-verification-result svg.waveform').length,
        comparisons: [...document.querySelectorAll('.voice-verification-result .checks li')].map((li) => li.innerText.replace(/\\s+/g, ' ')),
        score: document.querySelector('.voice-verification-result .score-explain').textContent }`)
      check('the synthetic voice is verified through the real engine, beside its closest enrolled recording (H55)',
        verified.heading === 'Your voice matches' && verified.waveforms === 2 && verified.comparisons.length === 3, verified)
      await shot('h55-a-voice-verified-light')
      nativeTheme.themeSource = 'dark'
      await shot('h55-a-voice-verified-dark')
      nativeTheme.themeSource = 'light'
      await click('Verify again')
      await waitText('Live verification')
      check('Verify again returns to the choice (H55)', await page(`return document.querySelector('.level') === null`))
      await click('Back')
      await waitText('Enrol my voice again')
      // H56: identification of the same synthetic microphone through the real engine: found, its own enrolment first and
      // its closest recording beside the new one; then "Identify again" to the choice.
      await click('Identify (1:N)')
      await waitText('Live identification')
      check('voice identification opens on the choice, before any microphone (H56)',
        (await page(`return document.querySelector('.level') === null`)) && (await has('Other users appear anonymously, without a recording or a name')))
      await shot('h56-a-voice-choice-light')
      await click('Live identification')
      await waitText('Each recording lasts 5 seconds', 30_000)
      check('the identification reads the last sentence (H56)', await has('The numbers seven, four and nine are written on the board.'))
      const identifyPrompt = await emptyPrompt('voice-identification')
      check('the empty status line of live identification takes no room (H56)', identifyPrompt.text === '' && identifyPrompt.height === 0, identifyPrompt)
      await shot('h56-b-voice-live-light')
      await click('Record')
      await until(async () => (await has('A matching voice was found')) || (await has('No matching voice was found')), 'the identification', 60_000)
      const identified = await page(`return {
        heading: document.querySelector('h1').textContent,
        rows: [...document.querySelectorAll('.voice-identification tbody tr')].map((tr) => tr.innerText.replace(/\\s+/g, ' ')),
        waveforms: document.querySelectorAll('.voice-identification svg.waveform').length,
        play: [...document.querySelectorAll('.voice-identification button')].filter((b) => b.textContent.trim() === 'Play' && !b.disabled).length,
        gallery: document.body.innerText.includes('One voice enrolment, 3 recordings, in this search.'),
        beside: document.body.innerText.includes('Your enrolled recording, rank 1 in the list, beside the new one.'),
        score: document.querySelector('.voice-identification .score-explain').textContent }`)
      check('the synthetic voice is identified through the real engine, its own enrolment first and beside the new recording (H56)',
        identified.heading === 'A matching voice was found' && identified.rows.length === 1 && identified.rows[0].startsWith('1 Your voice')
          && identified.waveforms === 2 && identified.play === 2 && identified.gallery && identified.beside, identified)
      await shot('h56-c-voice-identified-light')
      nativeTheme.themeSource = 'dark'
      await shot('h56-c-voice-identified-dark')
      nativeTheme.themeSource = 'light'
      await click('Identify again')
      await waitText('Live identification')
      check('Identify again returns to the choice (H56)', await page(`return document.querySelector('.level') === null`))
      await click('Back')
      await waitText('Enrol my voice again')
      // H57: recording files, the synthetic voice as an MP3 of 44.1 kHz and two channels (made from the synthetic WAV)
      // and an 8 kHz copy that its header refuses; never a person's voice. A file is dropped on the window.
      const dropFile = async (file: string, name: string, type: string) => {
        const encoded = fs.readFileSync(file).toString('base64')
        await page(`const bytes = Uint8Array.from(atob(${JSON.stringify(encoded)}), (c) => c.charCodeAt(0))
          const transfer = new DataTransfer(); transfer.items.add(new File([bytes], ${JSON.stringify(name)}, { type: ${JSON.stringify(type)} }))
          window.dispatchEvent(new DragEvent('dragenter', { dataTransfer: transfer, bubbles: true, cancelable: true }))
          window.dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, bubbles: true, cancelable: true }))`)
      }
      const voiceWav = process.env.MBS_CHECK_VOICE_WAV
      if (!voiceWav) throw new Error('the voice steps need MBS_CHECK_VOICE_WAV')
      const mp3 = path.join(path.dirname(voiceWav), 'voice-synthetic.mp3')
      const narrow = path.join(path.dirname(voiceWav), 'voice-synthetic-8k.wav')
      await click('Verify my voice (1:1)')
      await waitText('Upload an existing recording')
      await click('Upload an existing recording')
      await waitText('Drag a recording here, or choose a file.')
      check('the file screen opens no microphone (H57)', await page(`return document.querySelector('.level') === null`))
      await shot('h57-a-voice-file-light')
      await dropFile(mp3, 'synthetic.mp3', 'audio/mpeg')
      await until(async () => (await has('Your voice matches')) || (await has('Your voice does not match')) || (await has('did not pass its checks')),
        'the verification of a file', 60_000)
      const fileVerified = await page(`return { heading: document.querySelector('h1').textContent,
        waveforms: document.querySelectorAll('.voice-verification-result svg.waveform').length,
        play: [...document.querySelectorAll('.voice-verification-result button')].filter((b) => b.textContent.trim() === 'Play' && !b.disabled).length,
        source: [...document.querySelectorAll('p.aside')].map((p) => p.textContent).find((text) => text.startsWith('Source:')),
        score: document.querySelector('.voice-verification-result .score-explain')?.textContent }`)
      check('the synthetic voice from an MP3 file is verified through the real engine, with its source (H57)',
        fileVerified.heading === 'Your voice matches' && fileVerified.waveforms === 2 && fileVerified.play === 2
          && fileVerified.source === 'Source: a recording file, MP3, 44.1 kHz, 2 channels, 10.0 seconds; compared at 16 kHz, one channel.', fileVerified)
      await shot('h57-b-voice-file-verified-light')
      nativeTheme.themeSource = 'dark'
      await shot('h57-b-voice-file-verified-dark')
      nativeTheme.themeSource = 'light'
      await click('Verify again')
      await waitText('Upload an existing recording')
      await click('Back')
      await waitText('Enrol my voice again')
      await click('Identify (1:N)')
      await waitText('Upload an existing recording')
      await click('Upload an existing recording')
      await waitText('Drag a recording here, or choose a file.')
      await dropFile(narrow, 'phone.wav', 'audio/wav')
      await waitText('The recording did not pass its checks', 30_000)
      check('an 8 kHz file is refused by its header, with its checks (H57)', await has('Sample rate: 8 kHz; 16 to 192 kHz needed'))
      await shot('h57-c-voice-file-refused-light')
      await click('Identify again')
      await waitText('Upload an existing recording')
      await click('Upload an existing recording')
      await waitText('Drag a recording here, or choose a file.')
      await dropFile(mp3, 'synthetic.mp3', 'audio/mpeg')
      await until(async () => (await has('A matching voice was found')) || (await has('No matching voice was found')) || (await has('did not pass its checks')),
        'the identification of a file', 60_000)
      const fileIdentified = await page(`return { heading: document.querySelector('h1').textContent,
        rows: [...document.querySelectorAll('.voice-identification tbody tr')].map((tr) => tr.innerText.replace(/\\s+/g, ' ')),
        waveforms: document.querySelectorAll('.voice-identification svg.waveform').length,
        file: document.body.innerText.includes('Source: a recording file, MP3, 44.1 kHz') }`)
      check('the synthetic voice from an MP3 file is identified through the real engine, its own enrolment first (H57)',
        fileIdentified.heading === 'A matching voice was found' && (fileIdentified.rows[0] ?? '').startsWith('1 Your voice')
          && fileIdentified.waveforms === 2 && fileIdentified.file, fileIdentified)
      await shot('h57-d-voice-file-identified-light')
      await click('Back')
      await waitText('Enrol my voice again')
      // The Hebrew screens, with the Hebrew sentence.
      await page(`await window.mbs.call('changeLanguage', { language: 'he' })`)
      let reloaded = loaded()
      win.webContents.reload()
      await reloaded
      await page(HELPERS)
      await waitText('רישום הקול מחדש', 20_000)
      check('the voice screen in Hebrew is right to left (H31, H54)', (await direction()) === 'rtl' && (await has('מקבל מעל 0.25')))
      check('the Hebrew voice screen offers identification (H56)', await has('זיהוי (1:N)'))
      await click('רישום הקול מחדש')
      await waitText('מקריאים בקול:', 30_000)
      check('the Hebrew enrolment shows the first Hebrew sentence', await has('השמש זורחת מעל הגבעות, והרוח נושבת מן הים.'))
      await shot('h54-d-voice-hebrew-light')
      nativeTheme.themeSource = 'dark'
      await shot('h54-d-voice-hebrew-dark')
      nativeTheme.themeSource = 'light'
      await click('ביטול')
      await waitText('רישום הקול מחדש')
      await page(`await window.mbs.call('changeLanguage', { language: 'en' })`)
      reloaded = loaded()
      win.webContents.reload()
      await reloaded
      await page(HELPERS)
      await waitText('Enrol my voice again', 20_000)
      // The synthetic voice is deleted, so the later steps see no enrolment.
      await click('Delete the voice enrolment')
      await click('Delete')
      await waitText('The voice enrolment was deleted', 10_000)
      check('the synthetic voice enrolment is deleted again (H54)', await has('Not enrolled yet.'))
      await click('Home')
      await waitText('Not enrolled yet')
    }

    // 4. The account's theme, the opposite of Windows' setting here, kept across a reload; its language.
    const other = nativeTheme.shouldUseDarkColors ? 'light' : 'dark'
    await click('Settings')
    await waitText('Appearance')
    await page(`window.__t.choose(${JSON.stringify(other === 'dark' ? 'Dark' : 'Light')})`)
    await until(() => nativeTheme.themeSource === other, `the ${other} theme`)
    const dark = await page(`return matchMedia('(prefers-color-scheme: dark)').matches`)
    check(`choosing ${other} turns the window ${other}`, dark === (other === 'dark'))
    await shot(`04-settings-${other}`)
    const reloaded = loaded()
    win.webContents.reload()
    await reloaded
    await page(HELPERS)
    await waitText('Appearance')
    check('a reload keeps the session and the screen', true)
    check('the account keeps its theme after the reload', nativeTheme.themeSource === other, nativeTheme.themeSource)
    await page(`window.__t.choose('עברית')`)
    await waitText('אבטחה')
    await until(() => win.getTitle() === 'מערכת הזיהוי', 'the Hebrew title').catch(() => {})
    check('Hebrew in the settings turns every screen right to left (H31)', (await direction()) === 'rtl' &&
      win.getTitle() === 'מערכת הזיהוי', win.getTitle())
    await shot(`04b-settings-hebrew-${other}`)
    await page(`window.__t.choose('English')`)
    await waitText('Security')
    // The password is changed in the settings' security area, which has no screen or link of its own (H28).
    check('the password lives in the settings, with no link of its own', !(await has('Change password')))
    await fill('Current password', 'Dana password 1')
    await fill('New password', 'Dana new password 2')
    await fill('New password again', 'Dana new password 2')
    await click('Change the password')
    await waitText('The password was changed')
    check('the settings replace the password, and the session goes on', serverClient.signedIn)
    await shot(`04c-settings-password-${other}`)
    await click('Home')
    await waitText('Hello, dana')
    await shot(`05-home-${other}`)

    // 5. Sign-out returns to sign-in, in Windows' setting again.
    await click('Sign out')
    await waitText(signInPage)
    await until(() => nativeTheme.themeSource === 'system', "Windows' setting")
    check("sign-out returns to sign-in and to Windows' setting", !serverClient.signedIn)

    // 6. Password recovery by email (H32): the outbox's link opens the new-password screen.
    await click('Forgot your password?')
    await waitText('Reset your password')
    await page(`window.__t.choose('By email')`)
    await fill('Email', 'dana@example.com')
    await click('Send the link')
    await waitText('If this address belongs to an account')
    await shot('06-forgot-password')
    const sent = await until(() => {
      const files = fs.existsSync(server.outbox) ? fs.readdirSync(server.outbox).filter((f) => f.endsWith('.html')) : []
      return files[0] ? fs.readFileSync(path.join(server.outbox, files[0]), 'utf8') : null
    }, 'the message in the outbox')
    const [, resetToken, lang] = sent.match(/href="mbs:\/\/reset-password\?token=([\w-]+)&amp;lang=(\w+)"/) ?? []
    check('the outbox holds the email with its link', Boolean(resetToken) && lang === 'en' && sent.includes('dana@example.com'))
    if (!resetToken || lang !== 'en') throw new Error('the outbox has no link to open')
    serverClient.openLink({ token: resetToken, language: lang })
    win.webContents.send('mbs:link')
    await waitText('Choose a new password for your account.')
    const hidden = await page(`return document.documentElement.outerHTML.includes(${JSON.stringify(resetToken)})`)
    check("the link's token stays in the main process", !hidden)
    await fill('New password', 'Dana reset password 3')
    await fill('New password again', 'Dana reset password 3')
    await shot('07-reset-password')
    await click('Save the new password')
    await waitText('Your password was changed')
    check('the link sets the new password', true)
    await click('Sign in')
    await waitText(signInPage)

    // 7. Hebrew chosen at sign-in: right to left, the eye on the left, and saved in the account (H31).
    await click('עברית')
    await waitText('כניסה עם שם משתמש או אימייל.')
    const eyeSide = await page(`const input = window.__t.field('סיסמה').getBoundingClientRect()
      const button = window.__t.named('הצגת הסיסמה').getBoundingClientRect()
      return button.left - input.left < input.right - button.right ? 'left' : 'right'`)
    check('Hebrew turns the sign-in right to left, with the eye at the end of the line', (await direction()) === 'rtl' && eyeSide === 'left', eyeSide)
    await fill('שם משתמש או אימייל', 'dana')
    await fill('סיסמה', 'Dana reset password 3')
    await shot('08-sign-in-hebrew')
    await click('כניסה')
    await waitText('שלום, dana')
    check('the account signs in with the new password, in Hebrew', true)
    await shot('09-home-hebrew')
    await click('יציאה')
    await waitText('כניסה עם שם משתמש או אימייל.')
    check('after sign-out the screens stay in the last language', (await direction()) === 'rtl')
    await click('English')
    await waitText(signInPage)

    // 8. The first administrator signs in with the one-time password and must replace it first.
    await fill('Username or email', server.administrator)
    await fill('Password', server.one_time_password)
    await click('Sign in')
    await waitText('choose your own')
    check('a one-time password leads to its replacement, with no navigation', !(await page(`return Boolean(document.querySelector('nav'))`)))
    await page(`location.hash = '#/admin'`)
    await pause(600)
    check('the administration area stays closed until then', (await has('choose your own')) && !(await has('Audit log')))
    await shot('10-one-time-password')
    await fill('One-time password', server.one_time_password)
    await fill('New password', 'Admin password 1')
    await fill('New password again', 'Admin password 1')
    await click('Save')
    await waitText('Audit log')
    // The audit log has a section of its own since H61, and arrives after it, so the check waits for its first row.
    await click('Audit log')
    await until(() => has('First administrator created'), 'the audit log')
    check('after the replacement the administrator lands in the administration area', true)
    await click('Accounts')
    await until(() => page(`return Boolean(window.__t.row('dana@example.com'))`), 'the accounts')
    await shot('11-admin')

    // 9. Disabling an account asks for the administrator's password again.
    const row = "window.__t.row('dana@example.com')"
    await click('Disable…', row)
    await fill('Your password, to confirm', 'not the password', row)
    await click('Disable', row)
    await waitText('The password is wrong.')
    check('a wrong password does not disable the account', !(await page(`return ${row}.innerText.includes('Disabled')`)))
    await fill('Your password, to confirm', 'Admin password 1', row)
    await click('Disable', row)
    await until(() => page(`return ${row}.innerText.includes('Disabled')`), 'the account disabled')
    await shot('12-admin-disabled')
    await click('Audit log')
    check('the account is disabled, and the audit log records it', await until(() => has('Account disabled'), 'its audit entry'))
    await click('Accounts')
    await until(() => page(`return Boolean(document.querySelector('form.row'))`), 'the accounts')

    // 10. A new administrator gets a one-time password, shown once.
    const form = "document.querySelector('form.row')"
    await fill('Username', 'rotem', form)
    await fill('Email', 'rotem@example.com', form)
    await fill('Your password, to confirm', 'Admin password 1', form)
    await click('Create', form)
    await waitText('Administrator rotem was created')
    const shown = await page(`return document.querySelector('[role=status] code')?.textContent ?? ''`)
    check("the new administrator's one-time password is shown", shown.length > 0, shown.length)
    await shot('13-admin-new')

    // 10b. The attempt history (H61): this run's attempts if it made any, else the empty history; nothing sealed is
    // shown; a type filter narrows the list and is cleared again.
    await click('Attempt history')
    await waitText('Every comparison by every user')
    const listed = await until(() => page(`
      if (document.querySelector('.history__table')) return document.querySelectorAll('.history__table tr.attempt').length
      return document.body.innerText.includes('No attempts yet.') ? -1 : 0`), 'the history')
    check('the history lists the attempts of this run, or says there are none', listed !== 0, listed)
    check('the history shows no image, recording or print', await page(`return !document.querySelector('.history img, .history canvas, .history audio')`))
    await shot('13h-history')
    await click('Type')
    await page(`[...document.querySelectorAll('[role=option]')].find((o) => o.textContent === 'Fingerprint').click()`)
    await until(() => page(`return Boolean(window.__t.button('Type: Fingerprint'))`), 'the type filter')
    // The rows of the filters before stay, marked busy, until the new answer comes.
    await until(() => page(`return document.querySelector('.history__list')?.getAttribute('aria-busy') === 'false'`), 'the filtered history')
    check('the type filter leaves only fingerprint comparisons', await page(`
      return [...document.querySelectorAll('.history__table tr.attempt td:nth-child(3)')].every((cell) => cell.textContent.startsWith('Fingerprint'))`))
    await shot('13i-history-fingerprint')
    await click('Clear filters')
    await until(() => page(`return !window.__t.button('Type: Fingerprint')`), 'the filters cleared')

    // 11. The administration area in both themes, then sign-out.
    for (const [theme, label] of [['light', 'Light'], ['dark', 'Dark']] as const) {
      await click('Settings')
      await waitText('Appearance')
      await page(`window.__t.choose(${JSON.stringify(label)})`)
      await until(() => nativeTheme.themeSource === theme, `the ${theme} theme`)
      await click('Administration')
      await waitText('Audit log')
      await shot(`14-admin-${theme}`)
    }
    await click('Sign out')
    await waitText(signInPage)

    // 12. The disabled account cannot sign in.
    await fill('Username or email', 'dana')
    await fill('Password', 'Dana reset password 3')
    await click('Sign in')
    await waitText('This account is disabled')
    check('the disabled account cannot sign in', !serverClient.signedIn)
    await shot('15-sign-in-disabled')

    // 13. Sign-in when Windows is set to light, and to dark.
    for (const theme of ['light', 'dark'] as const) {
      nativeTheme.themeSource = theme
      await shot(`16-sign-in-${theme}`)
    }
    nativeTheme.themeSource = 'system'
  } catch (e) {
    await shot('failure').catch(() => {})
    check('the flow ran to its end', false, String((e instanceof Error && e.message) || e))
  }

  console.log('console', JSON.stringify(messages, null, 1))
  const failed = results.filter((r) => !r.passed).length
  console.log(`${results.length - failed} of ${results.length} checks passed`)
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ page: pageUrl ?? 'built', results, messages }, null, 2))
  if (process.env.MBS_CHECK_SHOTS) {
    fs.writeFileSync(path.join(out, 'layout.json'), JSON.stringify(layout, null, 1))
    console.log(`layout: ${layout.filter((entry) => entry.problems.length > 0).length} of ${layout.length} screenshots with findings`)
  }
  process.exit(failed ? 1 : 0)
})
