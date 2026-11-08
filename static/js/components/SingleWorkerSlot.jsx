// GeoLLM Single Worker Workbench Slot (React 18 JSX Component)
import React, { useState, useRef, useEffect } from 'https://esm.sh/react@18.2.0';
import { MarkdownView } from './MarkdownView.js?v=20261107_v4';
import { TimeSeriesPanel } from './TimeSeriesPanel.js?v=20261107_v4';
import { Terrain3DViewer } from './Terrain3DViewer.js?v=20261107_v4';
import { ValidationViewer } from './ValidationViewer.js?v=20261107_v4';

const getBasename = (p) => (p || '').replace(/\\/g, '/').split('/').pop();

export function SingleWorkerSlot({
  taskId,
  task = {},
  onApprovePlan,
  onRevisePlan,
  onCancelTask,
  onPreviewFile,
  onSwitchToGlobe,
  onNotify,
}) {
  const [revisionFeedback, setRevisionFeedback] = useState('');
  const [showLogs, setShowLogs] = useState(true);
  const [timelineFrame, setTimelineFrame] = useState(null);
  const [showTerrain3D, setShowTerrain3D] = useState(false);
  const activityRef = useRef(null);
  const isUserScrolledUp = useRef(false);

  const handleScroll = (e) => {
    const el = e.currentTarget;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isUserScrolledUp.current = distanceToBottom > 60;
  };

  // Auto-scroll activity feed to bottom as new events arrive, only if user hasn't scrolled up
  useEffect(() => {
    if (activityRef.current && showLogs && !isUserScrolledUp.current) {
      activityRef.current.scrollTop = activityRef.current.scrollHeight;
    }
  }, [task.activities, showLogs]);

  const taskNum = taskId ? taskId.replace('task_', '') : '1';

  const formatSeconds = (t) => {
    if (!t || t.status === 'idle') return 'Not started';
    if (!t.elapsed) return '00:00';
    const total = Math.floor(t.elapsed);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const statusLabel =
    task.status === 'running' ? (task.step || 'Running…') :
    task.status === 'pending_stac_approval' ? 'STAC Satellite Preview Pending Review' :
    task.status === 'pending_approval' ? 'Plan Pending Approval' :
    task.status === 'done' ? 'Completed' :
    task.status === 'failed' ? (task.error || 'Failed') : 'Idle';

  const inputGateActivity = (task.activities || []).slice().reverse().find(a => a.type === 'vision_input_gate');
  const artifacts = task.artifacts || [];
  const gifArt = artifacts.find(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return name.toLowerCase().endsWith('.gif');
  });
  const hasTimeline = artifacts.some(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return name.toLowerCase().includes('timeline.json');
  }) || !!gifArt;

  const terrain3dArt = artifacts.find(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return name.toLowerCase().includes('terrain_3d.json');
  });

  const isLidar = artifacts.some(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return ['lidar', 'chm', 'las', 'laz', 'canopy_height'].some(k => name.toLowerCase().includes(k));
  }) || (task.files || []).some(f => ['lidar', 'chm', 'las', 'laz', 'autzen'].some(k => (f || '').toLowerCase().includes(k)))
  || (task.prompt || task.question || '').toLowerCase().includes('lidar')
  || (task.prompt || task.question || '').toLowerCase().includes('canopy height')
  || (task.prompt || task.question || '').toLowerCase().includes('point cloud');

  const isElevation = artifacts.some(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return ['dem', 'elevation', 'dsm', 'dtm', 'cop-dem', 'srtm', 'nasadem', 'topography', 'terrain'].some(k => name.toLowerCase().includes(k));
  }) || (task.files || []).some(f => ['dem', 'elevation', 'dsm', 'dtm', 'cop-dem', 'srtm', 'nasadem'].some(k => (f || '').toLowerCase().includes(k)))
  || (task.prompt || task.question || '').toLowerCase().includes('elevation')
  || (task.prompt || task.question || '').toLowerCase().includes('terrain')
  || (task.prompt || task.question || '').toLowerCase().includes('topography')
  || (task.prompt || task.question || '').toLowerCase().includes('dem')
  || (task.prompt || task.question || '').toLowerCase().includes('slope');

  // Strictly guard 3D view button to DEM, LiDAR, or elevation queries only
  const canShow3D = !!terrain3dArt || isLidar || isElevation;

  const profileSvgArt = artifacts.find(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return name.toLowerCase().includes('profile.svg') || (name.toLowerCase().includes('profile') && name.toLowerCase().endsWith('.svg'));
  });

  const isDone = task.status === 'done';
  const isFailed = task.status === 'failed';

  // Collect the final assistant narrative from accumulated text activities
  const finalAnswer = (() => {
    if (!isDone && !isFailed) return null;
    const textParts = (task.activities || [])
      .filter(a => a.type === 'text' && a.text && a.text.trim())
      .map(a => a.text);
    return textParts.length > 0 ? textParts.join('') : null;
  })();

  const relevantActivities = (task.activities || []).filter((act) => {
    // Input quality gate is already shown in the dedicated card right below the header
    if (act.type === 'vision_input_gate') return false;
    return true;
  });

  return (
    <div className="single-task-workbench" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

      {/* Task Header Card */}
      <div className="task-header-card" style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: '8px', padding: '12px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className="task-pill mono" style={{ background: '#0F766E', color: '#FFFFFF', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold' }}>
            #{taskNum}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: '13.5px', color: '#F1F5F9', wordBreak: 'break-word' }}>
              {task.question ? task.question : `Sandbox Slot #${taskNum} (Idle)`}
            </div>
            <div className="mono" style={{ fontSize: '11px', color: '#94A3B8', marginTop: '3px' }}>
              Elapsed: {formatSeconds(task)} • Status:{' '}
              <span style={{ fontWeight: 600, color: task.status === 'running' ? '#38BDF8' : task.status === 'done' ? '#10B981' : task.status === 'failed' ? '#F87171' : '#E2E8F0' }}>
                {statusLabel}
              </span>
            </div>
          </div>
          {(task.status === 'running' || task.status === 'pending_approval' || task.status === 'pending_stac_approval') && (
            <button
              type="button"
              className="btn danger"
              style={{ fontSize: '11px', padding: '4px 10px', background: 'rgba(239, 68, 68, 0.2)', border: '1px solid #EF4444', color: '#FCA5A5', borderRadius: '4px', cursor: 'pointer', flexShrink: 0 }}
              onClick={() => onCancelTask && onCancelTask(taskId)}
            >
              Abort Task
            </button>
          )}
        </div>
      </div>

      {/* Input Quality Gate Status Card — Always visible immediately when input gate runs */}
      {inputGateActivity && (
        <div>
          <ValidationViewer activity={inputGateActivity} />
        </div>
      )}

      {/* Autonomous STAC Satellite Preview & Approval Gate */}
      {task.status === 'pending_stac_approval' && task.stacPreview && (
        <div className="plan-approval-banner" style={{ borderLeft: '4px solid #0284C7', background: '#0F172A', border: '1px solid #1E293B', borderRadius: '8px', padding: '14px' }}>
          <div className="plan-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontSize: '13.5px', fontWeight: 700, color: '#38BDF8' }}>
              🛰️ Satellite Scene Previews — Review Before Native-Resolution Staging
            </span>
            <span className="mono" style={{ fontSize: '11px', color: '#38BDF8', background: 'rgba(56, 189, 248, 0.15)', padding: '2px 8px', borderRadius: '10px' }}>
              100% Native Resolution Preserved
            </span>
          </div>

          {task.stacPreview.explanation && (
            <div style={{ fontSize: '12.5px', color: '#E2E8F0', marginBottom: '10px', lineHeight: 1.5 }}>
              <MarkdownView content={task.stacPreview.explanation} />
            </div>
          )}

          <div className="mono" style={{ fontSize: '11px', color: '#94A3B8', background: '#1E293B', padding: '8px 10px', borderRadius: '6px', marginBottom: '12px', display: 'flex', flexWrap: 'wrap', gap: '14px' }}>
            <span><strong>Location:</strong> {task.stacPreview.location_name || 'Custom AOI'}</span>
            {task.stacPreview.bbox && (
              <span><strong>BBox:</strong> [{task.stacPreview.bbox.map(n => Number(n).toFixed(4)).join(', ')}]</span>
            )}
            {task.stacPreview.native_grid_estimate && (
              <span>
                <strong>Native Grid:</strong> ~{task.stacPreview.native_grid_estimate.estimated_width_px}×{task.stacPreview.native_grid_estimate.estimated_height_px} px
                ({task.stacPreview.native_grid_estimate.native_resolution_m}m native res, {task.stacPreview.native_grid_estimate.area_km2} km²)
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', marginBottom: '14px' }}>
            {(task.stacPreview.scenes || []).map((sc, idx) => (
              <div key={sc.id || idx} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: '6px', overflow: 'hidden' }}>
                {sc.thumbnail ? (
                  <div style={{ background: '#090D14', textAlign: 'center', height: '140px', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                    <img
                      src={sc.thumbnail}
                      alt={sc.label || sc.id}
                      style={{ maxHeight: '140px', maxWidth: '100%', objectFit: 'contain' }}
                    />
                  </div>
                ) : (
                  <div className="mono" style={{ height: '100px', background: '#090D14', color: '#64748B', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px' }}>
                    No preview thumbnail
                  </div>
                )}
                <div style={{ padding: '8px 10px', fontSize: '11px' }}>
                  <div style={{ fontWeight: 700, color: '#F1F5F9', marginBottom: '4px' }}>
                    {sc.label || `Scene ${idx + 1}`}
                  </div>
                  <div className="mono" style={{ fontSize: '10px', color: '#94A3B8', lineHeight: 1.5 }}>
                    <div><strong>Collection:</strong> {sc.collection}</div>
                    <div><strong>Date:</strong> {(sc.datetime || '').slice(0, 10) || 'N/A'}</div>
                    {sc.cloud_cover !== null && sc.cloud_cover !== undefined && (
                      <div><strong>Cloud Cover:</strong> {sc.cloud_cover}%</div>
                    )}
                    {sc.aoi_coverage_pct !== null && sc.aoi_coverage_pct !== undefined && (
                      <div><strong>AOI Coverage:</strong> {sc.aoi_coverage_pct}%</div>
                    )}
                    <div><strong>Bands:</strong> {(sc.assets || []).join(', ')}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="plan-actions" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button
              type="button"
              className="btn primary"
              style={{ backgroundColor: '#0284C7', color: '#FFFFFF', padding: '8px 14px', borderRadius: '4px', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
              onClick={() => onApprovePlan && onApprovePlan(taskId)}
            >
              ✓ Approve & Stage Native-Resolution Images
            </button>
            <div style={{ display: 'flex', gap: '8px', flex: 1 }}>
              <input
                type="text"
                className="input mono"
                style={{ flex: 1, fontSize: '11.5px', background: '#111827', border: '1px solid #1E293B', color: '#F1F5F9', padding: '6px 10px', borderRadius: '4px' }}
                placeholder="Or give feedback (e.g., 'cloudy, search July 2024 instead')…"
                value={revisionFeedback}
                onChange={(e) => setRevisionFeedback(e.target.value)}
              />
              <button
                type="button"
                className="btn"
                style={{ background: '#1E293B', color: '#E2E8F0', border: '1px solid #334155', borderRadius: '4px', padding: '6px 12px', cursor: 'pointer' }}
                onClick={() => {
                  if (!revisionFeedback.trim()) {
                    if (onNotify) onNotify('Please enter feedback for the satellite search.', 'warning');
                    return;
                  }
                  onRevisePlan && onRevisePlan(taskId, revisionFeedback.trim());
                  setRevisionFeedback('');
                }}
              >
                Search Again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Plan Approval Gate */}
      {task.status === 'pending_approval' && (
        <div className="plan-approval-banner" style={{ background: '#0F172A', border: '1px solid #1E293B', borderRadius: '8px', padding: '14px', borderLeft: '4px solid #14B8A6' }}>
          <div className="plan-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '13.5px', fontWeight: 600, color: '#14B8A6' }}>📋 Plan Proposed — User Review Required</span>
            <span className="mono" style={{ fontSize: '10.5px', color: '#94A3B8' }}>Autonomous container paused</span>
          </div>
          <div className="plan-body" style={{ color: '#E2E8F0', fontSize: '12px', marginBottom: '12px' }}>
            <MarkdownView content={task.plan || 'No plan details provided.'} />
          </div>
          <div className="plan-actions" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button
              type="button"
              className="btn primary"
              style={{ backgroundColor: '#0F766E', color: '#FFFFFF', padding: '8px 14px', borderRadius: '4px', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
              onClick={() => onApprovePlan && onApprovePlan(taskId)}
            >
              ✓ Approve Plan & Execute Analysis
            </button>
            <div style={{ display: 'flex', gap: '8px', flex: 1 }}>
              <input
                type="text"
                className="input mono"
                style={{ flex: 1, fontSize: '11.5px', background: '#111827', border: '1px solid #1E293B', color: '#F1F5F9', padding: '6px 10px', borderRadius: '4px' }}
                placeholder="Request plan revisions (e.g., 'use threshold 0.25 and add confidence map')…"
                value={revisionFeedback}
                onChange={(e) => setRevisionFeedback(e.target.value)}
              />
              <button
                type="button"
                className="btn"
                style={{ background: '#1E293B', color: '#E2E8F0', border: '1px solid #334155', borderRadius: '4px', padding: '6px 12px', cursor: 'pointer' }}
                onClick={() => {
                  if (!revisionFeedback.trim()) {
                    if (onNotify) onNotify('Please enter revision feedback.', 'warning');
                    return;
                  }
                  onRevisePlan && onRevisePlan(taskId, revisionFeedback.trim());
                  setRevisionFeedback('');
                }}
              >
                Send Revision
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Findings / Summary card shown when task completes */}
      {(task.answer || finalAnswer) && (
        <div className="task-findings-card" style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: '8px', padding: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <span style={{ fontWeight: 700, fontSize: '13.5px', color: '#F1F5F9' }}>
              {isDone ? '✅ Analysis Complete — Findings & Evidence' : '❌ Task Failed — Details'}
            </span>
            {isDone && (
              <span style={{ fontSize: '10px', background: 'rgba(16, 185, 129, 0.2)', color: '#10B981', padding: '2px 8px', borderRadius: '12px', fontWeight: 600 }}>DONE</span>
            )}
          </div>
          <div className="markdown-body" style={{ maxHeight: '550px', overflowY: 'auto', color: '#CBD5E1', fontSize: '12px', lineHeight: 1.6 }}>
            <MarkdownView content={task.answer || finalAnswer} />
          </div>
        </div>
      )}

      {/* Time Series Animation & Synchronized Frame Viewer */}
      {hasTimeline && (
        <div className="time-series-viewer-card" style={{ background: '#0F172A', borderRadius: '8px', padding: '12px', border: '1px solid #1E293B' }}>
          {(timelineFrame || gifArt) && (() => {
            const frameFname = timelineFrame && timelineFrame.file ? getBasename(timelineFrame.file) : '';
            const matchingArt = frameFname ? (artifacts || []).find((a) => getBasename(typeof a === 'string' ? a : a.name) === frameFname) : null;
            const gifUrl = gifArt ? (typeof gifArt === 'string' ? `/runs/${gifArt}` : gifArt.url) : (timelineFrame && timelineFrame.gif_url ? timelineFrame.gif_url : null);
            const initialSrc = (matchingArt && matchingArt.url)
              ? matchingArt.url
              : (timelineFrame && timelineFrame.png_url)
              ? timelineFrame.png_url
              : frameFname
              ? `/api/tasks/${taskId || task.id}/artifacts/${frameFname}`
              : gifUrl;

            if (!initialSrc) return null;

            return (
              <div style={{ textAlign: 'center', marginBottom: '10px' }}>
                <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%' }}>
                  <img
                    src={initialSrc}
                    alt="Time Series Frame"
                    style={{
                      maxHeight: '400px',
                      maxWidth: '100%',
                      height: 'auto',
                      margin: '0 auto',
                      borderRadius: '6px',
                      border: '1px solid #334155',
                      display: 'block'
                    }}
                    onError={(e) => {
                      if (e.target.dataset.triedFallback === 'true') {
                        if (gifUrl && e.target.src !== gifUrl) {
                          e.target.dataset.triedFallback = 'gif';
                          e.target.src = gifUrl;
                        }
                        return;
                      }
                      e.target.dataset.triedFallback = 'true';
                      if (frameFname) {
                        const fbUrl = `/api/tasks/${taskId || task.id}/artifacts/${frameFname}`;
                        if (e.target.src !== fbUrl) {
                          e.target.src = fbUrl;
                          return;
                        }
                      }
                      if (gifUrl && e.target.src !== gifUrl) {
                        e.target.src = gifUrl;
                      }
                    }}
                  />
                  {(timelineFrame && (timelineFrame.label || timelineFrame.date)) && (
                    <div style={{
                      position: 'absolute',
                      bottom: '10px',
                      left: '12px',
                      background: 'rgba(15, 23, 42, 0.85)',
                      backdropFilter: 'blur(4px)',
                      color: '#38BDF8',
                      padding: '4px 10px',
                      borderRadius: '4px',
                      fontSize: '11px',
                      fontWeight: 600,
                      fontFamily: 'monospace',
                      border: '1px solid rgba(56, 189, 248, 0.3)'
                    }}>
                      {timelineFrame.label || timelineFrame.date || ''}
                    </div>
                  )}
                </div>
              </div>
            );
          })()}
          <TimeSeriesPanel
            taskId={taskId || task.id}
            runDir={task.run_dir}
            onFrameChange={(frame) => setTimelineFrame(frame)}
          />
        </div>
      )}

      {/* Generated Deliverables Section */}
      {artifacts.length > 0 && (
        <div className="task-deliverables-card" style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: '8px', padding: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontWeight: 600, fontSize: '13px', color: '#F1F5F9' }}>
              📦 Generated Deliverables ({artifacts.length} files)
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {canShow3D && (
                <button
                  type="button"
                  className="btn s"
                  style={{ fontSize: '11px', backgroundColor: isLidar ? '#047857' : '#0284C7', color: '#FFFFFF', border: 'none', borderRadius: '4px', padding: '4px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
                  onClick={() => setShowTerrain3D(true)}
                  title={isLidar ? "Open interactive 3D LiDAR Canopy & Structures Inspector" : "Open interactive 3D terrain viewer"}
                >
                  {isLidar ? '🌲 View 3D LiDAR & Canopy' : '🏔️ View 3D Terrain'}
                </button>
              )}
              <button
                type="button"
                className="btn s primary"
                style={{ fontSize: '11px', backgroundColor: '#0F766E', color: '#FFFFFF', border: 'none', borderRadius: '4px', padding: '4px 8px', cursor: 'pointer' }}
                onClick={() => onSwitchToGlobe && onSwitchToGlobe()}
                title="View all outputs overlaid on the 3D Globe"
              >
                🌍 View on 3D Globe
              </button>
            </div>
          </div>

          {/* Embedded Elevation Cross-Section Chart if available */}
          {profileSvgArt && (
            <div style={{ marginBottom: '12px', background: '#0F172A', borderRadius: '8px', padding: '10px', border: '1px solid #1E293B', textAlign: 'center' }}>
              <img
                src={profileSvgArt.url || `/api/tasks/${taskId || task.id}/artifacts/${getBasename(typeof profileSvgArt === 'string' ? profileSvgArt : profileSvgArt.name)}`}
                alt="Elevation Cross-Section Profile"
                style={{ maxWidth: '100%', height: 'auto', display: 'block', margin: '0 auto', borderRadius: '6px' }}
              />
            </div>
          )}

          <div className="deliverables-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '8px' }}>
            {artifacts.map((art, idx) => {
              const fname = typeof art === 'string' ? art : art.name || 'file';
              const artUrl = typeof art === 'string' ? null : art.url;
              const ext = fname.toLowerCase().split('.').pop();
              const isTif = ext === 'tif' || ext === 'tiff';
              const isImg = ext === 'png' || ext === 'gif' || ext === 'webp' || ext === 'svg';
              const isPreviewable = isTif || isImg;
              const downloadUrl = artUrl || `/runs/${fname}`;

              return (
                <div key={idx} className="deliverable-chip" style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#0B0F17', border: '1px solid #1E293B', padding: '6px 10px', borderRadius: '6px' }}>
                  <span className="file-icon" style={{ fontSize: '14px' }}>{isTif ? '🗺️' : isImg ? '🖼️' : '📄'}</span>
                  <span className="file-name mono" title={fname} style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '11px', color: '#E2E8F0' }}>
                    {fname.split(/[/\\]/).pop()}
                  </span>
                  <div style={{ flexShrink: 0, display: 'flex', gap: '4px' }}>
                    {isPreviewable ? (
                      <button
                        type="button"
                        className="preview-btn"
                        style={{ background: '#1E293B', color: '#38BDF8', border: '1px solid #334155', borderRadius: '4px', fontSize: '10px', padding: '2px 6px', cursor: 'pointer' }}
                        onClick={() => onPreviewFile && onPreviewFile(art)}
                      >
                        Preview
                      </button>
                    ) : (
                      <a
                        href={downloadUrl}
                        download={fname.split(/[/\\]/).pop()}
                        className="preview-btn"
                        style={{ background: '#1E293B', color: '#94A3B8', border: '1px solid #334155', borderRadius: '4px', fontSize: '10px', padding: '2px 6px', textDecoration: 'none', display: 'inline-block' }}
                      >
                        Download
                      </a>
                    )}
                    {isTif && (
                      <button
                        type="button"
                        className="globe-overlay-btn"
                        style={{ background: '#0F766E', color: '#FFFFFF', border: 'none', borderRadius: '4px', fontSize: '10px', padding: '2px 6px', cursor: 'pointer' }}
                        onClick={() => onSwitchToGlobe && onSwitchToGlobe(art)}
                        title="Overlay on 3D Globe"
                      >
                        🌍
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Interactive 3D Terrain & LiDAR Viewer Modal */}
      {canShow3D && (
        <Terrain3DViewer
          isOpen={showTerrain3D}
          onClose={() => setShowTerrain3D(false)}
          payloadUrl={terrain3dArt ? (terrain3dArt.url || `/api/tasks/${taskId || task.id}/artifacts/${getBasename(typeof terrain3dArt === 'string' ? terrain3dArt : terrain3dArt.name)}`) : `/api/runs/${taskId || task.id}/terrain_3d.json`}
          availableTextures={artifacts.filter(a => {
            const n = (typeof a === 'string' ? a : a.name || '').toLowerCase();
            return (n.endsWith('.png') || n.endsWith('.jpg') || n.endsWith('.tif')) && !n.includes('profile.svg') && !n.includes('terrain_3d');
          })}
          title={isLidar ? "Interactive 3D LiDAR Canopy & Structures" : "Interactive 3D Digital Elevation Model"}
        />
      )}

      {/* Live Execution & Reasoning Activity Feed — Always visible when events exist */}
      {relevantActivities.length > 0 && (
        <div className="task-execution-logs-card" style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: '8px', padding: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontWeight: 600, fontSize: '12.5px', color: '#E2E8F0' }}>
              🔬 Execution Log & Reasoning ({relevantActivities.length} events)
            </span>
            <button
              type="button"
              className="btn s"
              style={{ fontSize: '11px', background: '#1E293B', color: '#E2E8F0', border: '1px solid #334155', padding: '2px 8px', borderRadius: '4px', cursor: 'pointer' }}
              onClick={() => setShowLogs(!showLogs)}
            >
              {showLogs ? 'Hide Events' : 'Show Events'}
            </button>
          </div>

          {showLogs && (
            <div
              ref={activityRef}
              onScroll={handleScroll}
              className="worker-activity-feed"
              style={{ marginTop: '10px', maxHeight: '540px', overflowY: 'auto', overflowX: 'hidden', display: 'flex', flexDirection: 'column', gap: '8px' }}
            >
              {relevantActivities.map((act, i) => {
                if (act.type === 'thinking') {
                  const textStr = act.text || '';
                  const wordCount = textStr.trim() ? textStr.trim().split(/\s+/).filter(Boolean).length : 0;
                  const charCount = textStr.length;
                  const isLatestThinking = task.status === 'running' && i === relevantActivities.length - 1;

                  return (
                    <details
                      key={i}
                      className="claude-thinking"
                      open={isLatestThinking || undefined}
                      style={{ border: '1px solid #1E293B', borderRadius: '6px', background: '#090D14', padding: '6px 10px' }}
                    >
                      <summary className="mono" style={{ fontSize: '11px', cursor: 'pointer', color: '#38BDF8', fontWeight: 600, userSelect: 'none' }}>
                        🧠 Reasoning trace ({wordCount} words · {charCount} chars)
                      </summary>
                      <div
                        className="mono"
                        style={{
                          whiteSpace: 'pre-wrap',
                          fontSize: '10.5px',
                          marginTop: '6px',
                          color: '#CBD5E1',
                          wordBreak: 'break-word',
                          overflowWrap: 'anywhere',
                          maxHeight: '300px',
                          overflowY: 'auto',
                          padding: '8px',
                          background: '#0B0F17',
                          borderRadius: '4px',
                          borderLeft: '2px solid #0F766E'
                        }}
                      >
                        {textStr || 'Thinking…'}
                      </div>
                    </details>
                  );
                } else if (act.type === 'text') {
                  if (!act.text || !act.text.trim()) return null;
                  return (
                    <div key={i} style={{ padding: '6px 8px', background: '#0B0F17', borderRadius: '6px', border: '1px solid #1E293B', color: '#E2E8F0', fontSize: '11.5px' }}>
                      <MarkdownView content={act.text} />
                    </div>
                  );
                } else if (act.type === 'tool') {
                  const argsObj = typeof act.args === 'object' && act.args !== null ? act.args : null;
                  const codeStr = argsObj && typeof argsObj.code === 'string' ? argsObj.code : null;
                  const inputFilesList = argsObj && Array.isArray(argsObj.input_files) ? argsObj.input_files : null;
                  const isStacSearch = act.toolName === 'search_stac';
                  const isStacPropose = act.toolName === 'propose_stac_scenes';
                  const shortArgs = (!codeStr && !isStacSearch && !isStacPropose)
                    ? (typeof act.args === 'string' ? act.args : JSON.stringify(act.args || {}))
                    : '';

                  return (
                    <div
                      key={i}
                      className={`tool-card ${act.running ? 'run' : act.ok ? 'ok' : 'bad'}`}
                      style={{
                        background: '#0B0F17',
                        border: `1px solid ${act.running ? '#38BDF8' : act.ok ? '#0F766E' : '#EF4444'}`,
                        borderLeft: `3px solid ${act.running ? '#38BDF8' : act.ok ? '#10B981' : '#EF4444'}`,
                        borderRadius: '6px',
                        padding: '8px 10px'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11.5px', flexWrap: 'wrap' }}>
                        <span className="mono" style={{ fontWeight: 600, color: '#38BDF8' }}>
                          {isStacSearch ? '🛰️ STAC Catalog Search (search_stac)' : isStacPropose ? '🛰️ Propose Satellite Previews (propose_stac_scenes)' : `🛠️ ${act.toolName}`}
                        </span>
                        {act.attempt && (
                          <span className="mono" style={{ fontSize: '10px', background: '#1E293B', color: '#CBD5E1', padding: '1px 6px', borderRadius: '4px' }}>
                            att {act.attempt}{act.max_attempts ? `/${act.max_attempts}` : ''}
                          </span>
                        )}
                        <span className="mono" style={{ marginLeft: 'auto', fontSize: '10.5px', fontWeight: 600, color: act.running ? '#38BDF8' : act.ok ? '#10B981' : '#F87171' }}>
                          {act.running
                            ? (isStacSearch ? '⏳ querying Planetary Computer STAC…' : '⏳ running in sandbox…')
                            : (act.duration_s != null ? `${act.duration_s}s · ` : '') + `exit ${act.exit_code ?? '—'}`}
                        </span>
                      </div>

                      {isStacSearch && argsObj && (
                        <div className="mono" style={{ fontSize: '10.5px', color: '#CBD5E1', marginTop: '6px', background: '#05080E', padding: '6px 8px', borderRadius: '4px', border: '1px solid #1E293B', display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                          {argsObj.location_name && <span><strong>Location:</strong> {argsObj.location_name}</span>}
                          {argsObj.collections && <span><strong>Collections:</strong> {Array.isArray(argsObj.collections) ? argsObj.collections.join(', ') : String(argsObj.collections)}</span>}
                          {(argsObj.start_date || argsObj.end_date) && <span><strong>Dates:</strong> {argsObj.start_date || '…'} → {argsObj.end_date || '…'}</span>}
                          {argsObj.bbox && Array.isArray(argsObj.bbox) && <span><strong>BBox:</strong> [{argsObj.bbox.map(n => Number(n).toFixed(3)).join(', ')}]</span>}
                          {argsObj.max_cloud_cover != null && <span><strong>Max Cloud:</strong> {argsObj.max_cloud_cover}%</span>}
                        </div>
                      )}

                      {isStacPropose && argsObj && (
                        <div className="mono" style={{ fontSize: '10.5px', color: '#CBD5E1', marginTop: '6px', background: '#05080E', padding: '6px 8px', borderRadius: '4px', border: '1px solid #1E293B' }}>
                          <div><strong>Location:</strong> {argsObj.location_name || 'Target AOI'} • <strong>Proposed Scenes:</strong> {Array.isArray(argsObj.scenes) ? argsObj.scenes.length : 0}</div>
                          {Array.isArray(argsObj.scenes) && argsObj.scenes.length > 0 && (
                            <div style={{ marginTop: '4px', color: '#94A3B8', fontSize: '10px' }}>
                              {argsObj.scenes.map((s, idx) => `${s.collection || 'STAC'} (${(s.datetime || s.id || '').slice(0, 10)})`).join(' · ')}
                            </div>
                          )}
                        </div>
                      )}

                      {inputFilesList && inputFilesList.length > 0 && (
                        <div className="mono" style={{ fontSize: '10px', color: '#94A3B8', marginTop: '4px' }}>
                          📂 Inputs ({inputFilesList.length}): {inputFilesList.map(getBasename).slice(0, 6).join(', ')}{inputFilesList.length > 6 ? ` +${inputFilesList.length - 6} more` : ''}
                        </div>
                      )}

                      {codeStr && (
                        <details open={act.running || undefined} style={{ marginTop: '6px', fontSize: '10.5px' }}>
                          <summary className="mono" style={{ cursor: 'pointer', color: '#14B8A6', fontWeight: 600, userSelect: 'none' }}>
                            💻 Agent Python Code ({codeStr.split('\n').length} lines)
                          </summary>
                          <pre
                            className="mono"
                            style={{
                              margin: '4px 0 0 0',
                              padding: '8px',
                              background: '#05080E',
                              border: '1px solid #1E293B',
                              borderRadius: '4px',
                              overflowX: 'auto',
                              overflowY: 'auto',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              maxHeight: '260px',
                              fontSize: '10px',
                              color: '#E2E8F0'
                            }}
                          >
                            {codeStr}
                          </pre>
                        </details>
                      )}

                      {shortArgs && (
                        <div className="mono" style={{ fontSize: '10.5px', color: '#94A3B8', wordBreak: 'break-all', overflowWrap: 'anywhere', marginTop: '4px' }}>
                          {shortArgs.length > 260 ? shortArgs.slice(0, 257) + '…' : shortArgs}
                        </div>
                      )}

                      {(act.error || act.stdout) && (
                        <details open={act.ok === false || isStacSearch || undefined} style={{ marginTop: '6px', fontSize: '10.5px' }}>
                          <summary className="mono" style={{ cursor: 'pointer', color: act.ok === false ? '#FCA5A5' : '#94A3B8', userSelect: 'none' }}>
                            {isStacSearch ? '📄 STAC Search Results' : '📄 Output / Logs'}
                          </summary>
                          <pre
                            className="mono"
                            style={{
                              margin: '4px 0 0 0',
                              padding: '6px 8px',
                              background: '#05080E',
                              border: '1px solid #1E293B',
                              borderRadius: '4px',
                              overflowX: 'auto',
                              overflowY: 'auto',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-all',
                              overflowWrap: 'anywhere',
                              maxHeight: '220px',
                              maxWidth: '100%',
                              fontSize: '10px',
                              color: act.ok === false ? '#FECACA' : '#CBD5E1'
                            }}
                          >
                            {act.error || act.stdout}
                          </pre>
                        </details>
                      )}
                    </div>
                  );
                } else if (act.type === 'stac_download') {
                  return (
                    <div
                      key={i}
                      className={`tool-card ${act.running ? 'run' : act.ok ? 'ok' : 'bad'}`}
                      style={{
                        background: '#0B0F17',
                        border: `1px solid ${act.running ? '#38BDF8' : act.ok ? '#0F766E' : '#EF4444'}`,
                        borderLeft: `3px solid ${act.running ? '#38BDF8' : act.ok ? '#10B981' : '#EF4444'}`,
                        borderRadius: '6px',
                        padding: '8px 10px'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11.5px', flexWrap: 'wrap' }}>
                        <span className="mono" style={{ fontWeight: 600, color: '#38BDF8' }}>
                          {act.running ? '⬇️ Downloading STAC Band:' : act.ok ? '✅ Staged STAC Band:' : '❌ STAC Download Failed:'} {act.filename}
                        </span>
                        <span className="mono" style={{ marginLeft: 'auto', fontSize: '10.5px', fontWeight: 600, color: act.running ? '#38BDF8' : act.ok ? '#10B981' : '#F87171' }}>
                          {act.running
                            ? '⏳ Cropping & downloading at 100% native resolution…'
                            : act.ok
                              ? `${act.size_mb != null ? `${act.size_mb} MB · ` : ''}${act.duration_s != null ? `${act.duration_s}s` : 'done'}`
                              : (act.error || 'failed')}
                        </span>
                      </div>
                      {(act.collection || act.asset_key || act.width) && (
                        <div className="mono" style={{ fontSize: '10px', color: '#94A3B8', marginTop: '4px', display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                          {act.collection && <span><strong>Collection:</strong> {act.collection}</span>}
                          {act.asset_key && <span><strong>Band:</strong> {act.asset_key}</span>}
                          {act.date && <span><strong>Date:</strong> {act.date}</span>}
                          {(act.width && act.height) && <span><strong>Grid:</strong> {act.width}×{act.height} px</span>}
                        </div>
                      )}
                    </div>
                  );
                } else if (act.type === 'stac_staged') {
                  const stagedList = act.files || [];
                  return (
                    <div
                      key={i}
                      className="tool-card ok"
                      style={{
                        background: '#0B1320',
                        border: '1px solid #0F766E',
                        borderLeft: '3px solid #10B981',
                        borderRadius: '6px',
                        padding: '8px 10px'
                      }}
                    >
                      <div className="mono" style={{ fontWeight: 600, fontSize: '11.5px', color: '#10B981' }}>
                        📥 Staged {stagedList.length} Native-Resolution GeoTIFFs to Workspace
                      </div>
                      {stagedList.length > 0 && (
                        <div className="mono" style={{ fontSize: '10px', color: '#CBD5E1', marginTop: '4px', lineHeight: 1.5 }}>
                          {stagedList.map(getBasename).join(', ')}
                        </div>
                      )}
                    </div>
                  );
                } else if (act.type === 'stac_preview_ready') {
                  const scCount = (act.preview && Array.isArray(act.preview.scenes)) ? act.preview.scenes.length : 0;
                  return (
                    <div
                      key={i}
                      className="tool-card ok"
                      style={{
                        background: '#0B1120',
                        border: '1px solid #0284C7',
                        borderLeft: '3px solid #38BDF8',
                        borderRadius: '6px',
                        padding: '8px 10px'
                      }}
                    >
                      <div className="mono" style={{ fontWeight: 600, fontSize: '11.5px', color: '#38BDF8' }}>
                        🛰️ STAC Satellite Previews Ready ({scCount} scene{scCount === 1 ? '' : 's'} proposed for review)
                      </div>
                    </div>
                  );
                } else if (act.type === 'vision_check') {
                  const imgName = act.image ? act.image.split(/[/\\]/).pop() : 'image';
                  const isStarted = act.state === 'started';
                  const isOk = act.verdict === 'ok';
                  const isBad = act.verdict === 'needs_revision';
                  const isNotVerified = act.verdict === 'not_verified' || act.verdict === 'insufficient_data';

                  if (isStarted) {
                    return (
                      <div key={i} className="tool-card run" style={{ padding: '6px 8px', borderLeft: '3px solid #3B82F6', marginTop: '6px', background: '#0B0F17', borderRadius: '4px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: '#38BDF8' }}>
                          <span className="mono" style={{ fontWeight: 600 }}>🔍 Starting Visual QA: {imgName}</span>
                          {act.index && act.total && (
                            <span className="mono" style={{ marginLeft: 'auto', fontSize: '10.5px', color: '#94A3B8' }}>
                              {act.index} / {act.total}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={i} className={`tool-card ${isOk ? 'ok' : isBad ? 'bad' : isNotVerified ? 'bad' : ''}`} style={{ padding: '6px 8px', background: '#0B0F17', border: '1px solid #1E293B', borderRadius: '4px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
                        <span className="mono" style={{ fontWeight: 600, color: '#E2E8F0' }}>👁️ Visual QA: {imgName}</span>
                        <span className="mono" style={{ marginLeft: 'auto', fontSize: '10.5px', color: isOk ? '#10B981' : isBad ? '#EF4444' : '#F59E0B' }}>
                          {act.verdict || 'checking…'}
                        </span>
                      </div>
                      {act.text && act.text !== 'ok' && (
                        <div style={{ fontSize: '10.5px', color: '#CBD5E1', marginTop: '4px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{act.text}</div>
                      )}
                    </div>
                  );
                } else if (act.type && act.type.startsWith('vision_')) {
                  return <ValidationViewer key={i} activity={act} />;
                }
                return null;
              })}
            </div>
          )}
        </div>
      )}

    </div>
  );
}
