function SafetyDashboard({ data }) {
    const { risk_score, risk_level, flags, transcript_segments, analysis_summary } = data

    const getRiskColor = (level) => {
        switch (level) {
            case 'low': return 'var(--color-success)'
            case 'medium': return 'var(--color-warning)'
            case 'high': return 'var(--color-danger)'
            default: return 'var(--color-neutral-500)'
        }
    }

    const getCategoryColor = (category) => {
        switch (category) {
            case 'toxicity': return { border: 'var(--color-danger)', bg: 'var(--color-danger-bg)' }
            case 'bias': return { border: 'var(--color-warning)', bg: 'var(--color-warning-bg)' }
            case 'misinformation': return { border: '#7c3aed', bg: '#ede9fe' }
            case 'cultural_sensitivity': return { border: '#0891b2', bg: '#cffafe' }
            case 'age_inappropriate': return { border: '#ea580c', bg: '#ffedd5' }
            default: return { border: 'var(--color-neutral-400)', bg: 'var(--color-neutral-100)' }
        }
    }

    const formatTime = (seconds) => {
        const mins = Math.floor(seconds / 60)
        const secs = Math.floor(seconds % 60)
        return `${mins}:${secs.toString().padStart(2, '0')}`
    }

    const isSegmentFlagged = (segmentText) => {
        return flags.some(flag => segmentText.includes(flag.text_segment))
    }

    return (
        <div className="safety-dashboard">
            {/* Risk Score Card */}
            <div className="card">
                <div className="safety-score">
                    <div
                        className={`safety-score-value ${risk_level}`}
                        style={{ color: getRiskColor(risk_level) }}
                    >
                        {risk_score}
                    </div>
                    <div style={{ marginTop: 'var(--spacing-2)' }}>
                        <span className={`risk-badge ${risk_level}`}>
                            {risk_level} Risk
                        </span>
                    </div>
                    <p style={{
                        marginTop: 'var(--spacing-4)',
                        color: 'var(--color-neutral-600)'
                    }}>
                        {analysis_summary}
                    </p>
                </div>
            </div>

            {/* Flags Section */}
            {flags.length > 0 && (
                <div className="card">
                    <div className="card-header">
                        <h3 className="card-title">Safety Flags ({flags.length})</h3>
                        <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                            Issues detected that require review before dubbing
                        </p>
                    </div>

                    <div className="safety-flags">
                        {flags.map((flag, index) => {
                            const colors = getCategoryColor(flag.category)
                            return (
                                <div
                                    key={index}
                                    className="flag-item"
                                    style={{
                                        borderColor: colors.border,
                                        backgroundColor: colors.bg
                                    }}
                                >
                                    <div className="flag-category" style={{ color: colors.border }}>
                                        {flag.category.replace('_', ' ')}
                                        <span style={{
                                            marginLeft: 'var(--spacing-2)',
                                            fontSize: 'var(--font-size-xs)',
                                            opacity: 0.8
                                        }}>
                                            ({(flag.confidence * 100).toFixed(0)}% confidence)
                                        </span>
                                    </div>
                                    <div className="flag-text">
                                        "{flag.text_segment}"
                                    </div>
                                    <div className="flag-explanation">
                                        {flag.explanation}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}

            {/* Transcript Section */}
            <div className="card">
                <div className="card-header">
                    <h3 className="card-title">Transcript</h3>
                    <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                        Original content with flagged segments highlighted
                    </p>
                </div>

                <div>
                    {transcript_segments.map((segment, index) => {
                        const isFlagged = isSegmentFlagged(segment.text)
                        return (
                            <div key={index} className="transcript-segment">
                                <span className="segment-time">
                                    {formatTime(segment.start_time)} - {formatTime(segment.end_time)}
                                </span>
                                <span className={`segment-text ${isFlagged ? 'flagged' : ''}`}>
                                    {segment.text}
                                </span>
                                <span style={{
                                    color: 'var(--color-neutral-400)',
                                    fontSize: 'var(--font-size-xs)'
                                }}>
                                    {(segment.confidence * 100).toFixed(0)}%
                                </span>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* No Flags Message */}
            {flags.length === 0 && (
                <div className="alert alert-success">
                    <strong>All Clear!</strong> No safety issues were detected in this content.
                    You can proceed with dubbing.
                </div>
            )}
        </div>
    )
}

export default SafetyDashboard
