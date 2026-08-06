import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

const LANGUAGES = [
    { code: 'es', name: 'Spanish' },
    { code: 'fr', name: 'French' },
    { code: 'de', name: 'German' },
    { code: 'it', name: 'Italian' },
    { code: 'pt', name: 'Portuguese' },
    { code: 'ja', name: 'Japanese' },
    { code: 'ko', name: 'Korean' },
    { code: 'zh', name: 'Chinese' },
    { code: 'ar', name: 'Arabic' },
    { code: 'hi', name: 'Hindi' },
]

const POLL_INTERVAL_MS = 2000
const MAX_POLL_ATTEMPTS = 180
const DUBBING_STEP_NAMES = {
    dubbing: 'Processing dubbing...',
    translation: 'Translating content...',
    tts_synthesis: 'Generating AI voice...',
    output_generation: 'Creating final video...',
    completed: 'Complete!',
    error: 'Error occurred',
}

function DubbingPage({ jobId, analysisData }) {
    const [targetLanguage, setTargetLanguage] = useState('es')
    const [consentChecked, setConsentChecked] = useState(false)
    const [overrideSafety, setOverrideSafety] = useState(false)
    const [processing, setProcessing] = useState(false)
    const [progress, setProgress] = useState(0)
    const [currentStep, setCurrentStep] = useState('')
    const [error, setError] = useState(null)
    const navigate = useNavigate()

    // The backend database is the source of truth. These refs keep one
    // cancellable request and one scheduled retry alive without overlapping
    // fetches or losing an in-flight job when this page is remounted.
    const pollTimeoutRef = useRef(null)
    const pollAbortControllerRef = useRef(null)
    const pollAttemptsRef = useRef(0)
    const pollingJobIdRef = useRef(null)

    const stopPolling = () => {
        if (pollTimeoutRef.current) {
            clearTimeout(pollTimeoutRef.current)
            pollTimeoutRef.current = null
        }
        if (pollAbortControllerRef.current) {
            pollAbortControllerRef.current.abort()
            pollAbortControllerRef.current = null
        }
        pollAttemptsRef.current = 0
        pollingJobIdRef.current = null
    }

    const applyBackendStatus = (statusData) => {
        const status = statusData?.status || 'unknown'
        const progressValue = Number(statusData?.progress)
        setProgress(Number.isFinite(progressValue) ? progressValue : 0)
        setCurrentStep(
            DUBBING_STEP_NAMES[status] || statusData?.current_step || status
        )
        return status
    }

    const finishWithError = (message) => {
        stopPolling()
        setProcessing(false)
        setError(message)
    }

    const finishSuccessfully = () => {
        stopPolling()
        setProgress(100)
        setCurrentStep('Complete!')
        setProcessing(false)
        navigate('/results', { state: { jobId } })
    }

    const pollJobStatus = async () => {
        if (!jobId || pollingJobIdRef.current !== jobId) {
            return
        }

        if (pollAttemptsRef.current >= MAX_POLL_ATTEMPTS) {
            finishWithError(
                'Processing timeout. The dubbing is taking longer than expected. Please check the Results page.'
            )
            return
        }

        pollAttemptsRef.current += 1
        const controller = new AbortController()
        pollAbortControllerRef.current = controller

        try {
            const statusResponse = await fetch(`/api/job-status/${jobId}`, {
                signal: controller.signal,
            })
            const statusData = await statusResponse.json().catch(() => ({}))
            if (!statusResponse.ok) {
                throw new Error(statusData.detail || `Status check failed (${statusResponse.status})`)
            }

            const status = applyBackendStatus(statusData)
            if (status === 'error') {
                finishWithError(`Dubbing failed: ${statusData.message || 'Unknown error'}`)
                return
            }
            if (status === 'completed') {
                finishSuccessfully()
                return
            }

            if (pollingJobIdRef.current === jobId) {
                pollTimeoutRef.current = setTimeout(pollJobStatus, POLL_INTERVAL_MS)
            }
        } catch (pollError) {
            if (pollError.name === 'AbortError') {
                return
            }

            console.error('Polling error:', pollError)
            if (pollAttemptsRef.current >= MAX_POLL_ATTEMPTS) {
                finishWithError(
                    'Unable to read dubbing progress. Please check the Results page or try again.'
                )
                return
            }

            setCurrentStep('Reconnecting to processing job...')
            if (pollingJobIdRef.current === jobId) {
                pollTimeoutRef.current = setTimeout(pollJobStatus, POLL_INTERVAL_MS)
            }
        } finally {
            if (pollAbortControllerRef.current === controller) {
                pollAbortControllerRef.current = null
            }
        }
    }

    const startPolling = () => {
        stopPolling()
        pollingJobIdRef.current = jobId
        setProcessing(true)
        void pollJobStatus()
    }

    // Reconcile on mount so a refresh or route remount can resume an existing
    // backend job. The local React state is only a projection of this status.
    useEffect(() => {
        if (!jobId || jobId.startsWith('demo-')) {
            return undefined
        }

        let cancelled = false
        const syncJobStatus = async () => {
            try {
                const statusResponse = await fetch(`/api/job-status/${jobId}`)
                const statusData = await statusResponse.json().catch(() => ({}))
                if (!statusResponse.ok) {
                    throw new Error(statusData.detail || 'Unable to load job status')
                }
                if (cancelled) {
                    return
                }

                setError(null)
                const status = applyBackendStatus(statusData)
                if (status === 'dubbing') {
                    startPolling()
                } else if (status === 'completed') {
                    finishSuccessfully()
                } else if (status === 'error') {
                    finishWithError(`Dubbing failed: ${statusData.message || 'Unknown error'}`)
                }
            } catch (syncError) {
                if (!cancelled) {
                    setProcessing(false)
                    setError(syncError.message || 'Unable to load job status')
                }
            }
        }

        void syncJobStatus()
        return () => {
            cancelled = true
            stopPolling()
        }
    }, [jobId])

    const isHighRisk = analysisData?.risk_level === 'high'

    const handleStartDubbing = async () => {
        // Validation
        if (!consentChecked) {
            setError('You must confirm consent for AI voice synthesis');
            return;
        }

        if (isHighRisk && !overrideSafety) {
            setError('High-risk content detected. You must acknowledge the override to proceed.');
            return;
        }

        // Safety previews do not create jobs or artifacts. A real upload is
        // required before the consent-gated dubbing request can run.
        if (!jobId || jobId.startsWith('demo-')) {
            setError('This safety sample is preview-only. Upload a video to create a real dubbing job and downloadable artifacts.');
            return;
        }

        setProcessing(true);
        setError(null);
        setProgress(0);
        setCurrentStep('Starting dubbing process...');

        try {
            // The analysis page has local state, but the backend is the source
            // of truth for the safety gate. Reconcile before requesting TTS.
            const statusResponse = await fetch(`/api/job-status/${jobId}`);
            const statusData = await statusResponse.json().catch(() => ({}));
            if (!statusResponse.ok) {
                throw new Error(statusData.detail || 'Unable to verify backend job status');
            }

            if (statusData.status === 'ready_for_analysis') {
                const reanalysisResponse = await fetch('/api/analyze-content', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId })
                });
                if (!reanalysisResponse.ok) {
                    const reanalysisError = await reanalysisResponse.json().catch(() => ({}));
                    throw new Error(reanalysisError.detail || 'Backend analysis has not completed');
                }
            } else if (statusData.status !== 'analyzed') {
                throw new Error(
                    statusData.status === 'processing' || statusData.status === 'uploaded'
                        ? 'The backend is still processing this video. Wait for analysis to finish and try again.'
                        : statusData.message || `Backend job is not ready for dubbing (status: ${statusData.status})`
                );
            }

            // Start dubbing request
            const response = await fetch('/api/approve-and-dub', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    target_language: targetLanguage,
                    consent_confirmed: consentChecked,
                    override_safety: overrideSafety
                })
            });

            // Check if the request was successful
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorMsg = errorData.detail || `Request failed with status ${response.status}`;

                if (errorMsg.includes('not found')) {
                    setError('Job not found. Please upload a new video.');
                } else {
                    setError(errorMsg);
                }
                setProcessing(false);
                return;
            }

            const acceptedData = await response.json().catch(() => ({
                status: 'dubbing',
                progress: 0,
                current_step: 'translation',
            }));
            applyBackendStatus(acceptedData);
            startPolling();

        } catch (err) {
            // Real error handling - no demo fallback
            console.error('Dubbing request failed:', err);
            setError(`Failed to start dubbing: ${err.message || 'Network error'}`);
            setProcessing(false);
        }
    }


    return (
        <div className="safety-dashboard">
            {/* Risk Warning */}
            {isHighRisk && (
                <div className="alert alert-error">
                    <strong>High-Risk Content Detected</strong>
                    <p style={{ marginTop: 'var(--spacing-2)' }}>
                        The content analysis found issues that may require review before proceeding.
                        You must acknowledge the override to continue with dubbing.
                    </p>
                </div>
            )}

            {/* Configuration Card */}
            <div className="card">
                <div className="card-header">
                    <h2 className="card-title">Configure Dubbing</h2>
                    <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                        Select target language and confirm consent for AI voice generation
                    </p>
                </div>

                {(!jobId || jobId.startsWith('demo-')) && (
                    <div className="alert alert-info" role="status">
                        This is a safety preview. Upload a video from the Upload page to enable real dubbing.
                    </div>
                )}

                {error && (
                    <div className="alert alert-error">
                        {error}
                    </div>
                )}

                <div className="form-group">
                    <label className="form-label">Target Language</label>
                    <select
                        className="form-select"
                        value={targetLanguage}
                        onChange={(e) => setTargetLanguage(e.target.value)}
                        disabled={processing}
                    >
                        {LANGUAGES.map(lang => (
                            <option key={lang.code} value={lang.code}>
                                {lang.name}
                            </option>
                        ))}
                    </select>
                </div>

                {/* Consent Section */}
                <div className="card" style={{
                    backgroundColor: 'var(--color-neutral-100)',
                    marginTop: 'var(--spacing-4)'
                }}>
                    <h4 style={{ marginBottom: 'var(--spacing-3)' }}>Voice Synthesis Consent</h4>

                    <div className="checkbox-group" style={{ marginBottom: 'var(--spacing-3)' }}>
                        <input
                            type="checkbox"
                            id="consent"
                            className="checkbox-input"
                            checked={consentChecked}
                            onChange={(e) => setConsentChecked(e.target.checked)}
                            disabled={processing}
                        />
                        <label htmlFor="consent" className="checkbox-label">
                            <strong>I confirm consent for AI voice synthesis</strong>
                            <br />
                            I understand that AI-generated audio will be created and clearly labeled.
                            I have the right to use this content for the stated purpose.
                        </label>
                    </div>

                    {isHighRisk && (
                        <div className="checkbox-group" style={{
                            padding: 'var(--spacing-3)',
                            backgroundColor: 'var(--color-danger-bg)',
                            borderRadius: 'var(--radius-md)'
                        }}>
                            <input
                                type="checkbox"
                                id="override"
                                className="checkbox-input"
                                checked={overrideSafety}
                                onChange={(e) => setOverrideSafety(e.target.checked)}
                                disabled={processing}
                            />
                            <label htmlFor="override" className="checkbox-label">
                                <strong>I acknowledge the safety flags and choose to proceed</strong>
                                <br />
                                I understand this content has been flagged for potential issues.
                                I take responsibility for publishing this content.
                            </label>
                        </div>
                    )}
                </div>

                {/* Progress */}
                {processing && (
                    <div style={{ marginTop: 'var(--spacing-6)' }}>
                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            marginBottom: 'var(--spacing-2)'
                        }}>
                            <span>{currentStep}</span>
                            <span>{progress}%</span>
                        </div>
                        <div className="progress-bar">
                            <div className="progress-fill" style={{ width: `${progress}%` }} />
                        </div>
                    </div>
                )}

                {/* Actions */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'center',
                    gap: 'var(--spacing-4)',
                    marginTop: 'var(--spacing-6)'
                }}>
                    <button
                        className="btn btn-secondary"
                        onClick={() => navigate('/analysis')}
                        disabled={processing}
                    >
                        Back to Analysis
                    </button>
                    <button
                        className="btn btn-primary btn-lg"
                        onClick={handleStartDubbing}
                        disabled={processing || !jobId || jobId.startsWith('demo-') || !consentChecked || (isHighRisk && !overrideSafety)}
                    >
                        {processing ? 'Processing...' : 'Start Dubbing'}
                    </button>
                </div>
            </div>

            {/* Ethical Notice */}
            <div className="alert alert-info">
                <strong>Ethical Voice Usage:</strong> AI-generated audio is labeled in the audit metadata and
                logged for accountability. Voice synthesis is only performed with explicit user consent.
                This helps prevent misuse of voice cloning technology.
            </div>
        </div>
    )
}

export default DubbingPage
