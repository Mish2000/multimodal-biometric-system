// A screen that fails while it renders shows a short message in the screen's language instead of an empty window.
// The boundary stands around the screens inside the frame, so its bar stays, and around every screen, so the screens
// before sign-in are covered too. Any move to a screen, even the same one, shows it again; React still reports the
// error itself to the console.
import { Component, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { landing, useSession } from './session'

interface Props {
  resetKey: string // the location's key, new with every move between screens
  children: ReactNode
}

interface State {
  failed: boolean
  key: string
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, key: this.props.resetKey }

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey === state.key ? null : { failed: false, key: props.resetKey }
  }

  private readonly retry = (): void => this.setState({ failed: false })

  render(): ReactNode {
    return this.state.failed ? <ScreenFailed retry={this.retry} /> : this.props.children
  }
}

function ScreenFailed({ retry }: { retry: () => void }) {
  const { account, t } = useSession()
  const navigate = useNavigate()
  return (
    <section className="narrow" role="alert">
      <h1>{t.screenFailed.title}</h1>
      <p>{t.screenFailed.text}</p>
      <button
        type="button"
        onClick={() => {
          navigate(landing(account))
          retry()
        }}
      >
        {t.screenFailed.back}
      </button>
    </section>
  )
}
