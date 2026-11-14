import React, { useState, useEffect, useRef } from 'react';
import { TimelinePayload, TimelineFrame } from '@/types/geospatial';
import { Play, Pause, Loader2 } from 'lucide-react';

export interface TimeSeriesPanelProps {
  runDir?: string;
  taskId?: string;
  onFrameChange?: (frame: TimelineFrame | null, index?: number) => void;
}

export const TimeSeriesPanel: React.FC<TimeSeriesPanelProps> = ({
  runDir = '',
  taskId = '',
  onFrameChange,
}) => {
  const [timeline, setTimeline] = useState<TimelinePayload | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(800); // ms per frame
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onFrameChangeRef = useRef(onFrameChange);
  onFrameChangeRef.current = onFrameChange;

  // Fetch timeline.json whenever runDir or taskId changes
  useEffect(() => {
    if (!runDir && !taskId) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    const baseTimelineUrl = taskId
      ? `/api/runs/${encodeURIComponent(taskId)}/timeline.json`
      : `/api/artifacts/timeline.json?dir=${encodeURIComponent(runDir)}`;
    const timelineUrl = `${baseTimelineUrl}${baseTimelineUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;

    fetch(timelineUrl)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load timeline.json (${res.status})`);
        }
        return res.json();
      })
      .then((data: TimelinePayload) => {
        if (!isMounted) return;
        if (data && data.frames && data.frames.length > 0) {
          const framesWithGif: TimelineFrame[] = data.frames.map((fr) => ({
            ...fr,
            gif_url: fr.gif_url || data.gif_url,
          }));
          setTimeline({ ...data, frames: framesWithGif });
          setCurrentIndex(0);
          onFrameChangeRef.current?.(framesWithGif[0], 0);
        } else {
          setError('Timeline has no frames');
        }
      })
      .catch((err) => {
        if (isMounted) setError(err instanceof Error ? err.message : String(err));
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
          onFrameChangeRef.current?.(timeline.frames[next], next);
          return next;
        });
      }, playbackSpeed);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, playbackSpeed, timeline]);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const idx = parseInt(e.target.value, 10);
    setCurrentIndex(idx);
    if (timeline && timeline.frames[idx]) {
      onFrameChangeRef.current?.(timeline.frames[idx], idx);
    }
  };

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-lg p-3 flex items-center gap-2 text-muted-foreground text-xs">
        <Loader2 className="h-4 w-4 animate-spin text-sky-400" />
        <span>Loading time series timeline...</span>
      </div>
    );
  }

  if (error || !timeline || !timeline.frames || timeline.frames.length === 0) {
    return null; // Gracefully hidden if no timeline artifact exists
  }

  const currentFrame = timeline.frames[currentIndex] || {};
  const totalFrames = timeline.frames.length;

  // Single-frame guard: Don't show play/scrub controls for a static single frame
  if (totalFrames <= 1) {
    return (
      <div className="bg-card border border-border rounded-lg px-3.5 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-bold text-sky-400 uppercase text-[11px] tracking-wider">
            Single Frame Observation
          </span>
          <span className="font-mono text-muted-foreground text-[11px]">
            {currentFrame.date ? String(currentFrame.date).substring(0, 10) : ''}
          </span>
        </div>
        {currentFrame.value !== undefined && currentFrame.value !== null && (
          <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded-lg bg-sky-500/15 text-sky-400 border border-sky-500/30">
            {typeof currentFrame.value === 'number'
              ? currentFrame.value.toFixed(4)
              : String(currentFrame.value)}{' '}
            {timeline.unit || ''}
          </span>
        )}
      </div>
    );
  }

  const chartTitle = timeline.metric_name || timeline.title || 'Temporal Trend';
  const startDate = timeline.frames[0]?.date
    ? String(timeline.frames[0].date).substring(0, 10)
    : '';
  const endDate = timeline.frames[totalFrames - 1]?.date
    ? String(timeline.frames[totalFrames - 1].date).substring(0, 10)
    : '';

  const values = timeline.frames.map((f) =>
    typeof f.value === 'number' ? f.value : null
  );
  const validVals = values.filter((v): v is number => v !== null);
  const hasValues = validVals.length > 0;

  let sparklineElement: React.ReactNode = null;
  if (hasValues) {
    const minVal = Math.min(...validVals);
    const maxVal = Math.max(...validVals);
    const range = maxVal - minVal > 0 ? maxVal - minVal : 1;
    const width = 360;
    const height = 54;
    const padding = 6;
    const bottomY = height - padding;

    const pointCoords = values
      .map((v, i) => {
        if (v === null) return null;
        const x = padding + (i / (totalFrames - 1 || 1)) * (width - 2 * padding);
        const y = height - padding - ((v - minVal) / range) * (height - 2 * padding);
        return [x, y] as [number, number];
      })
      .filter((pt): pt is [number, number] => pt !== null);

    const points = pointCoords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const firstX = pointCoords[0] ? pointCoords[0][0].toFixed(1) : String(padding);
    const lastX = pointCoords[pointCoords.length - 1]
      ? pointCoords[pointCoords.length - 1][0].toFixed(1)
      : String(width - padding);
    const areaPoints = `${firstX},${bottomY} ${points} ${lastX},${bottomY}`;

    const curX = padding + (currentIndex / (totalFrames - 1 || 1)) * (width - 2 * padding);
    const curVal = typeof currentFrame.value === 'number' ? currentFrame.value : null;
    const curY =
      curVal !== null
        ? height - padding - ((curVal - minVal) / range) * (height - 2 * padding)
        : height / 2;

    sparklineElement = (
      <div className="bg-background border border-border rounded-lg p-2 mb-2.5">
        <div className="flex items-center justify-between text-[10px] font-mono mb-1">
          <span className="font-semibold text-foreground">{chartTitle}</span>
          <span className="text-muted-foreground">
            Range: {minVal.toFixed(2)} – {maxVal.toFixed(2)} {timeline.unit || ''}
          </span>
        </div>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-[54px] block"
        >
          <defs>
            <linearGradient id="sparkGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.0" />
            </linearGradient>
          </defs>
          <polygon points={areaPoints} fill="url(#sparkGradient)" />
          <polyline
            fill="none"
            stroke="#0ea5e9"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={points}
          />
          {curVal !== null && (
            <>
              <circle
                cx={curX}
                cy={curY}
                r="4.5"
                fill="#38bdf8"
                stroke="#0b1120"
                strokeWidth="2"
              />
              <line
                x1={curX}
                y1="0"
                x2={curX}
                y2={height}
                stroke="#38bdf8"
                strokeWidth="1.2"
                strokeDasharray="2,2"
                opacity="0.8"
              />
            </>
          )}
        </svg>
        <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground mt-1">
          <span>{startDate}</span>
          <span className="text-sky-400 font-semibold">
            Current: {curVal !== null ? curVal.toFixed(4) : '—'}
          </span>
          <span>{endDate}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-bold text-foreground">
            Time Series Animation
          </span>
          <span className="text-[11px] font-mono text-muted-foreground">
            ({totalFrames} dates)
          </span>
        </div>
        {typeof currentFrame.value === 'number' && (
          <div className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded-lg bg-sky-500/15 text-sky-400 border border-sky-500/30">
            {currentFrame.value.toFixed(4)} {timeline.unit || ''}
          </div>
        )}
      </div>

      {sparklineElement}

      <div className="flex items-center gap-2.5 mb-2">
        <button
          type="button"
          onClick={() => setIsPlaying((prev) => !prev)}
          title={isPlaying ? 'Pause' : 'Play'}
          className="h-7 w-7 rounded-lg bg-[#0284C7] hover:bg-[#0369A1] text-white flex items-center justify-center transition-colors shrink-0"
        >
          {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5 ml-0.5" />}
        </button>

        <input
          type="range"
          min={0}
          max={totalFrames - 1}
          value={currentIndex}
          onChange={handleSliderChange}
          className="flex-1 accent-sky-400 cursor-pointer"
        />

        <div className="text-[11px] font-mono text-foreground shrink-0 min-w-[44px] text-right">
          {currentIndex + 1} / {totalFrames}
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px] font-mono text-muted-foreground">
        <span>{currentFrame.date ? String(currentFrame.date).substring(0, 10) : ''}</span>
        <div className="flex items-center gap-1.5">
          <span>Speed:</span>
          <select
            value={playbackSpeed}
            onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
            className="bg-background border border-border text-foreground rounded-lg px-1.5 py-0.5 text-[11px] outline-none"
          >
            <option value={1500}>0.5x</option>
            <option value={800}>1x</option>
            <option value={400}>2x</option>
          </select>
        </div>
      </div>
    </div>
  );
};

