import { Component } from 'react'

/**
 * Error boundary component to catch React rendering errors.
 * Prevents the entire app from crashing on component errors.
 */
class ErrorBoundary extends Component {
    constructor(props) {
        super(props)
        this.state = { hasError: false, error: null }
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error }
    }

    componentDidCatch(error, errorInfo) {
        console.error('React Error Boundary caught an error:', error, errorInfo)
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="error-boundary">
                    <div className="error-boundary-content">
                        <h2>Something went wrong</h2>
                        <p>The application encountered an unexpected error.</p>
                        <button
                            className="btn btn-primary"
                            onClick={() => {
                                this.setState({ hasError: false, error: null })
                                window.location.href = '/'
                            }}
                        >
                            Return to Home
                        </button>
                        {import.meta.env.DEV && (
                            <details style={{ marginTop: '1rem', textAlign: 'left' }}>
                                <summary>Error Details (Dev Only)</summary>
                                <pre style={{
                                    background: '#1a1a1a',
                                    padding: '1rem',
                                    borderRadius: '4px',
                                    overflow: 'auto',
                                    fontSize: '0.8rem'
                                }}>
                                    {this.state.error?.toString()}
                                </pre>
                            </details>
                        )}
                    </div>
                </div>
            )
        }

        return this.props.children
    }
}

export default ErrorBoundary
