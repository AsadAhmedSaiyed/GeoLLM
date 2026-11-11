import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { TaskState, ActivityItem } from '@/types/task';
import { ArtifactItem } from '@/types/sse';
import { MarkdownView } from '@/components/MarkdownView';
import { ValidationViewer } from '@/components/ValidationViewer';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Satellite,
  ClipboardList,
  CheckCircle2,
  XCircle,
  Package,
  Globe,
  Trees,
  Mountain,
  Map,
  Image as ImageIcon,
  FileText,
  Brain,
  Wrench,
  Code2,
  FolderOpen,
  Download,
  Inbox,
  Eye,
  Microscope,
  Square,
  RotateCcw,
  ArrowDown,
} from 'lucide-react';

const getBasename = (p?: string | null): string => {
  if (!p) return '';
  return p.replace(/\\/g, '/').split('/').pop() || p;
};

export interface SingleWorkerSlotProps {
  taskId: string;
  task: TaskState;
  onApprovePlan?: (taskId: string) => void;
  onRevisePlan?: (taskId: string, feedback: string) => void;
  onCancelTask?: (taskId: string) => void;
  onResetTask?: (taskId: string) => void;
  onPreviewFile?: (artifact: string | ArtifactItem) => void;
  onSwitchToGlobe?: (artifact?: string | ArtifactItem) => void;
  onOpenTerrain3D?: (info: {
    taskId: string;
    payloadUrl: string;
    availableTextures: Array<string | ArtifactItem>;
    title: string;
  }) => void;
  onNotify?: (message: string, type?: 'info' | 'warning' | 'error' | 'success') => void;
  renderTimeSeriesPanel?: (props: {
    taskId: string;
    runDir?: string;
    onFrameChange: (frame: {
      file?: string;
      png_url?: string;
      gif_url?: string;
      label?: string;
      date?: string | null;
    } | null) => void;
  }) => React.ReactNode;
}

