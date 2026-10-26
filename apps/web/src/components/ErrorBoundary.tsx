import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

/** Evita a tela branca: qualquer throw de render cai no fallback com retry. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Erro não tratado na interface', error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children

    return (
      <main className="grid min-h-full place-items-center p-4 sm:p-6">
        <div className="card w-full max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">Algo deu errado</h1>
          <p role="alert" className="text-sm text-red-600">
            A página não conseguiu carregar. Tente novamente.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              className="btn-ghost flex-1"
              onClick={() => window.location.reload()}
            >
              Recarregar página
            </button>
            <button
              type="button"
              className="btn-primary flex-1"
              onClick={() => this.setState({ hasError: false })}
            >
              Tentar novamente
            </button>
          </div>
        </div>
      </main>
    )
  }
}
