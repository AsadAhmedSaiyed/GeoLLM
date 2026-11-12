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
    const name = getBasename(typeof a === 'string' ? a : a.name || '').toLowerCase();
    return name === 'terrain_3d.json' || name === 'lidar_3d.json';
  });

  const lidarPattern = /\b(lidar|chm|canopy_height|autzen)\b|\.(las|laz)$/i;
  const isLidar =
    artifacts.some((a) => {
      const name = typeof a === 'string' ? a : a.name || '';
      return lidarPattern.test(name);
    }) ||
    (task.files || []).some((f) => lidarPattern.test(f || '')) ||
    /\b(lidar|canopy height|point cloud)\b/i.test(task.question || '');

  const canShow3D = Boolean(terrain3dArt);

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

  const stacStagingSummary = useMemo(() => {
    type StacDlItem = Extract<ActivityItem, { type: 'stac_download' }>;
    const downloads = relevantActivities.filter(
      (a): a is StacDlItem => a.type === 'stac_download'
    );
    const stagedItem = relevantActivities.find(
      (a): a is Extract<ActivityItem, { type: 'stac_staged' }> => a.type === 'stac_staged'
    );
    const firstStacIndex = relevantActivities.findIndex(
      (a) => a.type === 'stac_download' || a.type === 'stac_staged'
    );

    const totalBands = Math.max(
      downloads.length,
      stagedItem?.files?.length || 0,
      ...downloads.map((d) => d.total_bands || 0)
    );
    const doneDownloads = downloads.filter((d) => !d.running && d.ok);
    const failedDownloads = downloads.filter((d) => !d.running && d.ok === false);
    const activeDownload = downloads.find((d) => d.running) || null;
    const totalSizeMb = Math.round(
      doneDownloads.reduce((sum, d) => sum + (Number(d.size_mb) || 0), 0) * 10
    ) / 10;
    const totalDurationS = Math.round(
      doneDownloads.reduce((sum, d) => sum + (Number(d.duration_s) || 0), 0) * 10
    ) / 10;

    // Group bands by collection + date
    interface StacSceneGroup {
      key: string;
      label: string;
      bands: string[];
      sizeMb: number;
      durationS: number;
      allOk: boolean;
    }
    const sceneMap: Record<string, StacSceneGroup> = {};
    for (const d of downloads) {
      const dateStr = d.date || 'scene';
      const colStr = d.collection || 'STAC';
      const key = `${colStr}_${dateStr}`;
      const existing = sceneMap[key];
      if (existing) {
        if (d.asset_key) existing.bands.push(d.asset_key);
        existing.sizeMb = Math.round((existing.sizeMb + (Number(d.size_mb) || 0)) * 100) / 100;
        existing.durationS = Math.round((existing.durationS + (Number(d.duration_s) || 0)) * 10) / 10;
        existing.allOk = existing.allOk && d.ok !== false;
      } else {
        sceneMap[key] = {
          key,
          label: `${colStr} (${dateStr})`,
          bands: d.asset_key ? [d.asset_key] : [],
          sizeMb: Math.round((Number(d.size_mb) || 0) * 100) / 100,
          durationS: Math.round((Number(d.duration_s) || 0) * 10) / 10,
          allOk: d.ok !== false,
        };
      }
    }

    const isStagingActive =
      Boolean(activeDownload) ||
      (!stagedItem &&
        task.status === 'running' &&
        totalBands > 0 &&
        doneDownloads.length + failedDownloads.length < totalBands);

    const overallPct = isStagingActive
      ? activeDownload?.overall_pct ??
        Math.round((doneDownloads.length / Math.max(1, totalBands)) * 100)
      : 100;

    return {
      firstStacIndex,
      downloads,
      stagedFiles: stagedItem?.files || [],
      totalBands,
      doneCount: stagedItem && doneDownloads.length === 0 ? stagedItem.files.length : doneDownloads.length,
      failedDownloads,
      activeDownload,
      totalSizeMb,
      totalDurationS,
      scenes: Object.values(sceneMap),
      isStagingActive,
      overallPct,
    };
  }, [relevantActivities, task.status]);

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
      <div className="bg-muted border border-border rounded-none p-3">
        <div className="flex items-center gap-2.5">
          <span className="font-mono bg-[#0F766E] text-white px-2 py-0.5 rounded-none text-[11px] font-bold shrink-0">
            #{taskNum}
          </span>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-[13px] text-foreground break-words">
              {task.question ? task.question : `Sandbox Slot #${taskNum} (Idle)`}
            </div>
            <div className="font-mono text-[11px] text-muted-foreground mt-0.5">
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
              className="h-7 px-2.5 text-[11px] bg-muted border border-border text-foreground hover:text-white hover:border-slate-400 shrink-0 gap-1 cursor-pointer"
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
          className="bg-card border border-border rounded-none p-3.5"
          style={{ borderLeft: '4px solid #0284C7' }}
        >
          <div className="flex justify-between items-center mb-2.5 flex-wrap gap-1.5">
            <span className="flex items-center gap-1.5 text-[13px] font-bold text-sky-400">
              <Satellite className="h-4 w-4 shrink-0" />
              <span>Satellite Scene Previews — Review Before Native-Resolution Staging</span>
            </span>
            <span className="font-mono text-[10.5px] text-sky-400 bg-sky-500/15 px-2 py-0.5 rounded-none border border-sky-500/30">
              100% Native Resolution Preserved
            </span>
          </div>

          {task.stacPreview.explanation && (
            <div className="text-xs text-foreground mb-2.5 leading-relaxed">
              <MarkdownView content={task.stacPreview.explanation} />
            </div>
          )}

          <div className="font-mono text-[11px] text-muted-foreground bg-muted px-2.5 py-2 rounded-none mb-3 flex flex-wrap gap-3.5">
            <span>
              <strong className="text-foreground">Location:</strong>{' '}
              {task.stacPreview.location_name || 'Custom AOI'}
            </span>
            {task.stacPreview.bbox && (
              <span>
                <strong className="text-foreground">BBox:</strong> [
                {task.stacPreview.bbox.map((n) => Number(n).toFixed(4)).join(', ')}]
              </span>
            )}
            {task.stacPreview.native_grid_estimate && (
              <span>
                <strong className="text-foreground">Native Grid:</strong> ~
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
                className="bg-muted border border-border rounded-none overflow-hidden"
              >
                {sc.thumbnail ? (
                  <div className="bg-background text-center h-[140px] flex items-center justify-center overflow-hidden">
                    <img
                      src={sc.thumbnail}
                      alt={sc.label || sc.id || `Scene ${idx + 1}`}
                      className="max-h-[140px] max-w-full object-contain"
                    />
                  </div>
                ) : (
                  <div className="font-mono h-[100px] bg-background text-muted-foreground flex items-center justify-center text-[11px]">
                    No preview thumbnail
                  </div>
                )}
                <div className="p-2 text-[11px]">
                  <div className="font-bold text-foreground mb-1">
                    {sc.label || `Scene ${idx + 1}`}
                  </div>
                  <div className="font-mono text-[10px] text-muted-foreground leading-relaxed space-y-0.5">
                    <div>
                      <strong className="text-foreground">Collection:</strong> {sc.collection}
                    </div>
                    <div>
                      <strong className="text-foreground">Date:</strong>{' '}
                      {(sc.datetime || '').slice(0, 10) || 'N/A'}
                    </div>
                    {sc.cloud_cover !== null && sc.cloud_cover !== undefined && (
                      <div>
                        <strong className="text-foreground">Cloud Cover:</strong> {sc.cloud_cover}%
                      </div>
                    )}
                    {sc.aoi_coverage_pct !== null && sc.aoi_coverage_pct !== undefined && (
                      <div>
                        <strong className="text-foreground">AOI Coverage:</strong>{' '}
                        {sc.aoi_coverage_pct}%
                      </div>
                    )}
                    <div>
                      <strong className="text-foreground">Bands:</strong>{' '}
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
                className="flex-1 h-8 text-[11.5px] bg-muted border-border"
                placeholder="Or give feedback (e.g., 'cloudy, search July 2024 instead')…"
                value={revisionFeedback}
                onChange={(e) => setRevisionFeedback(e.target.value)}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs bg-muted border border-border"
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
          className="bg-card border border-border rounded-none p-3.5"
          style={{ borderLeft: '4px solid #14B8A6' }}
        >
          <div className="flex justify-between items-center mb-2">
            <span className="flex items-center gap-1.5 text-[13px] font-semibold text-[#14B8A6]">
              <ClipboardList className="h-4 w-4 shrink-0" />
              <span>Plan Proposed — User Review Required</span>
            </span>
            <span className="font-mono text-[10.5px] text-muted-foreground">
              Autonomous container paused
            </span>
          </div>
          <div className="text-foreground text-xs mb-3">
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
                className="flex-1 h-8 text-[11.5px] bg-muted border-border"
                placeholder="Request plan revisions (e.g., 'use threshold 0.25 and add confidence map')…"
                value={revisionFeedback}
                onChange={(e) => setRevisionFeedback(e.target.value)}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="h-8 px-3 text-xs bg-muted border border-border"
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
        <div className="bg-muted border border-border rounded-none p-3.5">
          <div className="flex items-center gap-2 mb-2.5">
            {isDone ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            ) : (
              <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
            )}
            <span className="font-bold text-[13px] text-foreground">
              {isDone ? 'Analysis Complete — Findings & Evidence' : 'Task Failed — Details'}
            </span>
            {isDone && (
              <span className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-none font-semibold font-mono">
                DONE
              </span>
            )}
          </div>
          <div className="max-h-[550px] overflow-y-auto text-foreground text-xs leading-relaxed">
            <MarkdownView content={task.answer || finalAnswer} />
          </div>
        </div>
      )}

      {/* 6. Time Series Animation & Synchronized Frame Viewer */}
      {hasTimeline && (
        <div className="bg-card rounded-none p-3 border border-border">
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
                      className="max-h-[400px] max-w-full h-auto mx-auto rounded-none border border-border block"
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
                      <div className="absolute bottom-2.5 left-3 bg-card/85 backdrop-blur-xs text-sky-400 px-2.5 py-1 rounded-none text-[11px] font-semibold font-mono border border-sky-400/30">
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
        <div className="bg-muted border border-border rounded-none p-3.5">
          <div className="flex items-center justify-between mb-2.5 flex-wrap gap-1.5">
            <span className="flex items-center gap-1.5 font-semibold text-xs text-foreground">
              <Package className="h-4 w-4 text-sky-400 shrink-0" />
              <span>Generated Deliverables ({artifacts.length} files)</span>
            </span>
            {canShow3D && (
              <div className="flex items-center gap-1.5">
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
              </div>
            )}
          </div>

          {/* Embedded Elevation Cross-Section Chart if available */}
          {profileSvgArt && (
            <div className="mb-3 bg-card rounded-none p-2.5 border border-border text-center">
              <img
                src={
                  typeof profileSvgArt === 'object' && profileSvgArt.url
                    ? profileSvgArt.url
                    : `/api/tasks/${taskId}/artifacts/${getBasename(
                        typeof profileSvgArt === 'string' ? profileSvgArt : profileSvgArt.name
                      )}`
                }
                alt="Elevation Cross-Section Profile"
                className="max-w-full h-auto block mx-auto rounded-none"
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
                  className="flex items-center gap-1.5 bg-card border border-border px-2.5 py-1.5 rounded-none"
                >
                  {isTif ? (
                    <Map className="h-3.5 w-3.5 text-sky-400 shrink-0" />
                  ) : isImg ? (
                    <ImageIcon className="h-3.5 w-3.5 text-teal-400 shrink-0" />
                  ) : (
                    <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  )}
                  <span
                    className="font-mono flex-1 min-w-0 truncate text-[11px] text-foreground"
                    title={fname}
                  >
                    {getBasename(fname)}
                  </span>
                  <div className="shrink-0 flex items-center gap-1">
                    {isPreviewable ? (
                      <button
                        type="button"
                        className="bg-muted text-sky-400 border border-border hover:border-sky-400 rounded-none text-[10px] px-1.5 py-0.5 cursor-pointer transition-colors"
                        onClick={() => onPreviewFile?.(art)}
                      >
                        Preview
                      </button>
                    ) : (
                      <a
                        href={downloadUrl}
                        download={getBasename(fname)}
                        className="bg-muted text-foreground border border-border hover:text-white rounded-none text-[10px] px-1.5 py-0.5 no-underline inline-block"
                      >
                        Download
                      </a>
                    )}
                    {isTif && (
                      <button
                        type="button"
                        className="bg-[#0F766E] hover:bg-[#14B8A6] text-white rounded-none text-[10px] p-1 cursor-pointer transition-colors"
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
        <div className="bg-muted border border-border rounded-none p-3.5">
          <div className="flex items-center justify-between mb-2">
            <span className="flex items-center gap-1.5 font-semibold text-xs text-foreground">
              <Microscope className="h-4 w-4 text-sky-400 shrink-0" />
              <span>Execution Log & Reasoning ({relevantActivities.length} events)</span>
            </span>
            <button
              type="button"
              className="text-[11px] bg-muted text-foreground border border-border hover:border-border px-2 py-0.5 rounded-none cursor-pointer"
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

                    return (
                      <details
                        key={i}
                        className="border border-border rounded-none bg-background px-3 py-2"
                      >
                        <summary className="font-mono text-[11px] cursor-pointer text-sky-400 font-semibold select-none flex items-center justify-between">
                          <span className="flex items-center gap-1.5">
                            <Brain className="h-3.5 w-3.5 shrink-0 inline text-teal-400" />
                            <span>
                              Reasoning trace ({wordCount} words · {charCount} chars)
                            </span>
                          </span>
                          <span className="text-[10px] text-muted-foreground font-normal">
                            ↕ scrollable
                          </span>
                        </summary>
                        <div
                          className="font-mono whitespace-pre-wrap text-[11px] mt-2 text-foreground break-words max-h-[360px] overflow-y-auto p-3 bg-background rounded-none border border-border leading-relaxed select-text"
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
                      className="px-2.5 py-1.5 bg-card rounded-none border border-border text-foreground text-[11.5px]"
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
                      className="bg-card rounded-none px-2.5 py-2"
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
                        {(act.code_attempt || act.attempt) && (() => {
                          const isCodeTool =
                            act.toolName === 'run_geospatial_code' ||
                            act.toolName === 'run_sandbox_python_code';
                          const shownAtt = isCodeTool
                            ? act.code_attempt || act.attempt
                            : act.attempt;
                          if (!shownAtt) return null;
                          const label = isCodeTool
                            ? act.max_attempts
                              ? shownAtt <= act.max_attempts
                                ? `att ${shownAtt}/${act.max_attempts}`
                                : `fix #${shownAtt - act.max_attempts}`
                              : `att ${shownAtt}`
                            : `step #${shownAtt}`;
                          return (
                            <span className="font-mono text-[10px] bg-muted text-foreground px-1.5 py-0.5 rounded-none">
                              {label}
                            </span>
                          );
                        })()}
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
                        <div className="font-mono text-[10.5px] text-foreground mt-1.5 bg-background px-2 py-1.5 rounded-none border border-border flex flex-wrap gap-2.5">
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
                        <div className="font-mono text-[10.5px] text-foreground mt-1.5 bg-background px-2 py-1.5 rounded-none border border-border">
                          <div>
                            <strong>Location:</strong>{' '}
                            {String(argsObj.location_name || 'Target AOI')} •{' '}
                            <strong>Proposed Scenes:</strong>{' '}
                            {Array.isArray(argsObj.scenes) ? argsObj.scenes.length : 0}
                          </div>
                          {Array.isArray(argsObj.scenes) && argsObj.scenes.length > 0 && (
                            <div className="mt-1 text-muted-foreground text-[10px]">
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
                        <div className="font-mono text-[10px] text-muted-foreground mt-1 flex items-center gap-1">
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
                        <details className="mt-1.5 text-[10.5px]">
                          <summary className="font-mono cursor-pointer text-[#14B8A6] font-semibold select-none flex items-center gap-1">
                            <Code2 className="h-3.5 w-3.5 shrink-0 inline" />
                            <span>
                              Agent Python Code ({codeStr.split('\n').length} lines)
                            </span>
                          </summary>
                          <pre className="font-mono mt-1 p-2 bg-background border border-border rounded-none overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words max-h-[260px] text-[10px] text-foreground">
                            {codeStr}
                          </pre>
                        </details>
                      )}

                      {shortArgs && (
                        <div className="font-mono text-[10.5px] text-muted-foreground break-all mt-1">
                          {shortArgs.length > 260 ? `${shortArgs.slice(0, 257)}…` : shortArgs}
                        </div>
                      )}

                      {(act.error || act.stdout) && (
                        <details
                          open={act.ok === false || undefined}
                          className="mt-1.5 text-[10.5px]"
                        >
                          <summary
                            className="font-mono cursor-pointer select-none"
                            style={{ color: act.ok === false ? '#FCA5A5' : '#94A3B8' }}
                          >
                            {isStacSearch ? '📄 STAC Search Results' : '📄 Output / Logs'}
                          </summary>
                          <pre
                            className="font-mono mt-1 px-2 py-1.5 bg-background border border-border rounded-none overflow-x-auto overflow-y-auto whitespace-pre-wrap break-all max-h-[220px] max-w-full text-[10px]"
                            style={{ color: act.ok === false ? '#FECACA' : '#CBD5E1' }}
                          >
                            {act.error || act.stdout}
                          </pre>
                        </details>
                      )}
                    </div>
                  );
                }

                // D. Unified STAC Satellite Imagery Staging Card (real-time progress + auto-collapsing summary)
                if (act.type === 'stac_download' || act.type === 'stac_staged') {
                  if (i !== stacStagingSummary.firstStacIndex) {
                    return null;
                  }
                  const {
                    totalBands,
                    doneCount,
                    failedDownloads,
                    activeDownload,
                    totalSizeMb,
                    totalDurationS,
                    scenes,
                    isStagingActive,
                    overallPct,
                    stagedFiles,
                  } = stacStagingSummary;
                  const hasFailure = failedDownloads.length > 0 && !isStagingActive;
                  const borderColor = isStagingActive
                    ? '#38BDF8'
                    : hasFailure
                    ? '#EF4444'
                    : '#0F766E';
                  const leftBorderColor = isStagingActive
                    ? '#38BDF8'
                    : hasFailure
                    ? '#EF4444'
                    : '#10B981';

                  return (
                    <div
                      key="stac-staging-unified"
                      className="bg-card rounded-none p-3 text-foreground"
                      style={{
                        border: `1px solid ${borderColor}`,
                        borderLeft: `4px solid ${leftBorderColor}`,
                      }}
                    >
                      <div className="flex items-center gap-2 text-xs font-bold mb-1">
                        <Download
                          className={`h-4 w-4 shrink-0 ${
                            isStagingActive
                              ? 'text-sky-400 animate-pulse'
                              : hasFailure
                              ? 'text-rose-400'
                              : 'text-emerald-400'
                          }`}
                        />
                        <span>
                          {isStagingActive
                            ? 'Staging Satellite Imagery'
                            : 'Satellite Imagery Staged'}
                        </span>
                        <span className="font-mono text-[10.5px] text-muted-foreground font-medium">
                          ({doneCount}/{totalBands || stagedFiles.length} bands)
                        </span>
                        <span
                          className="ml-auto font-mono text-[10px] px-2 py-0.5 rounded-none font-bold uppercase"
                          style={{
                            background: isStagingActive
                              ? 'rgba(56, 189, 248, 0.15)'
                              : hasFailure
                              ? 'rgba(239, 68, 68, 0.15)'
                              : 'rgba(16, 185, 129, 0.15)',
                            color: isStagingActive
                              ? '#38BDF8'
                              : hasFailure
                              ? '#FCA5A5'
                              : '#34D399',
                          }}
                        >
                          {isStagingActive
                            ? `${overallPct}%`
                            : hasFailure
                            ? 'PARTIAL'
                            : 'STAGED'}
                        </span>
                      </div>

                      {/* Real-time active download progress bar */}
                      {isStagingActive ? (
                        <div className="mt-1.5 space-y-1.5">
                          <div className="w-full h-1.5 bg-muted overflow-hidden">
                            <div
                              className="h-full bg-sky-400 transition-all duration-300"
                              style={{ width: `${Math.max(4, Math.min(100, overallPct))}%` }}
                            />
                          </div>
                          {activeDownload && (
                            <div className="font-mono text-[10.5px] text-muted-foreground flex items-center justify-between gap-2">
                              <span className="truncate text-sky-400">
                                {activeDownload.filename}
                              </span>
                              <span className="shrink-0">
                                {activeDownload.band_pct != null
                                  ? `${activeDownload.band_pct}%`
                                  : 'reading…'}
                                {activeDownload.elapsed_s != null
                                  ? ` · ${activeDownload.elapsed_s}s`
                                  : ''}
                              </span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="font-mono text-[10.5px] text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5">
                          <span>
                            <strong className={hasFailure ? 'text-rose-400' : 'text-emerald-400'}>
                              {doneCount}/{totalBands || stagedFiles.length}
                            </strong>{' '}
                            staged
                          </span>
                          {totalSizeMb > 0 && (
                            <span>
                              Size: <strong className="text-foreground">{totalSizeMb} MB</strong>
                            </span>
                          )}
                          {totalDurationS > 0 && (
                            <span>
                              Time:{' '}
                              <strong className="text-foreground">
                                {totalDurationS >= 60
                                  ? `${Math.floor(totalDurationS / 60)}m ${Math.round(totalDurationS % 60)}s`
                                  : `${totalDurationS}s`}
                              </strong>
                            </span>
                          )}
                          {scenes.length > 0 && (
                            <span>
                              Scenes: <strong className="text-foreground">{scenes.length}</strong>
                            </span>
                          )}
                        </div>
                      )}

                      {/* Immediately surface failed bands if any */}
                      {failedDownloads.length > 0 && (
                        <div className="mt-2 space-y-1">
                          {failedDownloads.map((fd) => (
                            <div
                              key={fd.filename}
                              className="text-[11px] border border-rose-500/40 bg-rose-500/10 px-2 py-1 font-mono flex justify-between gap-2"
                            >
                              <span className="truncate text-foreground">{fd.filename}</span>
                              <span className="text-rose-400 shrink-0">{fd.error || 'failed'}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Collapsed Details Dropdown (Grouped by Scene/Date) */}
                      {(scenes.length > 0 || stagedFiles.length > 0) && (
                        <details className="mt-2 text-[10.5px]">
                          <summary className="font-mono cursor-pointer text-muted-foreground hover:text-foreground select-none">
                            Details ({scenes.length > 0 ? `${scenes.length} scene${scenes.length === 1 ? '' : 's'}` : `${stagedFiles.length} files`})
                          </summary>
                          <div className="mt-1.5 border-t border-border pt-1 space-y-1 max-h-[240px] overflow-y-auto">
                            {scenes.length > 0
                              ? scenes.map((sc) => (
                                  <div
                                    key={sc.key}
                                    className="text-[11px] text-foreground border-b border-border/60 last:border-none pb-1.5 pt-1"
                                  >
                                    <div className="flex justify-between items-center gap-2">
                                      <span className="font-mono font-semibold text-foreground truncate">
                                        {sc.label}
                                        {sc.bands.length > 0 && (
                                          <span className="text-muted-foreground font-normal ml-1.5">
                                            ({sc.bands.length} bands: {sc.bands.join(', ')})
                                          </span>
                                        )}
                                      </span>
                                      <span
                                        className="font-mono font-bold text-[10.5px] shrink-0"
                                        style={{ color: sc.allOk ? '#34D399' : '#F87171' }}
                                      >
                                        {sc.allOk ? 'STAGED' : 'ERROR'}
                                      </span>
                                    </div>
                                    <div className="flex gap-4 mt-0.5 text-muted-foreground font-mono text-[10px]">
                                      <span>Size: {sc.sizeMb} MB</span>
                                      <span>Duration: {sc.durationS}s</span>
                                    </div>
                                  </div>
                                ))
                              : stagedFiles.map((sf) => (
                                  <div key={sf} className="font-mono text-[10.5px] text-foreground py-0.5 truncate">
                                    {getBasename(sf)}
                                  </div>
                                ))}
                          </div>
                        </details>
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
                      className="bg-muted rounded-none px-2.5 py-2"
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
                        className="px-2 py-1.5 mt-1 bg-card rounded-none"
                        style={{ borderLeft: '3px solid #3B82F6' }}
                      >
                        <div className="flex items-center gap-2 text-[11px] text-sky-400">
                          <Eye className="h-3.5 w-3.5 shrink-0" />
                          <span className="font-mono font-semibold">
                            Starting Visual QA: {imgName}
                          </span>
                          {act.index && act.total && (
                            <span className="font-mono ml-auto text-[10.5px] text-muted-foreground">
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
                      className="px-2 py-1.5 bg-card border border-border rounded-none"
                    >
                      <div className="flex items-center gap-2 text-[11px]">
                        <Eye className="h-3.5 w-3.5 text-foreground shrink-0" />
                        <span className="font-mono font-semibold text-foreground">
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
                        <div className="text-[10.5px] text-foreground mt-1 whitespace-pre-wrap break-words">
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
                  className="absolute bottom-2.5 right-4 z-10 flex items-center gap-1.5 px-3 py-1 rounded-none bg-sky-600/90 hover:bg-sky-500 text-white text-[11px] font-medium shadow-lg backdrop-blur-sm transition-all duration-150 animate-in fade-in slide-in-from-bottom-2 cursor-pointer border border-sky-400/30"
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