export const SingleWorkerSlot: React.FC<SingleWorkerSlotProps> = ({
  taskId,
  task,
  onApprovePlan,
  onRevisePlan,
  onCancelTask,
  onResetTask,
  onPreviewFile,
  onSwitchToGlobe,
  onOpenTerrain3D,
  onNotify,
  renderTimeSeriesPanel,
}) => {
  const [revisionFeedback, setRevisionFeedback] = useState('');
  const [showLogs, setShowLogs] = useState(true);
  const [timelineFrame, setTimelineFrame] = useState<{
    file?: string;
    png_url?: string;
    gif_url?: string;
    label?: string;
    date?: string | null;
  } | null>(null);

  const activityRef = useRef<HTMLDivElement | null>(null);
  const isUserScrolledUp = useRef(false);
  const [showScrollBottomBtn, setShowScrollBottomBtn] = useState(false);

  // When user uses the wheel or touches, immediately pause auto-scroll if scrolling upward
  const handleWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    if (e.deltaY < 0) {
      isUserScrolledUp.current = true;
      setShowScrollBottomBtn(true);
    }
  }, []);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    // Re-engage auto-scroll when user returns to within 24px of bottom
    if (distanceToBottom <= 24) {
      isUserScrolledUp.current = false;
      setShowScrollBottomBtn(false);
    } else if (distanceToBottom > 40) {
      isUserScrolledUp.current = true;
      setShowScrollBottomBtn(true);
    }
  }, []);

  const scrollToBottom = useCallback(() => {
    if (activityRef.current) {
      activityRef.current.scrollTo({
        top: activityRef.current.scrollHeight,
        behavior: 'smooth',
      });
      isUserScrolledUp.current = false;
      setShowScrollBottomBtn(false);
    }
  }, []);

  // Smooth auto-scroll activity feed to bottom using rAF without fighting user gestures
  useEffect(() => {
    if (!activityRef.current || !showLogs || isUserScrolledUp.current) return;
    const el = activityRef.current;
    const rafId = requestAnimationFrame(() => {
      if (el && !isUserScrolledUp.current) {
        el.scrollTop = el.scrollHeight;
      }
    });
    return () => cancelAnimationFrame(rafId);
  }, [task.activities, showLogs]);

  const taskNum = taskId ? taskId.replace('task_', '') : '1';

  const formatSeconds = (t: TaskState): string => {
    if (!t || t.status === 'idle') return 'Not started';
    if (!t.elapsed) return '00:00';
    const total = Math.floor(t.elapsed);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const statusLabel =
    task.status === 'running'
      ? task.step || 'Running…'
      : task.status === 'pending_stac_approval'
      ? 'STAC Satellite Preview Pending Review'
      : task.status === 'pending_approval'
      ? 'Plan Pending Approval'
      : task.status === 'done'
      ? 'Completed'
      : task.status === 'failed'
      ? task.error || 'Failed'
      : 'Idle';

  const inputGateActivity = (task.activities || [])
    .slice()
    .reverse()
    .find((a) => a.type === 'vision_input_gate');

  const artifacts = task.artifacts || [];
  const gifArt = artifacts.find((a) => {
    const name = typeof a === 'string' ? a : a.name || '';
    return name.toLowerCase().endsWith('.gif');
  });
  const hasTimeline =
    artifacts.some((a) => {
      const name = typeof a === 'string' ? a : a.name || '';
      return name.toLowerCase().includes('timeline.json');
    }) || !!gifArt;

  const terrain3dArt = artifacts.find((a) => {
    const name = typeof a === 'string' ? a : a.name || '';
    return name.toLowerCase().includes('terrain_3d.json');
  });

  const isLidar =
    artifacts.some((a) => {
      const name = typeof a === 'string' ? a : a.name || '';
      return ['lidar', 'chm', 'las', 'laz', 'canopy_height'].some((k) =>
        name.toLowerCase().includes(k)
      );
    }) ||
    (task.files || []).some((f) =>
      ['lidar', 'chm', 'las', 'laz', 'autzen'].some((k) => (f || '').toLowerCase().includes(k))
    ) ||
    (task.question || '').toLowerCase().includes('lidar') ||
    (task.question || '').toLowerCase().includes('canopy height') ||
    (task.question || '').toLowerCase().includes('point cloud');

  const isElevation =
    artifacts.some((a) => {
      const name = typeof a === 'string' ? a : a.name || '';
      return [
        'dem',
        'elevation',
        'dsm',
        'dtm',
        'cop-dem',
        'srtm',
        'nasadem',
        'topography',
        'terrain',
      ].some((k) => name.toLowerCase().includes(k));
    }) ||
    (task.files || []).some((f) =>
      ['dem', 'elevation', 'dsm', 'dtm', 'cop-dem', 'srtm', 'nasadem'].some((k) =>
        (f || '').toLowerCase().includes(k)
      )
    ) ||
    (task.question || '').toLowerCase().includes('elevation') ||
    (task.question || '').toLowerCase().includes('terrain') ||
    (task.question || '').toLowerCase().includes('topography') ||
    (task.question || '').toLowerCase().includes('dem') ||
    (task.question || '').toLowerCase().includes('slope');

  const canShow3D = !!terrain3dArt || isLidar || isElevation;

  const profileSvgArt = artifacts.find((a) => {
    const name = typeof a === 'string' ? a : a.name || '';
    return (
      name.toLowerCase().includes('profile.svg') ||
      (name.toLowerCase().includes('profile') && name.toLowerCase().endsWith('.svg'))
    );
  });

  const isDone = task.status === 'done';
  const isFailed = task.status === 'failed';

  // Collect the final assistant narrative from accumulated text activities
  const finalAnswer = (() => {
    if (!isDone && !isFailed) return null;
    const textParts = (task.activities || [])
      .filter((a): a is { type: 'text'; text: string; timestamp: number } => a.type === 'text' && !!a.text?.trim())
      .map((a) => a.text);
    return textParts.length > 0 ? textParts.join('') : null;
  })();

  const relevantActivities = useMemo(() => {
    const raw = (task.activities || []).filter(
      (act) => (act as { type: string }).type !== 'vision_input_gate'
    );
    const coalesced: ActivityItem[] = [];
    for (const act of raw) {
      if (act.type === 'thinking' && 'text' in act) {
        const last = coalesced[coalesced.length - 1];
        if (last && last.type === 'thinking' && 'text' in last) {
          last.text = (last.text || '') + (act.text || '');
          continue;
        }
        coalesced.push({ ...act, text: act.text || '' });
        continue;
      }
      coalesced.push(act);
    }
    return coalesced;
  }, [task.activities]);

  const handleOpen3D = () => {
    if (!onOpenTerrain3D) {
      onNotify?.('3D Terrain & LiDAR Viewer will be mounted in Phase 5.', 'info');
      return;
    }
    const payloadUrl = terrain3dArt
      ? typeof terrain3dArt === 'object' && terrain3dArt.url
        ? terrain3dArt.url
        : `/api/tasks/${taskId}/artifacts/${getBasename(
            typeof terrain3dArt === 'string' ? terrain3dArt : terrain3dArt.name
          )}`
      : `/api/runs/${taskId}/terrain_3d.json`;

    const availableTextures = artifacts.filter((a) => {
      const n = (typeof a === 'string' ? a : a.name || '').toLowerCase();
      return (
        (n.endsWith('.png') || n.endsWith('.jpg') || n.endsWith('.tif')) &&
        !n.includes('profile.svg') &&
        !n.includes('terrain_3d')
      );
    });

    onOpenTerrain3D({
      taskId,
      payloadUrl,
      availableTextures,
      title: isLidar
        ? 'Interactive 3D LiDAR Canopy & Structures'
        : 'Interactive 3D Digital Elevation Model',
    });
  };

  return (
    <div className="flex flex-col gap-3">
      {/* 1. Task Header Card */}
      <div className="bg-[#111827] border border-[#1E293B] rounded-lg p-3">
        <div className="flex items-center gap-2.5">
          <span className="font-mono bg-[#0F766E] text-white px-2 py-0.5 rounded text-[11px] font-bold shrink-0">
            #{taskNum}
          </span>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-[13px] text-slate-100 break-words">
              {task.question ? task.question : `Sandbox Slot #${taskNum} (Idle)`}
            </div>
            <div className="font-mono text-[11px] text-slate-400 mt-0.5">
              Elapsed: {formatSeconds(task)} • Status:{' '}
              <span
                className="font-semibold"
                style={{
                  color:
                    task.status === 'running'
                      ? '#38BDF8'
                      : task.status === 'done'
                      ? '#10B981'
                      : task.status === 'failed'
                      ? '#F87171'
                      : '#E2E8F0',
                }}
              >
                {statusLabel}
              </span>
            </div>
          </div>

          {(task.status === 'running' ||
            task.status === 'pending_approval' ||
            task.status === 'pending_stac_approval') && (
            <Button
              type="button"
              size="sm"
              variant="destructive"
              className="h-7 px-2.5 text-[11px] bg-rose-500/20 border border-rose-500 text-rose-300 hover:bg-rose-500/30 shrink-0 gap-1"
              onClick={() => onCancelTask?.(taskId)}
            >
              <Square className="h-3 w-3 fill-current" />
              <span>Abort Task</span>
            </Button>
          )}

          {(task.status === 'failed' || task.status === 'done' || task.status === 'partial') && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-7 px-2.5 text-[11px] bg-[#1E293B] border border-[#334155] text-slate-300 hover:text-white hover:border-slate-400 shrink-0 gap-1 cursor-pointer"
              onClick={() => onResetTask?.(taskId)}
              title="Reset this container sandbox and clear outputs"
            >
              <RotateCcw className="h-3 w-3" />
              <span>Reset Slot</span>
            </Button>
          )}
        </div>
      </div>

      {/* 2. Input Quality Gate Status Card */}
      {inputGateActivity && (
        <div>
          <ValidationViewer activity={inputGateActivity} />
        </div>
      )}

      {/* 3. Autonomous STAC Satellite Preview & Approval Gate */}
      {task.status === 'pending_stac_approval' && task.stacPreview && (
        <div
          className="bg-[#0F172A] border border-[#1E293B] rounded-lg p-3.5"
          style={{ borderLeft: '4px solid #0284C7' }}
        >
          <div className="flex justify-between items-center mb-2.5 flex-wrap gap-1.5">
            <span className="flex items-center gap-1.5 text-[13px] font-bold text-sky-400">
              <Satellite className="h-4 w-4 shrink-0" />
              <span>Satellite Scene Previews — Review Before Native-Resolution Staging</span>
            </span>
            <span className="font-mono text-[10.5px] text-sky-400 bg-sky-500/15 px-2 py-0.5 rounded-full border border-sky-500/30">
              100% Native Resolution Preserved
            </span>
          </div>

          {task.stacPreview.explanation && (
            <div className="text-xs text-slate-200 mb-2.5 leading-relaxed">
              <MarkdownView content={task.stacPreview.explanation} />
            </div>
          )}

          <div className="font-mono text-[11px] text-slate-400 bg-[#1E293B] px-2.5 py-2 rounded-md mb-3 flex flex-wrap gap-3.5">
            <span>
              <strong className="text-slate-200">Location:</strong>{' '}
              {task.stacPreview.location_name || 'Custom AOI'}
            </span>
            {task.stacPreview.bbox && (
              <span>
                <strong className="text-slate-200">BBox:</strong> [
                {task.stacPreview.bbox.map((n) => Number(n).toFixed(4)).join(', ')}]
              </span>
            )}
            {task.stacPreview.native_grid_estimate && (
              <span>
                <strong className="text-slate-200">Native Grid:</strong> ~
                {task.stacPreview.native_grid_estimate.estimated_width_px}×
                {task.stacPreview.native_grid_estimate.estimated_height_px} px (
                {task.stacPreview.native_grid_estimate.native_resolution_m}m native res,{' '}
                {task.stacPreview.native_grid_estimate.area_km2} km²)
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-3.5">
            {(task.stacPreview.scenes || []).map((sc, idx) => (
              <div
                key={sc.id || idx}
                className="bg-[#111827] border border-[#1E293B] rounded-md overflow-hidden"
              >
                {sc.thumbnail ? (
                  <div className="bg-[#090D14] text-center h-[140px] flex items-center justify-center overflow-hidden">
                    <img
                      src={sc.thumbnail}
                      alt={sc.label || sc.id || `Scene ${idx + 1}`}
                      className="max-h-[140px] max-w-full object-contain"
                    />
                  </div>
                ) : (
                  <div className="font-mono h-[100px] bg-[#090D14] text-slate-500 flex items-center justify-center text-[11px]">
                    No preview thumbnail
                  </div>
                )}
                <div className="p-2 text-[11px]">
                  <div className="font-bold text-slate-100 mb-1">
                    {sc.label || `Scene ${idx + 1}`}
                  </div>
                  <div className="font-mono text-[10px] text-slate-400 leading-relaxed space-y-0.5">
                    <div>
                      <strong className="text-slate-300">Collection:</strong> {sc.collection}
                    </div>
                    <div>
                      <strong className="text-slate-300">Date:</strong>{' '}
                      {(sc.datetime || '').slice(0, 10) || 'N/A'}
                    </div>
                    {sc.cloud_cover !== null && sc.cloud_cover !== undefined && (
                      <div>
                        <strong className="text-slate-300">Cloud Cover:</strong> {sc.cloud_cover}%
                      </div>
                    )}
                    {sc.aoi_coverage_pct !== null && sc.aoi_coverage_pct !== undefined && (
                      <div>
                        <strong className="text-slate-300">AOI Coverage:</strong>{' '}
                        {sc.aoi_coverage_pct}%
                      </div>
                    )}
                    <div>
                      <strong className="text-slate-300">Bands:</strong>{' '}
                      {(sc.assets || []).join(', ')}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-2">
            <Button
              type="button"
              variant="primary"
              className="w-full bg-[#0284C7] hover:bg-sky-500 text-white font-bold text-xs h-8"
              onClick={() => onApprovePlan?.(taskId)}
            >
              ✓ Approve & Stage Native-Resolution Images
            </Button>
            <div className="flex gap-2">
              <Input
                type="text"
                className="flex-1 h-8 text-[11.5px] bg-[#111827] border-[#1E293B]"
                placeholder="Or give feedback (e.g., 'cloudy, search July 2024 instead')…"
                value={revisionFeedback}
                onChange={(e) => setRevisionFeedback(e.target.value)}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs bg-[#1E293B] border border-[#334155]"
                onClick={() => {
                  if (!revisionFeedback.trim()) {
                    onNotify?.('Please enter feedback for the satellite search.', 'warning');
                    return;
                  }
                  onRevisePlan?.(taskId, revisionFeedback.trim());
                  setRevisionFeedback('');
                }}
              >
                Search Again
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 4. Plan Approval Gate */}
      {task.status === 'pending_approval' && (
        <div
          className="bg-[#0F172A] border border-[#1E293B] rounded-lg p-3.5"
          style={{ borderLeft: '4px solid #14B8A6' }}
        >
          <div className="flex justify-between items-center mb-2">
            <span className="flex items-center gap-1.5 text-[13px] font-semibold text-[#14B8A6]">
              <ClipboardList className="h-4 w-4 shrink-0" />
              <span>Plan Proposed — User Review Required</span>
            </span>
            <span className="font-mono text-[10.5px] text-slate-400">
              Autonomous container paused
            </span>
          </div>
          <div className="text-slate-200 text-xs mb-3">
            <MarkdownView content={task.plan || 'No plan details provided.'} />
          </div>
          <div className="flex flex-col gap-2">
            <Button
              type="button"
              variant="teal"
              className="w-full font-bold text-xs h-8"
              onClick={() => onApprovePlan?.(taskId)}
            >
              ✓ Approve Plan & Execute Analysis
            </Button>
            <div className="flex gap-2">
              <Input
                type="text"
                className="flex-1 h-8 text-[11.5px] bg-[#111827] border-[#1E293B]"
                placeholder="Request plan revisions (e.g., 'use threshold 0.25 and add confidence map')…"
                value={revisionFeedback}
                onChange={(e) => setRevisionFeedback(e.target.value)}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs bg-[#1E293B] border border-[#334155]"
                onClick={() => {
                  if (!revisionFeedback.trim()) {
                    onNotify?.('Please enter revision feedback.', 'warning');
                    return;
                  }
                  onRevisePlan?.(taskId, revisionFeedback.trim());
                  setRevisionFeedback('');
                }}
              >
                Send Revision
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 5. Findings / Summary Card */}
      {(task.answer || finalAnswer) && (
        <div className="bg-[#111827] border border-[#1E293B] rounded-lg p-3.5">
          <div className="flex items-center gap-2 mb-2.5">
            {isDone ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            ) : (
              <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
            )}
            <span className="font-bold text-[13px] text-slate-100">
              {isDone ? 'Analysis Complete — Findings & Evidence' : 'Task Failed — Details'}
            </span>
            {isDone && (
              <span className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full font-semibold font-mono">
                DONE
              </span>
            )}
          </div>
          <div className="max-h-[550px] overflow-y-auto text-slate-300 text-xs leading-relaxed">
            <MarkdownView content={task.answer || finalAnswer} />
          </div>
        </div>
      )}

      {/* 6. Time Series Animation & Synchronized Frame Viewer */}
      {hasTimeline && (
        <div className="bg-[#0F172A] rounded-lg p-3 border border-[#1E293B]">
          {(timelineFrame || gifArt) &&
            (() => {
              const frameFname =
                timelineFrame && timelineFrame.file ? getBasename(timelineFrame.file) : '';
              const matchingArt = frameFname
                ? artifacts.find(
                    (a) => getBasename(typeof a === 'string' ? a : a.name) === frameFname
                  )
                : null;
              const gifUrl = gifArt
                ? typeof gifArt === 'string'
                  ? `/runs/${gifArt}`
                  : gifArt.url
                : timelineFrame && timelineFrame.gif_url
                ? timelineFrame.gif_url
                : null;
              const initialSrc =
                matchingArt && typeof matchingArt === 'object' && matchingArt.url
                  ? matchingArt.url
                  : timelineFrame && timelineFrame.png_url
                  ? timelineFrame.png_url
                  : frameFname
                  ? `/api/tasks/${taskId}/artifacts/${frameFname}`
                  : gifUrl;

              if (!initialSrc) return null;

              return (
                <div className="text-center mb-2.5">
                  <div className="relative inline-block max-w-full">
                    <img
                      src={initialSrc}
                      alt="Time Series Frame"
                      className="max-h-[400px] max-w-full h-auto mx-auto rounded-md border border-[#334155] block"
                      onError={(e) => {
                        const imgEl = e.currentTarget;
                        if (imgEl.dataset.triedFallback === 'true') {
                          if (gifUrl && imgEl.src !== gifUrl) {
                            imgEl.dataset.triedFallback = 'gif';
                            imgEl.src = gifUrl;
                          }
                          return;
                        }
                        imgEl.dataset.triedFallback = 'true';
                        if (frameFname) {
                          const fbUrl = `/api/tasks/${taskId}/artifacts/${frameFname}`;
                          if (imgEl.src !== fbUrl) {
                            imgEl.src = fbUrl;
                            return;
                          }
                        }
                        if (gifUrl && imgEl.src !== gifUrl) {
                          imgEl.src = gifUrl;
                        }
                      }}
                    />
                    {timelineFrame && (timelineFrame.label || timelineFrame.date) && (
                      <div className="absolute bottom-2.5 left-3 bg-[#0F172A]/85 backdrop-blur-xs text-sky-400 px-2.5 py-1 rounded text-[11px] font-semibold font-mono border border-sky-400/30">
                        {timelineFrame.label || timelineFrame.date || ''}
                      </div>
                    )}
                  </div>
                </div>
              );
            })()}
          {renderTimeSeriesPanel?.({
            taskId,
            runDir: task.run_dir,
            onFrameChange: (frame) => setTimelineFrame(frame),
          })}
        </div>
      )}

      {/* 7. Generated Deliverables Section */}
      {artifacts.length > 0 && (
        <div className="bg-[#111827] border border-[#1E293B] rounded-lg p-3.5">
          <div className="flex items-center justify-between mb-2.5 flex-wrap gap-1.5">
            <span className="flex items-center gap-1.5 font-semibold text-xs text-slate-100">
              <Package className="h-4 w-4 text-sky-400 shrink-0" />
              <span>Generated Deliverables ({artifacts.length} files)</span>
            </span>
            <div className="flex items-center gap-1.5">
              {canShow3D && (
                <Button
                  type="button"
                  size="sm"
                  className="h-7 text-[11px] px-2.5 gap-1 text-white"
                  style={{ backgroundColor: isLidar ? '#047857' : '#0284C7' }}
                  onClick={handleOpen3D}
                  title={
                    isLidar
                      ? 'Open interactive 3D LiDAR Canopy & Structures Inspector'
                      : 'Open interactive 3D terrain viewer'
                  }
                >
                  {isLidar ? (
                    <>
                      <Trees className="h-3.5 w-3.5" />
                      <span>View 3D LiDAR & Canopy</span>
                    </>
                  ) : (
                    <>
                      <Mountain className="h-3.5 w-3.5" />
                      <span>View 3D Terrain</span>
                    </>
                  )}
                </Button>
              )}
              <Button
                type="button"
                size="sm"
                variant="teal"
                className="h-7 text-[11px] px-2.5 gap-1"
                onClick={() => onSwitchToGlobe?.()}
                title="View all outputs overlaid on the 3D Globe"
              >
                <Globe className="h-3.5 w-3.5" />
                <span>View on 3D Globe</span>
              </Button>
            </div>
          </div>

          {/* Embedded Elevation Cross-Section Chart if available */}
          {profileSvgArt && (
            <div className="mb-3 bg-[#0F172A] rounded-lg p-2.5 border border-[#1E293B] text-center">
              <img
                src={
                  typeof profileSvgArt === 'object' && profileSvgArt.url
                    ? profileSvgArt.url
                    : `/api/tasks/${taskId}/artifacts/${getBasename(
                        typeof profileSvgArt === 'string' ? profileSvgArt : profileSvgArt.name
                      )}`
                }
                alt="Elevation Cross-Section Profile"
                className="max-w-full h-auto block mx-auto rounded-md"
              />
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {artifacts.map((art, idx) => {
              const fname = typeof art === 'string' ? art : art.name || 'file';
              const artUrl = typeof art === 'string' ? null : art.url;
              const ext = fname.toLowerCase().split('.').pop() || '';
              const isTif = ext === 'tif' || ext === 'tiff';
              const isImg = ext === 'png' || ext === 'gif' || ext === 'webp' || ext === 'svg';
              const isPreviewable = isTif || isImg;
              const downloadUrl = artUrl || `/runs/${fname}`;

              return (
                <div
                  key={idx}
                  className="flex items-center gap-1.5 bg-[#0B0F17] border border-[#1E293B] px-2.5 py-1.5 rounded-md"
                >
                  {isTif ? (
                    <Map className="h-3.5 w-3.5 text-sky-400 shrink-0" />
                  ) : isImg ? (
                    <ImageIcon className="h-3.5 w-3.5 text-teal-400 shrink-0" />
                  ) : (
                    <FileText className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                  )}
                  <span
                    className="font-mono flex-1 min-w-0 truncate text-[11px] text-slate-200"
                    title={fname}
                  >
                    {getBasename(fname)}
                  </span>
                  <div className="shrink-0 flex items-center gap-1">
                    {isPreviewable ? (
                      <button
                        type="button"
                        className="bg-[#1E293B] text-sky-400 border border-[#334155] hover:border-sky-400 rounded text-[10px] px-1.5 py-0.5 cursor-pointer transition-colors"
                        onClick={() => onPreviewFile?.(art)}
                      >
                        Preview
                      </button>
                    ) : (
                      <a
                        href={downloadUrl}
                        download={getBasename(fname)}
                        className="bg-[#1E293B] text-slate-300 border border-[#334155] hover:text-white rounded text-[10px] px-1.5 py-0.5 no-underline inline-block"
                      >
                        Download
                      </a>
                    )}
                    {isTif && (
                      <button
                        type="button"
                        className="bg-[#0F766E] hover:bg-[#14B8A6] text-white rounded text-[10px] p-1 cursor-pointer transition-colors"
                        onClick={() => onSwitchToGlobe?.(art)}
                        title="Overlay on 3D Globe"
                      >
                        <Globe className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 8. Live Execution & Reasoning Activity Feed */}
      {relevantActivities.length > 0 && (
        <div className="bg-[#111827] border border-[#1E293B] rounded-lg p-3.5">
          <div className="flex items-center justify-between mb-2">
            <span className="flex items-center gap-1.5 font-semibold text-xs text-slate-200">
              <Microscope className="h-4 w-4 text-sky-400 shrink-0" />
              <span>Execution Log & Reasoning ({relevantActivities.length} events)</span>
            </span>
            <button
              type="button"
              className="text-[11px] bg-[#1E293B] text-slate-200 border border-[#334155] hover:border-slate-500 px-2 py-0.5 rounded cursor-pointer"
              onClick={() => setShowLogs(!showLogs)}
            >
              {showLogs ? 'Hide Events' : 'Show Events'}
            </button>
          </div>

          {showLogs && (
            <div className="relative mt-2.5">
              <div
                ref={activityRef}
                onWheel={handleWheel}
                onScroll={handleScroll}
                className="max-h-[540px] overflow-y-auto overflow-x-hidden flex flex-col gap-2 scroll-smooth"
                style={{ overscrollBehavior: 'contain' }}
              >
                {relevantActivities.map((act: ActivityItem, i: number) => {
                  // A. Claude Thinking Trace
                  if (act.type === 'thinking' && 'text' in act) {
                    const textStr = act.text || '';
                    const wordCount = textStr.trim()
                      ? textStr.trim().split(/\s+/).filter(Boolean).length
                      : 0;
                    const charCount = textStr.length;
                    const isLatestThinking =
                      task.status === 'running' && i === relevantActivities.length - 1;

                    return (
                      <details
                        key={i}
                        open={isLatestThinking || undefined}
                        className="border border-[#1E293B] rounded-md bg-[#090D14] px-3 py-2"
                      >
                        <summary className="font-mono text-[11px] cursor-pointer text-sky-400 font-semibold select-none flex items-center justify-between">
                          <span className="flex items-center gap-1.5">
                            <Brain className="h-3.5 w-3.5 shrink-0 inline text-teal-400" />
                            <span>
                              Reasoning trace ({wordCount} words · {charCount} chars)
                            </span>
                          </span>
                          <span className="text-[10px] text-slate-500 font-normal">
                            ↕ scrollable
                          </span>
                        </summary>
                        <div
                          className="font-mono whitespace-pre-wrap text-[11px] mt-2 text-slate-200 break-words max-h-[360px] overflow-y-auto p-3 bg-[#06090E] rounded border border-[#1E293B] leading-relaxed select-text"
                          style={{
                            borderLeft: '3px solid #0F766E',
                          }}
                        >
                          {textStr || 'Thinking…'}
                        </div>
                      </details>
                  );
                }

                // B. Assistant Markdown Text
                if (act.type === 'text' && 'text' in act) {
                  if (!act.text || !act.text.trim()) return null;
                  return (
                    <div
                      key={i}
                      className="px-2.5 py-1.5 bg-[#0B0F17] rounded-md border border-[#1E293B] text-slate-200 text-[11.5px]"
                    >
                      <MarkdownView content={act.text} />
                    </div>
                  );
                }

                // C. Tool Execution Card
                if (act.type === 'tool') {
                  const argsObj =
                    typeof act.args === 'object' && act.args !== null
                      ? (act.args as Record<string, unknown>)
                      : null;
                  const codeStr =
                    argsObj && typeof argsObj.code === 'string' ? argsObj.code : null;
                  const inputFilesList =
                    argsObj && Array.isArray(argsObj.input_files)
                      ? (argsObj.input_files as string[])
                      : null;
                  const isStacSearch = act.toolName === 'search_stac';
                  const isStacPropose = act.toolName === 'propose_stac_scenes';
                  const shortArgs =
                    !codeStr && !isStacSearch && !isStacPropose
                      ? typeof act.args === 'string'
                        ? act.args
                        : JSON.stringify(act.args || {})
                      : '';

                  const borderColor = act.running
                    ? '#38BDF8'
                    : act.ok
                    ? '#0F766E'
                    : '#EF4444';
                  const leftBorderColor = act.running
                    ? '#38BDF8'
                    : act.ok
                    ? '#10B981'
                    : '#EF4444';

                  return (
                    <div
                      key={i}
                      className="bg-[#0B0F17] rounded-md px-2.5 py-2"
                      style={{
                        border: `1px solid ${borderColor}`,
                        borderLeft: `3px solid ${leftBorderColor}`,
                      }}
                    >
                      <div className="flex items-center gap-2 text-[11.5px] flex-wrap">
                        <span className="font-mono font-semibold text-sky-400 flex items-center gap-1.5">
                          {isStacSearch || isStacPropose ? (
                            <Satellite className="h-3.5 w-3.5 shrink-0" />
                          ) : (
                            <Wrench className="h-3.5 w-3.5 shrink-0" />
                          )}
                          <span>
                            {isStacSearch
                              ? 'STAC Catalog Search (search_stac)'
                              : isStacPropose
                              ? 'Propose Satellite Previews (propose_stac_scenes)'
                              : act.toolName}
                          </span>
                        </span>
                        {act.attempt && (
                          <span className="font-mono text-[10px] bg-[#1E293B] text-slate-300 px-1.5 py-0.5 rounded">
                            att {act.attempt}
                            {act.max_attempts ? `/${act.max_attempts}` : ''}
                          </span>
                        )}
                        <span
                          className="font-mono ml-auto text-[10.5px] font-semibold"
                          style={{
                            color: act.running
                              ? '#38BDF8'
                              : act.ok
                              ? '#10B981'
                              : '#F87171',
                          }}
                        >
                          {act.running
                            ? isStacSearch
                              ? '⏳ querying Planetary Computer STAC…'
                              : '⏳ running in sandbox…'
                            : `${act.duration_s != null ? `${act.duration_s}s · ` : ''}exit ${
                                act.exit_code ?? '—'
                              }`}
                        </span>
                      </div>

                      {isStacSearch && argsObj && (
                        <div className="font-mono text-[10.5px] text-slate-300 mt-1.5 bg-[#05080E] px-2 py-1.5 rounded border border-[#1E293B] flex flex-wrap gap-2.5">
                          {Boolean(argsObj.location_name) && (
                            <span>
                              <strong>Location:</strong> {String(argsObj.location_name)}
                            </span>
                          )}
                          {Boolean(argsObj.collections) && (
                            <span>
                              <strong>Collections:</strong>{' '}
                              {Array.isArray(argsObj.collections)
                                ? argsObj.collections.join(', ')
                                : String(argsObj.collections)}
                            </span>
                          )}
                          {Boolean(argsObj.start_date || argsObj.end_date) && (
                            <span>
                              <strong>Dates:</strong> {String(argsObj.start_date || '…')} →{' '}
                              {String(argsObj.end_date || '…')}
                            </span>
                          )}
                          {Array.isArray(argsObj.bbox) && (
                            <span>
                              <strong>BBox:</strong> [
                              {argsObj.bbox.map((n) => Number(n).toFixed(3)).join(', ')}]
                            </span>
                          )}
                          {argsObj.max_cloud_cover != null && (
                            <span>
                              <strong>Max Cloud:</strong> {String(argsObj.max_cloud_cover)}%
                            </span>
                          )}
                        </div>
                      )}

                      {isStacPropose && argsObj && (
                        <div className="font-mono text-[10.5px] text-slate-300 mt-1.5 bg-[#05080E] px-2 py-1.5 rounded border border-[#1E293B]">
                          <div>
                            <strong>Location:</strong>{' '}
                            {String(argsObj.location_name || 'Target AOI')} •{' '}
                            <strong>Proposed Scenes:</strong>{' '}
                            {Array.isArray(argsObj.scenes) ? argsObj.scenes.length : 0}
                          </div>
                          {Array.isArray(argsObj.scenes) && argsObj.scenes.length > 0 && (
                            <div className="mt-1 text-slate-400 text-[10px]">
                              {argsObj.scenes
                                .map(
                                  (s: Record<string, unknown>) =>
                                    `${s.collection || 'STAC'} (${String(
                                      s.datetime || s.id || ''
                                    ).slice(0, 10)})`
                                )
                                .join(' · ')}
                            </div>
                          )}
                        </div>
                      )}

                      {inputFilesList && inputFilesList.length > 0 && (
                        <div className="font-mono text-[10px] text-slate-400 mt-1 flex items-center gap-1">
                          <FolderOpen className="h-3 w-3 shrink-0" />
                          <span>
                            Inputs ({inputFilesList.length}):{' '}
                            {inputFilesList.map(getBasename).slice(0, 6).join(', ')}
                            {inputFilesList.length > 6
                              ? ` +${inputFilesList.length - 6} more`
                              : ''}
                          </span>
                        </div>
                      )}

                      {codeStr && (
                        <details
                          open={act.running || undefined}
                          className="mt-1.5 text-[10.5px]"
                        >
                          <summary className="font-mono cursor-pointer text-[#14B8A6] font-semibold select-none flex items-center gap-1">
                            <Code2 className="h-3.5 w-3.5 shrink-0 inline" />
                            <span>
                              Agent Python Code ({codeStr.split('\n').length} lines)
                            </span>
                          </summary>
                          <pre className="font-mono mt-1 p-2 bg-[#05080E] border border-[#1E293B] rounded overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words max-h-[260px] text-[10px] text-slate-200">
                            {codeStr}
                          </pre>
                        </details>
                      )}

                      {shortArgs && (
                        <div className="font-mono text-[10.5px] text-slate-400 break-all mt-1">
                          {shortArgs.length > 260 ? `${shortArgs.slice(0, 257)}…` : shortArgs}
                        </div>
                      )}

                      {(act.error || act.stdout) && (
                        <details
                          open={act.ok === false || isStacSearch || undefined}
                          className="mt-1.5 text-[10.5px]"
                        >
                          <summary
                            className="font-mono cursor-pointer select-none"
                            style={{ color: act.ok === false ? '#FCA5A5' : '#94A3B8' }}
                          >
                            {isStacSearch ? '📄 STAC Search Results' : '📄 Output / Logs'}
                          </summary>
                          <pre
                            className="font-mono mt-1 px-2 py-1.5 bg-[#05080E] border border-[#1E293B] rounded overflow-x-auto overflow-y-auto whitespace-pre-wrap break-all max-h-[220px] max-w-full text-[10px]"
                            style={{ color: act.ok === false ? '#FECACA' : '#CBD5E1' }}
                          >
                            {act.error || act.stdout}
                          </pre>
                        </details>
                      )}
                    </div>
                  );
                }

                // D. STAC Band Download Card
                if (act.type === 'stac_download') {
                  const borderColor = act.running
                    ? '#38BDF8'
                    : act.ok
                    ? '#0F766E'
                    : '#EF4444';
                  const leftBorderColor = act.running
                    ? '#38BDF8'
                    : act.ok
                    ? '#10B981'
                    : '#EF4444';

                  return (
                    <div
                      key={i}
                      className="bg-[#0B0F17] rounded-md px-2.5 py-2"
                      style={{
                        border: `1px solid ${borderColor}`,
                        borderLeft: `3px solid ${leftBorderColor}`,
                      }}
                    >
                      <div className="flex items-center gap-2 text-[11.5px] flex-wrap">
                        <span className="font-mono font-semibold text-sky-400 flex items-center gap-1.5">
                          <Download className="h-3.5 w-3.5 shrink-0" />
                          <span>
                            {act.running
                              ? 'Downloading STAC Band:'
                              : act.ok
                              ? 'Staged STAC Band:'
                              : 'STAC Download Failed:'}{' '}
                            {act.filename}
                          </span>
                        </span>
                        <span
                          className="font-mono ml-auto text-[10.5px] font-semibold"
                          style={{
                            color: act.running
                              ? '#38BDF8'
                              : act.ok
                              ? '#10B981'
                              : '#F87171',
                          }}
                        >
                          {act.running
                            ? '⏳ Cropping & downloading at 100% native resolution…'
                            : act.ok
                            ? `${act.size_mb != null ? `${act.size_mb} MB · ` : ''}${
                                act.duration_s != null ? `${act.duration_s}s` : 'done'
                              }`
                            : act.error || 'failed'}
                        </span>
                      </div>
                      {(act.collection || act.asset_key || act.width) && (
                        <div className="font-mono text-[10px] text-slate-400 mt-1 flex flex-wrap gap-2.5">
                          {act.collection && (
                            <span>
                              <strong>Collection:</strong> {act.collection}
                            </span>
                          )}
                          {act.asset_key && (
                            <span>
                              <strong>Band:</strong> {act.asset_key}
                            </span>
                          )}
                          {act.date && (
                            <span>
                              <strong>Date:</strong> {act.date}
                            </span>
                          )}
                          {act.width && act.height && (
                            <span>
                              <strong>Grid:</strong> {act.width}×{act.height} px
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                }

                // E. STAC Staged Summary
                if (act.type === 'stac_staged' && 'files' in act) {
                  const stagedList = act.files || [];
                  return (
                    <div
                      key={i}
                      className="bg-[#0B1320] rounded-md px-2.5 py-2"
                      style={{
                        border: '1px solid #0F766E',
                        borderLeft: '3px solid #10B981',
                      }}
                    >
                      <div className="font-mono font-semibold text-[11.5px] text-emerald-400 flex items-center gap-1.5">
                        <Inbox className="h-3.5 w-3.5 shrink-0" />
                        <span>
                          Staged {stagedList.length} Native-Resolution GeoTIFFs to Workspace
                        </span>
                      </div>
                      {stagedList.length > 0 && (
                        <div className="font-mono text-[10px] text-slate-300 mt-1 leading-relaxed">
                          {stagedList.map(getBasename).join(', ')}
                        </div>
                      )}
                    </div>
                  );
                }

                // F. STAC Preview Ready Event Card
                if (act.type === 'stac_preview_ready' && 'preview' in act) {
                  const scCount =
                    act.preview && Array.isArray(act.preview.scenes)
                      ? act.preview.scenes.length
                      : 0;
                  return (
                    <div
                      key={i}
                      className="bg-[#0B1120] rounded-md px-2.5 py-2"
                      style={{
                        border: '1px solid #0284C7',
                        borderLeft: '3px solid #38BDF8',
                      }}
                    >
                      <div className="font-mono font-semibold text-[11.5px] text-sky-400 flex items-center gap-1.5">
                        <Satellite className="h-3.5 w-3.5 shrink-0" />
                        <span>
                          STAC Satellite Previews Ready ({scCount} scene
                          {scCount === 1 ? '' : 's'} proposed for review)
                        </span>
                      </div>
                    </div>
                  );
                }

                // G. Vision Check Status Card
                if (act.type === 'vision_check' && 'image' in act) {
                  const imgName = getBasename(act.image) || 'image';
                  const isStarted = act.state === 'started';
                  const isOk = act.verdict === 'ok';
                  const isBad =
                    act.verdict === 'needs_revision' ||
                    act.verdict === 'not_verified' ||
                    act.verdict === 'insufficient_data';

                  if (isStarted) {
                    return (
                      <div
                        key={i}
                        className="px-2 py-1.5 mt-1 bg-[#0B0F17] rounded"
                        style={{ borderLeft: '3px solid #3B82F6' }}
                      >
                        <div className="flex items-center gap-2 text-[11px] text-sky-400">
                          <Eye className="h-3.5 w-3.5 shrink-0" />
                          <span className="font-mono font-semibold">
                            Starting Visual QA: {imgName}
                          </span>
                          {act.index && act.total && (
                            <span className="font-mono ml-auto text-[10.5px] text-slate-400">
                              {act.index} / {act.total}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div
                      key={i}
                      className="px-2 py-1.5 bg-[#0B0F17] border border-[#1E293B] rounded"
                    >
                      <div className="flex items-center gap-2 text-[11px]">
                        <Eye className="h-3.5 w-3.5 text-slate-300 shrink-0" />
                        <span className="font-mono font-semibold text-slate-200">
                          Visual QA: {imgName}
                        </span>
                        <span
                          className="font-mono ml-auto text-[10.5px] font-semibold"
                          style={{
                            color: isOk ? '#10B981' : isBad ? '#EF4444' : '#F59E0B',
                          }}
                        >
                          {act.verdict || 'checking…'}
                        </span>
                      </div>
                      {act.text && act.text !== 'ok' && (
                        <div className="text-[10.5px] text-slate-300 mt-1 whitespace-pre-wrap break-words">
                          {act.text}
                        </div>
                      )}
                    </div>
                  );
                }

                // H. All other vision_* events delegated to ValidationViewer
                if (act.type && act.type.startsWith('vision_')) {
                  return <ValidationViewer key={i} activity={act} />;
                }

                return null;
              })}
            </div>

              {/* Floating Jump to Bottom Pill when user scrolled up during active stream */}
              {showScrollBottomBtn && task.status === 'running' && (
                <button
                  type="button"
                  onClick={scrollToBottom}
                  className="absolute bottom-2.5 right-4 z-10 flex items-center gap-1.5 px-3 py-1 rounded-full bg-sky-600/90 hover:bg-sky-500 text-white text-[11px] font-medium shadow-lg backdrop-blur-sm transition-all duration-150 animate-in fade-in slide-in-from-bottom-2 cursor-pointer border border-sky-400/30"
                >
                  <ArrowDown className="h-3.5 w-3.5 animate-bounce" />
                  <span>Resume auto-scroll</span>
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

