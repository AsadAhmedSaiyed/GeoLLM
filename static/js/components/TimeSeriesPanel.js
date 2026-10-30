// TimeSeriesPanel Component: Time slider, playback, synchronized sparkline/chart, and timeline loader.
import { html, React } from '/static/js/html.js';

const { useState, useEffect, useRef } = React;

export function TimeSeriesPanel({
  runDir = '',
  taskId = '',
  onFrameChange = null,
  activeLayer = '',
  onToggleLayer = null,
}) {
  const [timeline, setTimeline] = useState(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(800); // ms per frame
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  // Fetch timeline.json whenever runDir or taskId changes
  useEffect(() => {
    if (!runDir && !taskId) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    const timelineUrl = taskId
      ? `/api/runs/${encodeURIComponent(taskId)}/timeline.json`
      : `/api/artifacts/timeline.json?dir=${encodeURIComponent(runDir)}`;

    fetch(timelineUrl)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load timeline.json (${res.status})`);
        }
        return res.json();
      })
      .then((data) => {
        if (!isMounted) return;
        if (data && data.frames && data.frames.length > 0) {
          setTimeline(data);
          setCurrentIndex(0);
          if (onFrameChange) {
            onFrameChange(data.frames[0], 0);
          }
        } else {
          setError('Timeline has no frames');
        }
      })
      .catch((err) => {
        if (isMounted) setError(err.message);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [runDir, taskId]);

  // Handle Play/Pause
  useEffect(() => {
    if (isPlaying && timeline && timeline.frames.length > 1) {
      timerRef.current = setInterval(() => {
        setCurrentIndex((prev) => {
          const next = (prev + 1) % timeline.frames.length;
          if (onFrameChange) {
            onFrameChange(timeline.frames[next], next);
          }
          return next;
        });
      }, playbackSpeed);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, playbackSpeed, timeline]);

  const handleSliderChange = (e) => {
    const idx = parseInt(e.target.value, 10);
    setCurrentIndex(idx);
    if (timeline && timeline.frames[idx] && onFrameChange) {
      onFrameChange(timeline.frames[idx], idx);
    }
  };

  const togglePlay = () => {
    setIsPlaying(!isPlaying);
  };

  if (loading) {
    return html`
      <div className="ts-panel" style=${{ display: 'flex', alignItems: 'center', gap: '8px', color: '#94A3B8', fontSize: '12px' }}>
        <svg style=${{ width: '16px', height: '16px', animation: 'spin 1s linear infinite' }} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle style=${{ opacity: 0.25 }} cx="12" cy="12" r="10" stroke="#38BDF8" strokeWidth="4"></circle>
          <path style=${{ opacity: 0.75 }} fill="#38BDF8" d="M4 12a8 8 0 018-8v8H4z"></path>
        </svg>
        <span>Loading time series timeline...</span>
      </div>
    `;
  }

  if (error || !timeline || !timeline.frames || timeline.frames.length === 0) {
    return null; // Gracefully hidden if no timeline artifact exists
  }

  const currentFrame = timeline.frames[currentIndex] || {};
  const totalFrames = timeline.frames.length;

  // Single-frame guard: Don't show play/scrub controls for a static single frame
  if (totalFrames <= 1) {
    return html`
      <div className="ts-panel" style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px' }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style=${{ fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', fontSize: '11px', letterSpacing: '0.05em' }}>
            Single Frame Observation
          </span>
          <span style=${{ fontFamily: 'IBM Plex Mono, monospace', color: '#94A3B8', fontSize: '11px' }}>
            ${currentFrame.date ? currentFrame.date.substring(0, 10) : ''}
          </span>
        </div>
        ${currentFrame.value !== undefined && currentFrame.value !== null && html`
          <span className="ts-badge">
            ${currentFrame.value.toFixed ? currentFrame.value.toFixed(4) : currentFrame.value} ${timeline.unit || ''}
          </span>
        `}
      </div>
    `;
  }

  const chartTitle = timeline.metric_name || timeline.title || 'Temporal Trend';
  const startDate = timeline.frames[0]?.date ? timeline.frames[0].date.substring(0, 10) : '';
  const endDate = timeline.frames[totalFrames - 1]?.date ? timeline.frames[totalFrames - 1].date.substring(0, 10) : '';

  // Render synced SVG sparkline with area fill and axis labels
  const values = timeline.frames.map((f) => (f.value !== undefined && f.value !== null ? f.value : null));
  const hasValues = values.some((v) => v !== null);

  let sparklineSvg = null;
  if (hasValues) {
    const validVals = values.filter((v) => v !== null);
    const minVal = Math.min(...validVals);
    const maxVal = Math.max(...validVals);
    const range = maxVal - minVal > 0 ? maxVal - minVal : 1;
    const width = 360;
    const height = 54;
    const padding = 6;
    const bottomY = height - padding;

    const pointCoords = values.map((v, i) => {
      if (v === null) return null;
      const x = padding + (i / (totalFrames - 1 || 1)) * (width - 2 * padding);
      const y = height - padding - ((v - minVal) / range) * (height - 2 * padding);
      return [x, y];
    }).filter(Boolean);

    const points = pointCoords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const firstX = pointCoords[0] ? pointCoords[0][0].toFixed(1) : padding;
    const lastX = pointCoords[pointCoords.length - 1] ? pointCoords[pointCoords.length - 1][0].toFixed(1) : (width - padding);
    const areaPoints = `${firstX},${bottomY} ${points} ${lastX},${bottomY}`;

    const curX = padding + (currentIndex / (totalFrames - 1 || 1)) * (width - 2 * padding);
    const curVal = currentFrame.value !== undefined && currentFrame.value !== null ? currentFrame.value : null;
    const curY = curVal !== null ? height - padding - ((curVal - minVal) / range) * (height - 2 * padding) : height / 2;

    sparklineSvg = html`
      <div className="ts-sparkline-box">
        <div className="ts-sparkline-header">
          <span className="ts-sparkline-title">${chartTitle}</span>
          <span className="ts-sparkline-range">Range: ${minVal.toFixed(2)} – ${maxVal.toFixed(2)} ${timeline.unit || ''}</span>
        </div>
        <svg viewBox="0 0 ${width} ${height}" className="ts-sparkline-svg" style=${{ width: '100%', height: '54px', display: 'block' }}>
          <defs>
            <linearGradient id="sparkGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#0ea5e9" stop-opacity="0.45" />
              <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0.0" />
            </linearGradient>
          </defs>
          <polygon points="${areaPoints}" fill="url(#sparkGradient)" />
          <polyline fill="none" stroke="#0ea5e9" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" points="${points}" />
          ${curVal !== null && html`
            <circle cx="${curX}" cy="${curY}" r="4.5" fill="#38bdf8" stroke="#0b1120" strokeWidth="2" />
            <line x1="${curX}" y1="0" x2="${curX}" y2="${height}" stroke="#38bdf8" strokeWidth="1.2" strokeDasharray="2,2" opacity="0.8" />
          `}
        </svg>
        <div className="ts-sparkline-axis">
          <span>${startDate}</span>
          <span className="ts-sparkline-cur">Current: ${curVal !== null ? (curVal.toFixed ? curVal.toFixed(4) : curVal) : '—'}</span>
          <span>${endDate}</span>
        </div>
      </div>
    `;
  }

  return html`
    <div className="ts-panel">
      <div className="ts-header">
        <div className="ts-title-group">
          <span className="ts-title">Time Series Animation</span>
          <span className="ts-frame-count">(${totalFrames} dates)</span>
        </div>
        ${currentFrame.value !== undefined &&
        currentFrame.value !== null &&
        html`
          <div className="ts-badge">
            ${currentFrame.value.toFixed ? currentFrame.value.toFixed(4) : currentFrame.value} ${timeline.unit || ''}
          </div>
        `}
      </div>

      ${sparklineSvg}

      <div className="ts-controls-row">
        <button
          onClick=${togglePlay}
          className="ts-play-btn"
          title=${isPlaying ? 'Pause' : 'Play'}
        >
          ${isPlaying ? '⏸' : '▶'}
        </button>

        <input
          type="range"
          min="0"
          max=${totalFrames - 1}
          value=${currentIndex}
          onChange=${handleSliderChange}
          className="ts-slider"
        />

        <div className="ts-counter">
          ${currentIndex + 1} / ${totalFrames}
        </div>
      </div>

      <div className="ts-footer">
        <span>${currentFrame.date ? currentFrame.date.substring(0, 10) : ''}</span>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>Speed:</span>
          <select
            value=${playbackSpeed}
            onChange=${(e) => setPlaybackSpeed(Number(e.target.value))}
            className="ts-speed-select"
          >
            <option value="1500">0.5x</option>
            <option value="800">1x</option>
            <option value="400">2x</option>
          </select>
        </div>
      </div>
    </div>
  `;
}

