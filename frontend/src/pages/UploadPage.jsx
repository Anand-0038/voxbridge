import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import VideoPreview from '../components/VideoPreview'
import UiIcon from '../components/UiIcon'

function UploadPage({ onUploadComplete, onDemoMode }) {
    const [file, setFile] = useState(null)
    const [uploading, setUploading] = useState(false)
    const [progress, setProgress] = useState(0)
    const [error, setError] = useState(null)
    const [dragActive, setDragActive] = useState(false)
    const [showPreview, setShowPreview] = useState(false)
    const [platformStatus, setPlatformStatus] = useState(null)
    const [youtubeUrl, setYoutubeUrl] = useState('')
    const [sourceMode, setSourceMode] = useState('file')
    const fileInputRef = useRef(null)
    const navigate = useNavigate()

    useEffect(() => {
        const loadPlatformStatus = async () => {
            try {
                const response = await fetch('/health')
                if (response.ok) {
                    const payload = await response.json()
                    setPlatformStatus(payload)
                }
            } catch {
                setPlatformStatus(null)
            }
        }

        loadPlatformStatus()
    }, [])

    const handleDrag = (e) => {
        e.preventDefault()
        e.stopPropagation()
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true)
        } else if (e.type === 'dragleave') {
            setDragActive(false)
        }
    }

    const handleDrop = (e) => {
        e.preventDefault()
        e.stopPropagation()
        setDragActive(false)

        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFile(e.dataTransfer.files[0])
        }
    }

    const handleFileSelect = (e) => {
        if (e.target.files && e.target.files[0]) {
            handleFile(e.target.files[0])
        }
    }

    const handleFile = (selectedFile) => {
        // Updated to support MKV and WEBM
        const validTypes = [
            'video/mp4',
            'video/quicktime',
            'video/x-msvideo',
            'video/matroska',
            'video/mkv',
            'video/avi',
            'video/webm',
            'video/x-matroska',
            'video/m4v',
            'video/x-m4v',
        ]
        const extension = selectedFile.name.split('.').pop().toLowerCase()
        const validExtensions = ['mp4', 'mov', 'avi', 'webm', 'mkv', 'm4v']

        const isValidType = selectedFile.type ? validTypes.includes(selectedFile.type) : false
        const isValidExt = validExtensions.includes(extension)

        if (!isValidType && !isValidExt) {
            setError('Please select a valid video file (MP4, MOV, AVI, WEBM, MKV, M4V)')
            return
        }
        setFile(selectedFile)
        setSourceMode('file')
        setError(null)
        setShowPreview(true)
    }

    const handleUpload = async () => {
        if (!file) return

        setSourceMode('file')
        setUploading(true)
        setProgress(0)
        setError(null)

        const formData = new FormData()
        formData.append('file', file)

        // Use XMLHttpRequest for real upload progress tracking
        const xhr = new XMLHttpRequest()

        xhr.upload.addEventListener('progress', (event) => {
            if (event.lengthComputable) {
                const percentComplete = Math.round((event.loaded / event.total) * 100)
                setProgress(percentComplete)
            }
        })

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText)
                    // Bug #12 fix: Validate job_id exists in response
                    if (!data.job_id || typeof data.job_id !== 'string') {
                        setError('Server returned invalid response (missing job_id)')
                        setUploading(false)
                        return
                    }
                    setProgress(100)
                    if (onUploadComplete) {
                        onUploadComplete(data.job_id)
                    }
                    setTimeout(() => {
                        navigate('/analysis')
                    }, 500)
                } catch (e) {
                    setError('Failed to parse server response')
                    setUploading(false)
                }
            } else {
                let errorMessage = `Upload failed (${xhr.status})`
                try {
                    const errorData = JSON.parse(xhr.responseText)
                    errorMessage = errorData.detail || errorData.message || errorMessage
                } catch (e) {
                    if (xhr.responseText) {
                        errorMessage = `${errorMessage}: ${xhr.responseText}`
                    }
                }
                setError(errorMessage)
                setUploading(false)
            }
        })

        xhr.addEventListener('error', () => {
            setError('Network error. Please check your connection and try again.')
            setUploading(false)
        })

        xhr.addEventListener('timeout', () => {
            setError('Upload timed out. The file may be too large or the connection is slow.')
            setUploading(false)
        })

        xhr.addEventListener('abort', () => {
            setError('Upload cancelled')
            setUploading(false)
        })

        // 10 minute timeout for large files
        xhr.timeout = 600000

        xhr.open('POST', '/api/upload-video')
        xhr.send(formData)
    }

    const handleYoutubeImport = async () => {
        const url = youtubeUrl.trim()
        if (!url) {
            setError('Enter a YouTube video URL')
            return
        }

        setSourceMode('youtube')
        setUploading(true)
        setProgress(5)
        setError(null)

        try {
            const response = await fetch('/api/import-youtube', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            })
            const data = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(data.detail || `YouTube import failed (${response.status})`)
            }
            if (!data.job_id || typeof data.job_id !== 'string') {
                throw new Error('Server returned an invalid job ID')
            }

            setProgress(100)
            if (onUploadComplete) {
                onUploadComplete(data.job_id)
            }
            setTimeout(() => navigate('/analysis'), 300)
        } catch (err) {
            setError(err.message || 'YouTube import failed')
            setUploading(false)
        }
    }

    const handleDemoMode = async (mode) => {
        setUploading(true)
        setError(null)

        try {
            const endpoint = mode === 'safe'
                ? '/api/demo/safe-transcript'
                : '/api/demo/flagged-transcript'

            const response = await fetch(endpoint)
            if (!response.ok) {
                throw new Error('Demo endpoint returned an error')
            }
            const data = await response.json()

            // This is a preview-only route; it does not create a backend job.
            const previewJobId = `demo-${mode}-${Date.now()}`
            if (onUploadComplete) {
                onUploadComplete(previewJobId)
            }
            if (onDemoMode) {
                onDemoMode(mode, data)
            }

            navigate('/analysis')

        } catch (err) {
            setError('Failed to load demo content')
            console.error('Demo mode failed:', err)
        } finally {
            setUploading(false)
        }
    }

    return (
        <div className="safety-dashboard">
            <div className="card">
                <div className="card-header">
                    <h2 className="card-title">Upload Video</h2>
                    <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                        Upload a video file to begin the responsible dubbing process
                    </p>
                </div>

                {platformStatus && platformStatus.demo_mode && (
                    <div className="alert alert-warning" style={{ marginBottom: 'var(--spacing-4)' }}>
                        <UiIcon name="WarningCircle" size={18} />
                        <strong>Demo mode is active.</strong> This keeps transcription and dubbing in local fixture mode.
                        Set <code>DEMO_MODE=false</code> and configure real credentials to run genuine AI dubbing.
                    </div>
                )}

                {platformStatus && !platformStatus.demo_mode && platformStatus.tts?.status !== 'ready' && (
                    <div className="alert alert-error" style={{ marginBottom: 'var(--spacing-4)' }}>
                        <UiIcon name="PlugSlash" size={16} />
                        <strong>Real AI mode is not fully configured.</strong> The API status currently shows:
                        {' '}
                        {platformStatus.tts?.status || 'unknown'}.
                        Configure a valid <code>ELEVENLABS_API_KEY</code> to enable true voice synthesis.
                    </div>
                )}

                {error && (
                    <div className="alert alert-error">
                        {error}
                    </div>
                )}

                <div
                    className={`upload-zone ${dragActive ? 'dragging' : ''}`}
                    onDragEnter={handleDrag}
                    onDragLeave={handleDrag}
                    onDragOver={handleDrag}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                >
                    <div className="upload-icon">
                        <UiIcon name="UploadSimple" size={44} weight="duotone" />
                    </div>
                    {file ? (
                        <div>
                            <p style={{ fontWeight: 600 }}>{file.name}</p>
                            <p style={{ color: 'var(--color-neutral-500)', fontSize: 'var(--font-size-sm)' }}>
                                {(file.size / 1024 / 1024).toFixed(2)} MB
                            </p>
                        </div>
                    ) : (
                        <div>
                            <p style={{ fontWeight: 600 }}>Drop your video here or click to browse</p>
                            <p style={{ color: 'var(--color-neutral-500)', fontSize: 'var(--font-size-sm)' }}>
                                Supports MP4, MOV, AVI, WEBM, MKV, and M4V files
                            </p>
                        </div>
                    )}
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-msvideo,video/matroska,video/mkv,video/webm,video/x-matroska,video/avi,video/m4v,video/x-m4v"
                        onChange={handleFileSelect}
                        style={{ display: 'none' }}
                    />
                </div>

                {/* Video Preview */}
                {file && showPreview && (
                    <VideoPreview
                        file={file}
                        title={`Preview: ${file.name}`}
                        onClose={() => setShowPreview(false)}
                    />
                )}

                {uploading && (
                    <div style={{ marginTop: 'var(--spacing-4)' }}>
                        <div className="progress-bar">
                            <div className="progress-fill" style={{ width: `${progress}%` }} />
                        </div>
                        <p style={{
                            textAlign: 'center',
                            marginTop: 'var(--spacing-2)',
                            color: 'var(--color-neutral-500)',
                            fontSize: 'var(--font-size-sm)'
                        }}>
                            {progress < 100
                                ? sourceMode === 'youtube'
                                    ? 'Downloading from YouTube...'
                                    : 'Uploading and processing...'
                                : 'Source acquired!'}
                        </p>
                    </div>
                )}

                <div style={{
                    display: 'flex',
                    gap: 'var(--spacing-4)',
                    marginTop: 'var(--spacing-6)',
                    justifyContent: 'center'
                }}>
                    <button
                        className="btn btn-primary btn-lg"
                        aria-label="Upload and analyze"
                        onClick={handleUpload}
                        disabled={!file || uploading}
                    >
                        <UiIcon
                            name="UploadSimple"
                            size={20}
                            weight="bold"
                        />
                        {uploading ? 'Processing...' : 'Upload and Analyze'}
                    </button>
                </div>
            </div>

            <div className="card">
                <div className="card-header">
                    <h3 className="card-title">Import from YouTube</h3>
                    <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                        Acquire one public video URL and send it through the same analysis pipeline.
                    </p>
                </div>

                <div className="form-group">
                    <label className="form-label" htmlFor="youtube-url">YouTube video URL</label>
                    <input
                        id="youtube-url"
                        className="form-input"
                        type="url"
                        value={youtubeUrl}
                        onChange={(event) => setYoutubeUrl(event.target.value)}
                        placeholder="https://www.youtube.com/watch?v=..."
                        disabled={uploading}
                    />
                </div>
                <button
                    className="btn btn-secondary"
                    aria-label="Download YouTube and analyze"
                    onClick={handleYoutubeImport}
                    disabled={!youtubeUrl.trim() || uploading}
                >
                    <UiIcon name="YoutubeLogo" size={20} weight="bold" />
                    {uploading && sourceMode === 'youtube' ? 'Downloading...' : 'Download and Analyze'}
                </button>
                <p style={{
                    color: 'var(--color-neutral-500)',
                    fontSize: 'var(--font-size-sm)',
                    marginTop: 'var(--spacing-3)'
                }}>
                    Publishing to a channel is intentionally not enabled. You approve dubbing and download the result locally.
                </p>
            </div>

            {/* Demo Mode */}
            <div className="card">
                <div className="card-header">
                    <h3 className="card-title">Safety Preview</h3>
                    <p style={{ color: 'var(--color-neutral-500)', marginTop: 'var(--spacing-2)' }}>
                        Review sample safety results without creating a dubbing job or media artifact.
                    </p>
                </div>

                <div className="grid grid-2">
                    <div style={{ textAlign: 'center' }}>
                        <h4 style={{ marginBottom: 'var(--spacing-2)' }}>Safe Content</h4>
                        <p style={{
                            color: 'var(--color-neutral-500)',
                            fontSize: 'var(--font-size-sm)',
                            marginBottom: 'var(--spacing-4)'
                        }}>
                            Educational content about renewable energy
                        </p>
                        <button
                            className="btn btn-secondary"
                            aria-label="Preview safe content sample"
                            onClick={() => handleDemoMode('safe')}
                            disabled={uploading}
                        >
                            <UiIcon name="Play" size={18} weight="bold" />
                            Preview Safe Sample
                        </button>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                        <h4 style={{ marginBottom: 'var(--spacing-2)' }}>Flagged Content</h4>
                        <p style={{
                            color: 'var(--color-neutral-500)',
                            fontSize: 'var(--font-size-sm)',
                            marginBottom: 'var(--spacing-4)'
                        }}>
                            Content with safety flags for demonstration
                        </p>
                        <button
                            className="btn btn-secondary"
                            aria-label="Preview flagged content sample"
                            onClick={() => handleDemoMode('flagged')}
                            disabled={uploading}
                        >
                            <UiIcon name="Warning" size={18} weight="bold" />
                            Preview Flagged Sample
                        </button>
                    </div>
                </div>
            </div>

            {/* Info Card */}
            <div className="alert alert-info">
                <strong>Responsible AI Notice:</strong> All uploaded content will be analyzed for
                toxicity, bias, misinformation, and cultural sensitivity before dubbing.
                Every decision is logged for accountability.
            </div>
        </div>
    )
}

export default UploadPage
