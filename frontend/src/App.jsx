import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import UploadPage from './pages/UploadPage'
import AnalysisPage from './pages/AnalysisPage'
import DubbingPage from './pages/DubbingPage'
import ResultsPage from './pages/ResultsPage'

const stepPathMap = ['/', '/analysis', '/dubbing', '/results']
const ACTIVE_JOB_STORAGE_KEY = 'voxbridge.activeJobId'

function getStoredJobId() {
    if (typeof window === 'undefined') {
        return null
    }

    try {
        return window.sessionStorage.getItem(ACTIVE_JOB_STORAGE_KEY)
    } catch {
        return null
    }
}

function storeJobId(jobId) {
    if (typeof window === 'undefined') {
        return
    }

    try {
        if (jobId) {
            window.sessionStorage.setItem(ACTIVE_JOB_STORAGE_KEY, jobId)
        } else {
            window.sessionStorage.removeItem(ACTIVE_JOB_STORAGE_KEY)
        }
    } catch {
        // Session storage can be unavailable in privacy-restricted browsers.
    }
}

function AppShell() {
    const location = useLocation()
    const normalizedPath = location.pathname === '/' ? '/' : location.pathname.replace(/\/+$/, '')
    const activeStepIndex = stepPathMap.includes(normalizedPath) ? stepPathMap.indexOf(normalizedPath) : 0
    const [jobId, setJobId] = useState(() => location.state?.jobId || getStoredJobId())
    const [analysisData, setAnalysisData] = useState(null)
    const [demoContext, setDemoContext] = useState(null)

    // Dubbing navigates to Results with the job ID in router state. Reconcile
    // that ID into app state so Results receives it immediately, and restore it
    // after a browser refresh from the current session.
    useEffect(() => {
        const routedJobId = location.state?.jobId
        if (typeof routedJobId !== 'string' || !routedJobId) {
            return
        }

        setJobId(routedJobId)
        storeJobId(routedJobId)
    }, [location.state])

    const handleUploadComplete = (id) => {
        if (typeof id !== 'string' || !id) {
            return
        }

        setJobId(id)
        storeJobId(id)
        setAnalysisData(null)
        if (!id.startsWith('demo-')) {
            setDemoContext(null)
        }
    }

    const handleDemoMode = (mode, data) => {
        setDemoContext({ type: mode, data })
        setAnalysisData(null)
    }

    const activeJobId = location.state?.jobId || jobId

    return (
        <div className="page">
            <header className="header">
                <div className="container header-content">
                    <div>
                        <NavLink to="/" className="logo">
                            <span className="logo-text">VoxBridge</span>
                            <span className="logo-subtitle">Responsible AI</span>
                        </NavLink>
                    </div>
                    <nav className="nav">
                        <NavLink
                            to="/"
                            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                        >
                            Upload
                        </NavLink>
                        <NavLink
                            to="/analysis"
                            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                        >
                            Analysis
                        </NavLink>
                        <NavLink
                            to="/dubbing"
                            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                        >
                            Dubbing
                        </NavLink>
                        <NavLink
                            to="/results"
                            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                        >
                            Results
                        </NavLink>
                    </nav>
                </div>
            </header>

            <main className="main-content">
                <div className="container">
                    <div className="steps">
                        <div className={`step ${activeStepIndex === 0 ? 'active' : activeStepIndex > 0 ? 'completed' : ''}`}>
                            <div className="step-number">1</div>
                            <div className="step-label">Upload</div>
                        </div>
                        <div className={`step ${activeStepIndex === 1 ? 'active' : activeStepIndex > 1 ? 'completed' : ''}`}>
                            <div className="step-number">2</div>
                            <div className="step-label">Analysis</div>
                        </div>
                        <div className={`step ${activeStepIndex === 2 ? 'active' : activeStepIndex > 2 ? 'completed' : ''}`}>
                            <div className="step-number">3</div>
                            <div className="step-label">Dubbing</div>
                        </div>
                        <div className={`step ${activeStepIndex === 3 ? 'active' : ''}`}>
                            <div className="step-number">4</div>
                            <div className="step-label">Results</div>
                        </div>
                    </div>

                    <ErrorBoundary>
                        <Routes>
                            <Route
                                path="/"
                                element={
                                    <UploadPage
                                        onUploadComplete={handleUploadComplete}
                                        onDemoMode={handleDemoMode}
                                    />
                                }
                            />
                            <Route
                                path="/analysis"
                                element={
                                    <AnalysisPage
                                        jobId={activeJobId}
                                        demoContext={demoContext}
                                        onAnalysisComplete={(data) => setAnalysisData(data)}
                                    />
                                }
                            />
                            <Route
                                path="/dubbing"
                                element={
                                    <DubbingPage
                                        jobId={activeJobId}
                                        analysisData={analysisData}
                                    />
                                }
                            />
                            <Route
                                path="/results"
                                element={<ResultsPage jobId={activeJobId} demoContext={demoContext} />}
                            />
                        </Routes>
                    </ErrorBoundary>
                </div>
            </main>

            <footer
                style={{
                    padding: 'var(--spacing-4) 0',
                    textAlign: 'center',
                    color: 'var(--color-neutral-500)',
                    fontSize: 'var(--font-size-sm)',
                    borderTop: '1px solid var(--color-neutral-200)'
                }}
            >
                VoxBridge - Responsible AI Video Dubbing Platform
            </footer>
        </div>
    )
}

export default function App() {
    return (
        <BrowserRouter>
            <AppShell />
        </BrowserRouter>
    )
}
