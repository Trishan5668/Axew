import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[AXEW] Renderer error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            display: 'flex',
            height: '100vh',
            width: '100vw',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#0A0A0C',
            color: '#E8E8F0',
            fontFamily: 'Inter, system-ui, sans-serif',
            padding: 24,
            boxSizing: 'border-box',
          }}
        >
          <h1 style={{ fontSize: 18, marginBottom: 8 }}>AXEW failed to start</h1>
          <p style={{ fontSize: 12, color: '#6B6B7E', marginBottom: 16, textAlign: 'center' }}>
            The renderer encountered an error. Check DevTools console for details.
          </p>
          <pre
            style={{
              maxWidth: '90%',
              overflow: 'auto',
              padding: 12,
              background: '#16161B',
              border: '1px solid #22222A',
              borderRadius: 6,
              fontSize: 11,
              color: '#EF4444',
            }}
          >
            {this.state.error.message}
          </pre>
        </div>
      )
    }

    return this.props.children
  }
}
