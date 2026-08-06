import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import VideoPreview from '../components/VideoPreview'

function ResultsPage({ jobId, demoContext }) {
    const [auditData, setAuditData] = useState(null)
    const [loading, setLoading] = useState(true)
    const [jobStatus, setJobStatus] = useState(null) // Track actual job status
    const [showOriginalPreview, setShowOriginalPreview] = useState(false)
    const [showDubbedPreview, setShowDubbedPreview] = useState(false)
    const navigate = useNavigate()
    const location = useLocation()
    const isDemoResult = Boolean(location.state?.isDemo) || (jobId && jobId.startsWith('demo-'))

    useEffect(() => {
        if (isDemoResult) {
            setAuditData(null)
            setJobStatus('demo_preview')
            setLoading(false)
            return
        }

        if (jobId && !jobId.startsWith('demo-')) {
            loadAuditData()
            return
        }

        // No job available yet
        setLoading(false)
        setJobStatus('no_job')
    }, [jobId, isDemoResult])

    const loadAuditData = async () => {
        setLoading(true)

        try {
            // First check job status
            const statusRes = await fetch(`/api/job-status/${jobId}`)
            if (statusRes.ok) {
                const statusData = await statusRes.json()
                setJobStatus(statusData.status)
            }

            const response = await fetch(`/api/audit-report/${jobId}`)
            if (response.ok) {
                const data = await response.json()
                setAuditData(data)
                setLoading(false)
                return
            }
        } catch (err) {
            console.error('Failed to load audit data:', err)
        }

        // FIXED: Don't auto-fallback to demo - show error state
        setJobStatus('error')
        setLoading(false)
    }

    const isRealJob = jobId && !jobId.startsWith('demo-')

    const handleDownloadAudit = () => {
        const json = JSON.stringify(auditData, null, 2)
        const blob = new Blob([json], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `audit-report-${auditData.job_id}.json`
        a.click()
        URL.revokeObjectURL(url)
    }

    const handleDownloadVideo = async () => {
        if (!jobId || jobId.startsWith('demo-')) {
            alert('Video download is available for real dubbing jobs. This is a demo preview.')
            return
        }

        try {
            // Use window.open or direct link for better browser handling of downloads
            // But if we want to stream:
            window.location.href = `/api/download/video/${jobId}`
        } catch (err) {
            console.error('Download error:', err)
            alert('Failed to download video. Please try again.')
        }
    }

    const handleDownloadAudio = async () => {
        if (!jobId || jobId.startsWith('demo-')) {
            alert('Audio download is available for real dubbing jobs. This is a demo preview.')
            return
        }

        try {
            window.location.href = `/api/download/audio/${jobId}`
        } catch (err) {
            console.error('Download error:', err)
            alert('Failed to download audio. Please try again.')
        }
    }

    const formatStepName = (name) => {
        return name
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ')
    }

    const formatTimestamp = (timestamp) => {
        if (!timestamp) return 'Not completed'
        const date = new Date(timestamp)
        // Check for epoch time (indicates null/invalid date)
        if (date.getTime() === 0 || date.getFullYear() === 1970) {
            return 'Not completed'
        }
        return date.toLocaleString()
    }

    if (loading) {
        return (
            <div className="card">
                <div className="loading">
                    <div className="spinner" />
                    <p style={{ marginTop: 'var(--spacing-4)' }}>Loading results...</p>
                </div>
            </div>
        )
    }

    // FIXED: Show proper UI for no job or error states instead of demo data
    if (jobStatus === 'no_job' || (!auditData && !jobId)) {
        return (
            <div className="card">
                <div className="alert alert-warning">
                    <strong>No Results Available</strong>
                    <p style={{ marginTop: 'var(--spacing-2)' }}>
                        Please complete the full dubbing process to see results.
                        Upload a video, run analysis, and complete dubbing first.
                    </p>
                </div>
                <div style={{ textAlign: 'center', marginTop: 'var(--spacing-4)' }}>
                    <button className="btn btn-primary" onClick={() => navigate('/')}>
                        Start New Dubbing
                    </button>
                </div>
            </div>
        )
    }

    if (jobStatus === 'demo_preview') {
        return (
            <div className="card">
                <div className="alert alert-info" role="status">
                    <strong>Safety Preview Only</strong>
                    <p style={{ marginTop: 'var(--spacing-2)' }}>
                        This sample has no backend job, audit record, or downloadable media. Upload a video to run the complete dubbing workflow.
                    </p>
                </div>
                <div style={{ textAlign: 'center', marginTop: 'var(--spacing-4)' }}>
                    <button className="btn btn-primary" onClick={() => navigate('/')}>
                        Upload a Video
                    </button>
                </div>
            </div>
        )
    }

    if (jobStatus === 'error' && !auditData) {
        return (
            <div className="card">
                <div className="alert alert-danger">
                    <strong>Failed to Load Results</strong>
                    <p style={{ marginTop: 'var(--spacing-2)' }}>
                        The job data could not be retrieved. It may have been deleted or never completed.
                    </p>
                </div>
                <div style={{ textAlign: 'center', marginTop: 'var(--spacing-4)' }}>
                    <button className="btn btn-primary" onClick={() => navigate('/')}>
                        Start New Dubbing
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className="safety-dashboard">
            {/* Success/Status Banner */}
            {jobStatus === 'completed' ? (
                <div className="alert alert-success">
                    <strong>Dubbing Complete!</strong> Your video has been successfully dubbed
                    with all responsible AI checks passed.
                </div>
            ) : jobStatus === 'error' ? (
                <div className="alert alert-error">
                    <strong>Dubbing Failed</strong> An error occurred during processing.
                    Please try uploading again.
                </div>
            ) : jobStatus ? (
                <div className="alert alert-warning">
                    <strong>Processing in Progress</strong> Current status: {jobStatus}.
                    Please wait for dubbing to complete.
                </div>
            ) : (
                <div className="alert alert-info">
                    <strong>Demo Mode</strong> Showing sample results.
                </div>
            )}

            {/* Video Preview Section */}
            {isRealJob && (
                <div className="card">
                    <div className="card-header">
                        <h2 className="card-title">Video Preview</h2>
                        <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                            Compare original and dubbed videos side by side
                        </p>
                    </div>

                    <div className="grid grid-2">
                        <div>
                            <div style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                marginBottom: 'var(--spacing-3)'
                            }}>
                                <h4>Original Video</h4>
                                <button
                                    className={`btn ${showOriginalPreview ? 'btn-danger' : 'btn-secondary'}`}
                                    onClick={() => setShowOriginalPreview(!showOriginalPreview)}
                                    style={{ padding: 'var(--spacing-2) var(--spacing-4)' }}
                                >
                                    {showOriginalPreview ? 'Hide' : 'Preview'}
                                </button>
                            </div>
                            {showOriginalPreview && (
                                <VideoPreview
                                    videoUrl={`/api/stream/original/${jobId}`}
                                    title="Original Video"
                                />
                            )}
                        </div>

                        <div>
                            <div style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                marginBottom: 'var(--spacing-3)'
                            }}>
                                <h4>Dubbed Video</h4>
                                <button
                                    className={`btn ${showDubbedPreview ? 'btn-danger' : 'btn-primary'}`}
                                    onClick={() => setShowDubbedPreview(!showDubbedPreview)}
                                    style={{ padding: 'var(--spacing-2) var(--spacing-4)' }}
                                >
                                    {showDubbedPreview ? 'Hide' : 'Preview'}
                                </button>
                            </div>
                            {showDubbedPreview && (
                                <VideoPreview
                                    videoUrl={`/api/stream/dubbed/${jobId}`}
                                    title="Dubbed Video"
                                />
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Download Section */}
            <div className="card">
                <div className="card-header">
                    <h2 className="card-title">Download Results</h2>
                </div>

                <div className="grid grid-3">
                    <div style={{ textAlign: 'center', padding: 'var(--spacing-4)' }}>
                        <div style={{ fontSize: '3rem', marginBottom: 'var(--spacing-2)' }}>🎬</div>
                        <h4>Dubbed Video</h4>
                        <p style={{
                            color: 'var(--color-neutral-500)',
                            fontSize: 'var(--font-size-sm)',
                            marginBottom: 'var(--spacing-3)'
                        }}>
                            Final video with translated audio
                        </p>
                        <button className="btn btn-primary" onClick={handleDownloadVideo}>
                            Download Video
                        </button>
                    </div>

                    <div style={{ textAlign: 'center', padding: 'var(--spacing-4)' }}>
                        <div style={{ fontSize: '3rem', marginBottom: 'var(--spacing-2)' }}>🎵</div>
                        <h4>Audio Track</h4>
                        <p style={{
                            color: 'var(--color-neutral-500)',
                            fontSize: 'var(--font-size-sm)',
                            marginBottom: 'var(--spacing-3)'
                        }}>
                            Separated audio file
                        </p>
                        <button className="btn btn-secondary" onClick={handleDownloadAudio}>
                            Download Audio
                        </button>
                    </div>

                    <div style={{ textAlign: 'center', padding: 'var(--spacing-4)' }}>
                        <div style={{ fontSize: '3rem', marginBottom: 'var(--spacing-2)' }}>📋</div>
                        <h4>Audit Report</h4>
                        <p style={{
                            color: 'var(--color-neutral-500)',
                            fontSize: 'var(--font-size-sm)',
                            marginBottom: 'var(--spacing-3)'
                        }}>
                            Complete compliance log
                        </p>
                        <button
                            className="btn btn-secondary"
                            onClick={handleDownloadAudit}
                        >
                            Download JSON
                        </button>
                    </div>
                </div>
            </div>

            {/* Audit Summary */}
            <div className="card">
                <div className="card-header">
                    <h2 className="card-title">Audit Summary</h2>
                    <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                        Complete log of all processing steps for accountability
                    </p>
                </div>

                {/* Job Info */}
                <div className="grid grid-2" style={{ marginBottom: 'var(--spacing-6)' }}>
                    <div>
                        <p style={{ color: 'var(--color-neutral-500)', fontSize: 'var(--font-size-sm)' }}>
                            Job ID
                        </p>
                        <p style={{ fontFamily: 'monospace' }}>{auditData.job_id}</p>
                    </div>
                    <div>
                        <p style={{ color: 'var(--color-neutral-500)', fontSize: 'var(--font-size-sm)' }}>
                            Completed At
                        </p>
                        <p>{formatTimestamp(auditData.completed_at)}</p>
                    </div>
                </div>

                {/* Processing Steps */}
                <h4 style={{ marginBottom: 'var(--spacing-3)' }}>Processing Steps</h4>
                <div style={{ marginBottom: 'var(--spacing-6)' }}>
                    {auditData.steps.map((step, index) => (
                        <div
                            key={index}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                padding: 'var(--spacing-2) 0',
                                borderBottom: index < auditData.steps.length - 1
                                    ? '1px solid var(--color-neutral-200)'
                                    : 'none'
                            }}
                        >
                            <span style={{
                                color: 'var(--color-success)',
                                marginRight: 'var(--spacing-3)'
                            }}>
                                ✓
                            </span>
                            <span style={{ flex: 1 }}>
                                {formatStepName(step.step_name)}
                            </span>
                            <span style={{
                                color: 'var(--color-neutral-500)',
                                fontSize: 'var(--font-size-sm)'
                            }}>
                                {step.status}
                            </span>
                        </div>
                    ))}
                </div>

                {/* Metrics Grid */}
                <div className="grid grid-3" style={{ marginBottom: 'var(--spacing-4)' }}>
                    {/* Safety */}
                    <div className="card" style={{ backgroundColor: 'var(--color-neutral-100)' }}>
                        <h4 style={{ marginBottom: 'var(--spacing-2)' }}>Safety Analysis</h4>
                        {auditData.safety_analysis ? (
                            <>
                                <div className={`risk-badge ${auditData.safety_analysis.risk_level}`}>
                                    {auditData.safety_analysis.risk_level} risk
                                </div>
                                <p style={{
                                    marginTop: 'var(--spacing-2)',
                                    fontSize: 'var(--font-size-sm)',
                                    color: 'var(--color-neutral-600)'
                                }}>
                                    Score: {auditData.safety_analysis.risk_score}/100
                                    <br />
                                    Flags: {auditData.safety_analysis.flags_count || (auditData.safety_analysis.flags ? auditData.safety_analysis.flags.length : 0)}
                                </p>
                            </>
                        ) : (
                            <p style={{ color: 'var(--color-neutral-500)' }}>Analysis pending...</p>
                        )}
                    </div>

                    {/* Translation */}
                    <div className="card" style={{ backgroundColor: 'var(--color-neutral-100)' }}>
                        <h4 style={{ marginBottom: 'var(--spacing-2)' }}>Translation</h4>
                        {auditData.translation_data ? (
                            <>
                                <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>
                                    {auditData.translation_data.source_language?.toUpperCase() || '?'} → {auditData.translation_data.target_language?.toUpperCase() || '?'}
                                </p>
                                <p style={{
                                    marginTop: 'var(--spacing-2)',
                                    fontSize: 'var(--font-size-sm)',
                                    color: 'var(--color-neutral-600)'
                                }}>
                                    Segments: {auditData.translation_data.segments_translated || 0}
                                    <br />
                                    Avg Confidence: {((auditData.translation_data.average_confidence || 0) * 100).toFixed(0)}%
                                </p>
                            </>
                        ) : (
                            <p style={{ color: 'var(--color-neutral-500)' }}>pending...</p>
                        )}
                    </div>

                    {/* Voice */}
                    <div className="card" style={{ backgroundColor: 'var(--color-neutral-100)' }}>
                        <h4 style={{ marginBottom: 'var(--spacing-2)' }}>Voice Synthesis</h4>
                        {auditData.voice_synthesis ? (
                            <>
                                <p style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>
                                    {auditData.voice_synthesis.service || 'Unknown'}
                                </p>
                                <p style={{
                                    marginTop: 'var(--spacing-2)',
                                    fontSize: 'var(--font-size-sm)',
                                    color: 'var(--color-neutral-600)'
                                }}>
                                    Consent: {auditData.voice_synthesis.consent_verified ? 'Verified' : 'Pending'}
                                    <br />
                                    AI Generated: Yes
                                </p>
                            </>
                        ) : (
                            <p style={{ color: 'var(--color-neutral-500)' }}>pending...</p>
                        )}
                    </div>
                </div>

                {/* User Decisions */}
                {auditData.user_decisions.length > 0 && (
                    <>
                        <h4 style={{ marginBottom: 'var(--spacing-3)' }}>User Decisions</h4>
                        {auditData.user_decisions.map((decision, index) => (
                            <div
                                key={index}
                                className="transcript-segment"
                            >
                                <span className="segment-time">{decision.decision_type}</span>
                                <span className="segment-text">{decision.decision_value}</span>
                            </div>
                        ))}
                    </>
                )}
            </div>

            {/* Start New */}
            <div style={{ textAlign: 'center', marginTop: 'var(--spacing-6)' }}>
                <button
                    className="btn btn-primary btn-lg"
                    onClick={() => navigate('/')}
                >
                    Start New Dubbing
                </button>
            </div>
        </div>
    )
}

export default ResultsPage
