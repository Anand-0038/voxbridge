import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import SafetyDashboard from '../components/SafetyDashboard'

function AnalysisPage({ jobId, demoContext, onAnalysisComplete }) {
    const [loading, setLoading] = useState(false)
    const [waitingForProcessing, setWaitingForProcessing] = useState(false)
    const [currentStatus, setCurrentStatus] = useState('') // Show current backend status
    const [analysisData, setAnalysisData] = useState(null)
    const [error, setError] = useState(null)
    const navigate = useNavigate()

    // Demo data for when no job is active
    const demoSafeData = {
        risk_score: 5,
        risk_level: 'low',
        flags: [],
        transcript_segments: [
            { text: 'Welcome to this demonstration of our video dubbing platform.', start_time: 0, end_time: 4, confidence: 0.97 },
            { text: 'This system uses responsible AI to ensure content safety.', start_time: 4, end_time: 8, confidence: 0.95 },
            { text: 'All content is analyzed before translation and dubbing.', start_time: 8, end_time: 12, confidence: 0.96 },
            { text: 'Thank you for watching our demonstration.', start_time: 12, end_time: 15, confidence: 0.98 },
        ],
        analysis_summary: 'No safety concerns detected. Content is safe for dubbing.'
    }

    const demoFlaggedData = {
        risk_score: 75,
        risk_level: 'high',
        flags: [
            {
                category: 'misinformation',
                severity: 'high',
                text_segment: 'This revolutionary product will cure all diseases instantly.',
                explanation: 'This claim is medically inaccurate and potentially harmful. Making unverified health claims can mislead viewers and cause them to forgo legitimate medical treatment.',
                confidence: 0.92
            },
            {
                category: 'bias',
                severity: 'high',
                text_segment: 'Studies show that certain groups are naturally less capable.',
                explanation: 'This statement promotes harmful stereotypes about groups of people. Such generalizations are scientifically unfounded and can perpetuate discrimination.',
                confidence: 0.89
            }
        ],
        transcript_segments: [
            { text: 'Welcome to our product demonstration video.', start_time: 0, end_time: 3, confidence: 0.98 },
            { text: 'This revolutionary product will cure all diseases instantly.', start_time: 3, end_time: 7, confidence: 0.95 },
            { text: 'Studies show that certain groups are naturally less capable.', start_time: 7, end_time: 11, confidence: 0.92 },
            { text: 'Thank you for watching our presentation.', start_time: 11, end_time: 14, confidence: 0.97 },
        ],
        analysis_summary: 'High-risk content detected. Contains misinformation and potentially biased statements.'
    }

    const buildDemoAnalysis = (mode, transcriptPayload) => {
        if (!transcriptPayload || !Array.isArray(transcriptPayload.transcript)) {
            return mode === 'flagged' ? demoFlaggedData : demoSafeData
        }

        const transcriptSegments = transcriptPayload.transcript.map((segment) => ({
            text: segment.text || '',
            start_time: Number(segment.start_time) || 0,
            end_time: Number(segment.end_time) || 0,
            confidence: typeof segment.confidence === 'number'
                ? segment.confidence
                : 0.97,
        }))

        const flags = Array.isArray(transcriptPayload.expected_flags)
            ? transcriptPayload.expected_flags.map((flag, index) => {
                const segment = transcriptSegments[flag.segment_index] || {}
                return {
                    category: flag.category || 'content',
                    severity: 'high',
                    text_segment: segment.text || '',
                    explanation: `Demo expected flag for ${flag.category || 'content'} segment ${index + 1}.`,
                    confidence: segment.confidence || 0.95
                }
            })
            : []

        return {
            risk_score: mode === 'flagged' || flags.length > 0 ? 75 : 5,
            risk_level: mode === 'flagged' || flags.length > 0 ? 'high' : 'low',
            flags,
            transcript_segments: transcriptSegments,
            analysis_summary: mode === 'flagged' || flags.length > 0
                ? 'High-risk content detected. Contains synthetic demo flags.'
                : 'No safety concerns detected. Content is safe for dubbing.'
        }
    }

    useEffect(() => {
        if (jobId && jobId.startsWith('demo-')) {
            const demoType = demoContext?.type || 'safe'
            const contextData = demoContext?.data || null
            const initialData = buildDemoAnalysis(demoType, contextData)
            setAnalysisData(initialData)
            if (onAnalysisComplete) {
                onAnalysisComplete(initialData)
            }
            return
        }

        if (jobId) {
            runAnalysis()
        }
        // FIXED: No automatic demo data - user must explicitly click demo button
        // If no jobId, show nothing (handled in render below)
    }, [jobId, demoContext])

    const runAnalysis = async () => {
        setLoading(true)
        setError(null)

        try {
            // RACE CONDITION FIX: Poll until job is ready for analysis
            // The backend needs time to process (transcribe) the video first
            let isReady = false
            let attempts = 0
            const maxAttempts = 60 // 2 minutes max wait (60 * 2s)

            while (!isReady && attempts < maxAttempts) {
                const statusRes = await fetch(`/api/job-status/${jobId}`)
                if (statusRes.ok) {
                    const statusData = await statusRes.json()
                    const status = statusData.status
                    setCurrentStatus(status) // Update UI with current status
                    console.log(`[Analysis] Job status: ${status}`)

                    if (statusData.status === 'ready_for_analysis') {
                        isReady = true
                    } else if (statusData.status === 'error') {
                        throw new Error(statusData.message || 'Processing failed')
                    } else if (statusData.status === 'analyzed') {
                        // Already analyzed, skip to fetching results
                        const auditRes = await fetch(`/api/audit-report/${jobId}`)
                        if (auditRes.ok) {
                            const auditData = await auditRes.json()
                            // Convert audit format to analysis format
                            setAnalysisData({
                                risk_score: auditData.safety_analysis?.risk_score || 0,
                                risk_level: auditData.safety_analysis?.risk_level || 'low',
                                flags: auditData.safety_analysis?.flags || [],
                                transcript_segments: auditData.transcript_segments || [],
                                analysis_summary: 'Previously analyzed content.'
                            })
                            setLoading(false)
                            return
                        }
                        isReady = true // Try analyze anyway
                    } else {
                        // Still processing, wait and retry
                        await new Promise(resolve => setTimeout(resolve, 2000))
                        attempts++
                    }
                } else {
                    throw new Error('Failed to check job status')
                }
            }

            if (!isReady) {
                throw new Error('Processing timeout. Please try again.')
            }

            // Now call analyze-content
            const response = await fetch('/api/analyze-content', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            })

            if (!response.ok) {
                const errorData = await response.json()
                throw new Error(errorData.detail || 'Analysis failed')
            }

            const data = await response.json()
            setAnalysisData(data)

            if (onAnalysisComplete) {
                onAnalysisComplete(data)
            }

        } catch (err) {
            // FIXED: Don't auto-fallback to demo data - show actual error
            console.error('Analysis error:', err)
            setError(err.message)
            // analysisData stays null, showing "No content" UI
        } finally {
            setLoading(false)
        }
    }

    const loadDemoData = (type) => {
        setAnalysisData(type === 'flagged' ? demoFlaggedData : demoSafeData)
        if (onAnalysisComplete) {
            onAnalysisComplete(type === 'flagged' ? demoFlaggedData : demoSafeData)
        }
    }

    const handleProceed = () => {
        if (onAnalysisComplete && analysisData) {
            onAnalysisComplete(analysisData)
        }
        navigate('/dubbing')
    }

    return (
        <div className="safety-dashboard">
            {loading ? (
                <div className="card">
                    <div className="loading">
                        <div className="spinner" />
                        <p style={{ marginTop: 'var(--spacing-4)' }}>
                            {currentStatus === 'processing' || currentStatus === 'uploaded'
                                ? 'Processing video...'
                                : 'Analyzing content for safety...'}
                        </p>
                        <p style={{ color: 'var(--color-neutral-500)', fontSize: 'var(--font-size-sm)' }}>
                            {currentStatus === 'uploaded' && 'Extracting audio...'}
                            {currentStatus === 'processing' && 'Transcribing audio (this may take 1-2 minutes)...'}
                            {currentStatus === 'ready_for_analysis' && 'Running safety checks...'}
                            {!currentStatus && 'Checking for toxicity, bias, and misinformation'}
                        </p>
                    </div>
                </div>
            ) : analysisData ? (
                <>
                    <SafetyDashboard data={analysisData} />

                    {/* Demo toggle buttons */}
                    {!jobId && (
                        <div className="card" style={{ marginTop: 'var(--spacing-4)' }}>
                            <p style={{ marginBottom: 'var(--spacing-3)', fontSize: 'var(--font-size-sm)', color: 'var(--color-neutral-500)' }}>
                                Switch demo content:
                            </p>
                            <div style={{ display: 'flex', gap: 'var(--spacing-2)' }}>
                                <button
                                    className={`btn ${analysisData.risk_level === 'low' ? 'btn-primary' : 'btn-secondary'}`}
                                    onClick={() => loadDemoData('safe')}
                                >
                                    Safe Content
                                </button>
                                <button
                                    className={`btn ${analysisData.risk_level === 'high' ? 'btn-primary' : 'btn-secondary'}`}
                                    onClick={() => loadDemoData('flagged')}
                                >
                                    Flagged Content
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Action buttons */}
                    <div style={{
                        display: 'flex',
                        justifyContent: 'center',
                        gap: 'var(--spacing-4)',
                        marginTop: 'var(--spacing-6)'
                    }}>
                        <button
                            className="btn btn-secondary"
                            onClick={() => navigate('/')}
                        >
                            Back to Upload
                        </button>
                        <button
                            className="btn btn-primary btn-lg"
                            onClick={handleProceed}
                        >
                            {analysisData.risk_level === 'high'
                                ? 'Review and Proceed'
                                : 'Proceed to Dubbing'
                            }
                        </button>
                    </div>
                </>
            ) : (
                <div className="card">
                    {/* Show actual error if present */}
                    {error ? (
                        <div className="alert alert-danger" style={{ marginBottom: 'var(--spacing-4)' }}>
                            <strong>Analysis Failed</strong>
                            <p style={{ marginTop: 'var(--spacing-2)' }}>{error}</p>
                        </div>
                    ) : (
                        <div className="alert alert-warning" style={{ marginBottom: 'var(--spacing-4)' }}>
                            <strong>No Content to Analyze</strong>
                            <p style={{ marginTop: 'var(--spacing-2)' }}>
                                Please upload a video first to see analysis results.
                            </p>
                        </div>
                    )}

                    <div style={{ display: 'flex', gap: 'var(--spacing-3)', flexWrap: 'wrap', justifyContent: 'center' }}>
                        <button
                            className="btn btn-primary"
                            onClick={() => navigate('/')}
                        >
                            Go to Upload
                        </button>

                        {/* Explicit demo buttons - only shown when no job */}
                        {!jobId && (
                            <>
                                <button
                                    className="btn btn-secondary"
                                    onClick={() => loadDemoData('safe')}
                                >
                                    Try Demo (Safe)
                                </button>
                                <button
                                    className="btn btn-secondary"
                                    onClick={() => loadDemoData('flagged')}
                                >
                                    Try Demo (Flagged)
                                </button>
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

export default AnalysisPage
