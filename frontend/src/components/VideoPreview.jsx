import { useState, useRef, useEffect } from 'react'

/**
 * VideoPreview - Reusable video player component with controls
 * 
 * Supports:
 * - Local file preview (from File object)
 * - Remote video streaming (from backend URL)
 * - Play/pause, progress bar, volume, fullscreen
 */
function VideoPreview({ file, videoUrl, title, onClose }) {
    const videoRef = useRef(null)
    const [isPlaying, setIsPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [duration, setDuration] = useState(0)
    const [volume, setVolume] = useState(1)
    const [isMuted, setIsMuted] = useState(false)
    const [isFullscreen, setIsFullscreen] = useState(false)
    const [error, setError] = useState(null)
    const [loading, setLoading] = useState(true)

    // Create object URL for local file preview
    const [objectUrl, setObjectUrl] = useState(null)

    useEffect(() => {
        if (file) {
            const url = URL.createObjectURL(file)
            setObjectUrl(url)
            return () => URL.revokeObjectURL(url)
        }
    }, [file])

    const src = videoUrl || objectUrl

    const handleLoadedMetadata = () => {
        if (videoRef.current) {
            setDuration(videoRef.current.duration)
            setLoading(false)
        }
    }

    const handleTimeUpdate = () => {
        if (videoRef.current) {
            setCurrentTime(videoRef.current.currentTime)
        }
    }

    const handleError = () => {
        setError('Failed to load video. The file may be corrupted or format not supported.')
        setLoading(false)
    }

    const togglePlay = () => {
        if (videoRef.current) {
            if (isPlaying) {
                videoRef.current.pause()
            } else {
                videoRef.current.play()
            }
            setIsPlaying(!isPlaying)
        }
    }

    const handleSeek = (e) => {
        const time = parseFloat(e.target.value)
        if (videoRef.current) {
            videoRef.current.currentTime = time
            setCurrentTime(time)
        }
    }

    const handleVolumeChange = (e) => {
        const vol = parseFloat(e.target.value)
        if (videoRef.current) {
            videoRef.current.volume = vol
            setVolume(vol)
            setIsMuted(vol === 0)
        }
    }

    const toggleMute = () => {
        if (videoRef.current) {
            videoRef.current.muted = !isMuted
            setIsMuted(!isMuted)
        }
    }

    const toggleFullscreen = () => {
        const container = videoRef.current?.parentElement
        if (!container) return

        if (!isFullscreen) {
            if (container.requestFullscreen) {
                container.requestFullscreen()
            } else if (container.webkitRequestFullscreen) {
                container.webkitRequestFullscreen()
            }
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen()
            } else if (document.webkitExitFullscreen) {
                document.webkitExitFullscreen()
            }
        }
        setIsFullscreen(!isFullscreen)
    }

    const formatTime = (seconds) => {
        if (!seconds || isNaN(seconds)) return '0:00'
        const mins = Math.floor(seconds / 60)
        const secs = Math.floor(seconds % 60)
        return `${mins}:${secs.toString().padStart(2, '0')}`
    }

    if (!src) {
        return (
            <div className="video-preview-placeholder">
                <p>No video selected</p>
            </div>
        )
    }

    return (
        <div className="video-preview-container">
            {title && (
                <div className="video-preview-header">
                    <h4>{title}</h4>
                    {onClose && (
                        <button className="video-close-btn" onClick={onClose}>
                            ×
                        </button>
                    )}
                </div>
            )}

            <div className="video-player-wrapper">
                {loading && (
                    <div className="video-loading">
                        <div className="spinner" />
                        <p>Loading video...</p>
                    </div>
                )}

                {error && (
                    <div className="video-error">
                        <p>{error}</p>
                    </div>
                )}

                <video
                    ref={videoRef}
                    src={src}
                    className="video-player"
                    onLoadedMetadata={handleLoadedMetadata}
                    onTimeUpdate={handleTimeUpdate}
                    onError={handleError}
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onEnded={() => setIsPlaying(false)}
                    onClick={togglePlay}
                    style={{ display: loading || error ? 'none' : 'block' }}
                />

                {!loading && !error && (
                    <div className="video-controls">
                        <button
                            className="video-control-btn"
                            onClick={togglePlay}
                            title={isPlaying ? 'Pause' : 'Play'}
                        >
                            {isPlaying ? (
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                    <rect x="6" y="4" width="4" height="16" />
                                    <rect x="14" y="4" width="4" height="16" />
                                </svg>
                            ) : (
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                    <polygon points="5,3 19,12 5,21" />
                                </svg>
                            )}
                        </button>

                        <span className="video-time">{formatTime(currentTime)}</span>

                        <input
                            type="range"
                            className="video-progress"
                            min="0"
                            max={duration || 0}
                            value={currentTime}
                            onChange={handleSeek}
                            step="0.1"
                        />

                        <span className="video-time">{formatTime(duration)}</span>

                        <button
                            className="video-control-btn"
                            onClick={toggleMute}
                            title={isMuted ? 'Unmute' : 'Mute'}
                        >
                            {isMuted ? (
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <polygon points="11,5 6,9 2,9 2,15 6,15 11,19" fill="currentColor" />
                                    <line x1="23" y1="9" x2="17" y2="15" />
                                    <line x1="17" y1="9" x2="23" y2="15" />
                                </svg>
                            ) : (
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <polygon points="11,5 6,9 2,9 2,15 6,15 11,19" fill="currentColor" />
                                    <path d="M15.54 8.46a5 5 0 010 7.07" />
                                    <path d="M19.07 4.93a10 10 0 010 14.14" />
                                </svg>
                            )}
                        </button>

                        <input
                            type="range"
                            className="video-volume"
                            min="0"
                            max="1"
                            value={isMuted ? 0 : volume}
                            onChange={handleVolumeChange}
                            step="0.1"
                        />

                        <button
                            className="video-control-btn"
                            onClick={toggleFullscreen}
                            title="Fullscreen"
                        >
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <polyline points="15,3 21,3 21,9" />
                                <polyline points="9,21 3,21 3,15" />
                                <line x1="21" y1="3" x2="14" y2="10" />
                                <line x1="3" y1="21" x2="10" y2="14" />
                            </svg>
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}

export default VideoPreview
