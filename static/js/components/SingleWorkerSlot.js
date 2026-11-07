import { html, React } from '../html.js';
import { MarkdownView } from './MarkdownView.js';
import { TimeSeriesPanel } from './TimeSeriesPanel.js';
import { Terrain3DViewer } from './Terrain3DViewer.js?v=20261102_lidar_fix';
import { ValidationViewer } from './ValidationViewer.js';

const { useState, useRef, useEffect } = React;

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
    // If the user has scrolled up more than 60px above bottom, pause autoscroll
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
    task.status === 'running' ? (task.step || 'Running\u2026') :
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
  || (task.prompt || '').toLowerCase().includes('lidar')
  || (task.prompt || '').toLowerCase().includes('canopy height')
  || (task.prompt || '').toLowerCase().includes('point cloud');

  const isElevation = artifacts.some(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return ['dem', 'elevation', 'dsm', 'dtm', 'cop-dem', 'srtm', 'nasadem', 'topography', 'terrain'].some(k => name.toLowerCase().includes(k));
  }) || (task.files || []).some(f => ['dem', 'elevation', 'dsm', 'dtm', 'cop-dem', 'srtm', 'nasadem'].some(k => (f || '').toLowerCase().includes(k)))
  || (task.prompt || '').toLowerCase().includes('elevation')
  || (task.prompt || '').toLowerCase().includes('terrain')
  || (task.prompt || '').toLowerCase().includes('topography')
  || (task.prompt || '').toLowerCase().includes('dem')
  || (task.prompt || '').toLowerCase().includes('slope');

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
    return true;
  });

  return html`
    <div className="single-task-workbench">

      <!-- Task Header Card -->
      <div className="task-header-card">
        <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className="task-pill mono">#${taskNum}</span>
          <div style=${{ flex: 1 }}>
            <div style=${{ fontWeight: 600, fontSize: '15px', color: '#14201C' }}>
              ${task.question ? task.question : `Sandbox Slot #${taskNum} (Idle)`}
            </div>
            <div className="mono" style=${{ fontSize: '11px', color: '#5B6B64', marginTop: '2px' }}>
              Elapsed: ${formatSeconds(task)} \u2022 Status: <span style=${{ fontWeight: 600 }}>${statusLabel}</span>
            </div>
          </div>
          ${task.status === 'running' || task.status === 'pending_approval' || task.status === 'pending_stac_approval' ? html`
            <button
              type="button"
              className="btn danger"
              style=${{ fontSize: '11px', padding: '4px 10px' }}
              onClick=${() => onCancelTask && onCancelTask(taskId)}
            >
              Abort Task
            </button>
          ` : null}
        </div>
      </div>

      <!-- Autonomous STAC Satellite Preview & Approval Gate -->
      ${task.status === 'pending_stac_approval' && task.stacPreview ? html`
        <div className="plan-approval-banner" style=${{ borderLeft: '4px solid #0284C7', background: '#F0F9FF' }}>
          <div className="plan-header" style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <span style=${{ fontSize: '14px', fontWeight: 700, color: '#0369A1' }}>
              \ud83d\udef0\ufe0f Satellite Scene Previews \u2014 Review Before Native-Resolution Staging
            </span>
            <span className="mono" style=${{ fontSize: '11px', color: '#0284C7', background: '#E0F2FE', padding: '2px 8px', borderRadius: '10px' }}>
              100% Native Resolution Preserved
            </span>
          </div>

          ${task.stacPreview.explanation ? html`
            <div style=${{ fontSize: '12.5px', color: '#1E293B', marginBottom: '10px', lineHeight: 1.5 }}>
              <${MarkdownView} content=${task.stacPreview.explanation} />
            </div>
          ` : null}

          <div className="mono" style=${{ fontSize: '11px', color: '#334155', background: '#E2E8F0', padding: '6px 10px', borderRadius: '6px', marginBottom: '12px', display: 'flex', flexWrap: 'wrap', gap: '14px' }}>
            <span><strong>Location:</strong> ${task.stacPreview.location_name || 'Custom AOI'}</span>
            ${task.stacPreview.bbox ? html`
              <span><strong>BBox:</strong> [${task.stacPreview.bbox.map(n => Number(n).toFixed(4)).join(', ')}]</span>
            ` : null}
            ${task.stacPreview.native_grid_estimate ? html`
              <span>
                <strong>Native Grid:</strong> ~${task.stacPreview.native_grid_estimate.estimated_width_px}\u00d7${task.stacPreview.native_grid_estimate.estimated_height_px} px
                (${task.stacPreview.native_grid_estimate.native_resolution_m}m native res, ${task.stacPreview.native_grid_estimate.area_km2} km\u00b2)
              </span>
            ` : null}
          </div>

          <div style=${{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '12px', marginBottom: '14px' }}>
            ${(task.stacPreview.scenes || []).map((sc, idx) => html`
              <div key=${sc.id || idx} style=${{ background: '#FFFFFF', border: '1px solid #CBD5E1', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
                ${sc.thumbnail ? html`
                  <div style=${{ background: '#0F172A', textAlign: 'center', height: '170px', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                    <img
                      src=${sc.thumbnail}
                      alt=${sc.label || sc.id}
                      style=${{ maxHeight: '170px', maxWidth: '100%', objectFit: 'contain' }}
                    />
                  </div>
                ` : html`
                  <div className="mono" style=${{ height: '120px', background: '#1E293B', color: '#94A3B8', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px' }}>
                    No preview thumbnail
                  </div>
                `}
                <div style=${{ padding: '8px 10px', fontSize: '11.5px' }}>
                  <div style=${{ fontWeight: 700, color: '#0F172A', marginBottom: '4px' }}>
                    ${sc.label || `Scene ${idx + 1}`}
                  </div>
                  <div className="mono" style=${{ fontSize: '10.5px', color: '#475569', lineHeight: 1.5 }}>
                    <div><strong>Collection:</strong> ${sc.collection}</div>
                    <div><strong>Date:</strong> ${(sc.datetime || '').slice(0, 10) || 'N/A'}</div>
                    ${sc.cloud_cover !== null && sc.cloud_cover !== undefined ? html`
                      <div><strong>Cloud Cover:</strong> ${sc.cloud_cover}%</div>
                    ` : null}
                    ${sc.aoi_coverage_pct !== null && sc.aoi_coverage_pct !== undefined ? html`
                      <div><strong>AOI Coverage:</strong> ${sc.aoi_coverage_pct}%</div>
                    ` : null}
                    <div><strong>Bands:</strong> ${(sc.assets || []).join(', ')}</div>
                  </div>
                </div>
              </div>
            `)}
          </div>

          <div className="plan-actions">
            <button
              type="button"
              className="btn primary"
              style=${{ backgroundColor: '#0284C7', color: '#FFFFFF' }}
              onClick=${() => onApprovePlan && onApprovePlan(taskId)}
            >
              \u2713 Approve & Stage Native-Resolution Images
            </button>
            <div style=${{ display: 'flex', gap: '8px', flex: 1, marginTop: '8px' }}>
              <input
                type="text"
                className="input mono"
                style=${{ flex: 1, fontSize: '11.5px' }}
                placeholder="Or give feedback to search different images (e.g., '2020 image looks cloudy, try June instead')\u2026"
                value=${revisionFeedback}
                onChange=${(e) => setRevisionFeedback(e.target.value)}
              />
              <button
                type="button"
                className="btn"
                onClick=${() => {
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
      ` : null}

      <!-- Input Quality Gate Status Card -->
      ${inputGateActivity ? html`
        <div style=${{ marginBottom: '12px' }}>
          <${ValidationViewer} activity=${inputGateActivity} />
        </div>
      ` : null}

      <!-- Plan Approval Gate -->
      ${task.status === 'pending_approval' ? html`
        <div className="plan-approval-banner">
          <div className="plan-header">
            <span style=${{ fontSize: '14px', fontWeight: 600 }}>\ud83d\udccb Plan Proposed \u2014 User Review Required</span>
            <span style=${{ fontSize: '11px', color: '#3730A3' }}>Autonomous container paused</span>
          </div>
          <div className="plan-body">
            <${MarkdownView} content=${task.plan || 'No plan details provided.'} />
          </div>
          <div className="plan-actions">
            <button
              type="button"
              className="btn primary"
              style=${{ backgroundColor: '#0F766E', color: '#FFFFFF' }}
              onClick=${() => onApprovePlan && onApprovePlan(taskId)}
            >
              \u2713 Approve Plan & Execute Analysis
            </button>
            <div style=${{ display: 'flex', gap: '8px', flex: 1, marginTop: '8px' }}>
              <input
                type="text"
                className="input mono"
                style=${{ flex: 1, fontSize: '11.5px' }}
                placeholder="Request plan revisions (e.g., 'use threshold 0.25 and add confidence map')\u2026"
                value=${revisionFeedback}
                onChange=${(e) => setRevisionFeedback(e.target.value)}
              />
              <button
                type="button"
                className="btn"
                onClick=${() => {
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
      ` : null}

      <!-- Findings / Summary card shown when task completes -->
      ${(task.answer || finalAnswer) ? html`
        <div className="task-findings-card">
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <span style=${{ fontWeight: 700, fontSize: '13.5px', color: '#14201C' }}>
              ${isDone ? '\u2705 Analysis Complete \u2014 Findings & Evidence' : '\u274c Task Failed \u2014 Details'}
            </span>
            ${isDone ? html`
              <span style=${{ fontSize: '11px', background: '#D1FAE5', color: '#065F46', padding: '2px 8px', borderRadius: '12px', fontWeight: 600 }}>DONE</span>
            ` : null}
          </div>
          <div className="markdown-body" style=${{ maxHeight: '600px', overflowY: 'auto' }}>
            <${MarkdownView} content=${task.answer || finalAnswer} />
          </div>
        </div>
      ` : null}

      <!-- Time Series Animation & Synchronized Frame Viewer -->
      ${hasTimeline ? html`
        <div className="time-series-viewer-card" style=${{
          background: '#0F172A',
          borderRadius: '8px',
          padding: '12px',
          marginBottom: '14px',
          border: '1px solid #1E293B',
          boxShadow: '0 4px 14px rgba(0,0,0,0.3)'
        }}>
          ${(timelineFrame || gifArt) ? (() => {
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

            return html`
            <div style=${{ textAlign: 'center', marginBottom: '10px' }}>
              <div style=${{ position: 'relative', display: 'inline-block', maxWidth: '100%' }}>
                <img
                  src=${initialSrc}
                  alt="Time Series Frame"
                  style=${{
                    maxHeight: '440px',
                    maxWidth: '100%',
                    height: 'auto',
                    margin: '0 auto',
                    borderRadius: '6px',
                    border: '1px solid #334155',
                    display: 'block',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.6)'
                  }}
                  onError=${(e) => {
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
                ${(timelineFrame && (timelineFrame.label || timelineFrame.date)) ? html`
                  <div style=${{
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
                    ${timelineFrame.label || timelineFrame.date || ''}
                  </div>
                ` : null}
              </div>
            </div>
            `;
          })() : null}
          <${TimeSeriesPanel}
            taskId=${taskId || task.id}
            runDir=${task.run_dir}
            onFrameChange=${(frame) => setTimelineFrame(frame)}
          />
        </div>
      ` : null}

      <!-- Deliverables Section -->
      ${artifacts.length > 0 ? html`
        <div className="task-deliverables-card">
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px', flexWrap: 'wrap', gap: '6px' }}>
            <span style=${{ fontWeight: 600, fontSize: '13px' }}>
              Generated Deliverables (${artifacts.length} files)
            </span>
            <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              ${canShow3D ? html`
                <button
                  type="button"
                  className="btn s"
                  style=${{ fontSize: '11px', backgroundColor: isLidar ? '#047857' : '#0284C7', color: '#FFFFFF', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
                  onClick=${() => setShowTerrain3D(true)}
                  title=${isLidar ? "Open interactive 3D LiDAR Canopy & Structures Inspector" : "Open interactive 3D terrain viewer"}
                >
                  ${isLidar ? '🌲 View 3D LiDAR & Canopy' : '🏔️ View 3D Terrain'}
                </button>
              ` : null}
              <button
                type="button"
                className="btn s primary"
                style=${{ fontSize: '11px', backgroundColor: '#0F766E', color: '#FFFFFF' }}
                onClick=${() => onSwitchToGlobe && onSwitchToGlobe()}
                title="View all outputs overlaid on the 3D Globe"
              >
                🌍 View on 3D Globe
              </button>
            </div>
          </div>

          <!-- Embedded Elevation Cross-Section Chart if available -->
          ${profileSvgArt ? html`
            <div style=${{ marginBottom: '12px', background: '#0F172A', borderRadius: '8px', padding: '10px', border: '1px solid #1E293B', textAlign: 'center' }}>
              <img
                src=${profileSvgArt.url || `/api/tasks/${taskId || task.id}/artifacts/${getBasename(typeof profileSvgArt === 'string' ? profileSvgArt : profileSvgArt.name)}`}
                alt="Elevation Cross-Section Profile"
                style=${{ maxWidth: '100%', height: 'auto', display: 'block', margin: '0 auto', borderRadius: '6px' }}
              />
            </div>
          ` : null}

          <div className="deliverables-grid">
            ${artifacts.map((art, idx) => {
              const fname = typeof art === 'string' ? art : art.name || 'file';
              const artUrl = typeof art === 'string' ? null : art.url;
              const ext = fname.toLowerCase().split('.').pop();
              const isTif = ext === 'tif' || ext === 'tiff';
              const isImg = ext === 'png' || ext === 'gif' || ext === 'webp' || ext === 'svg';
              const isPreviewable = isTif || isImg;
              // Non-previewable: json, geojson, csv, txt → trigger download
              const downloadUrl = artUrl || `/runs/${fname}`;
              return html`
                <div key=${idx} className="deliverable-chip">
                  <span className="file-icon">${isTif ? '🗺️' : isImg ? '🖼️' : '📄'}</span>
                  <span className="file-name mono" title=${fname} style=${{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${fname.split(/[/\\]/).pop()}</span>
                  <div style=${{ flexShrink: 0, display: 'flex', gap: '4px' }}>
                    ${isPreviewable ? html`
                      <button
                        type="button"
                        className="preview-btn"
                        onClick=${() => onPreviewFile && onPreviewFile(art)}
                      >
                        Preview
                      </button>
                    ` : html`
                      <a
                        href=${downloadUrl}
                        download=${fname.split(/[/\\]/).pop()}
                        className="preview-btn"
                        style=${{ textDecoration: 'none', display: 'inline-block' }}
                      >
                        Download
                      </a>
                    `}
                    ${isTif ? html`
                      <button
                        type="button"
                        className="globe-overlay-btn"
                        onClick=${() => {
                          if (onSwitchToGlobe) onSwitchToGlobe(art);
                        }}
                        title="Overlay on 3D Globe"
                      >
                        🌍
                      </button>
                    ` : null}
                  </div>
                </div>
              `;
            })}
          </div>
        </div>
      ` : null}

      <!-- Interactive 3D Terrain Viewer Modal -->
      ${canShow3D ? html`
        <${Terrain3DViewer}
          isOpen=${showTerrain3D}
          onClose=${() => setShowTerrain3D(false)}
          payloadUrl=${terrain3dArt ? (terrain3dArt.url || `/api/tasks/${taskId || task.id}/artifacts/${getBasename(typeof terrain3dArt === 'string' ? terrain3dArt : terrain3dArt.name)}`) : `/api/runs/${taskId || task.id}/terrain_3d.json`}
          availableTextures=${artifacts.filter(a => {
            const n = (typeof a === 'string' ? a : a.name || '').toLowerCase();
            return (n.endsWith('.png') || n.endsWith('.jpg') || n.endsWith('.tif')) && !n.includes('profile.svg') && !n.includes('terrain_3d');
          })}
          title=${isLidar ? "Interactive 3D LiDAR Canopy & Structures" : "Interactive 3D Digital Elevation Model"}
        />
      ` : null}

      <!-- Collapsible Execution Activity Feed -->
      ${relevantActivities.length > 0 ? html`
        <div className="task-execution-logs-card">
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style=${{ fontWeight: 600, fontSize: '12px', color: '#4B5B54' }}>
              \ud83d\udd2c Execution Log (${relevantActivities.length} events)
            </span>
            <button
              type="button"
              className="btn s"
              style=${{ fontSize: '11px' }}
              onClick=${() => setShowLogs(!showLogs)}
            >
              ${showLogs ? 'Hide Events' : 'Show Events'}
            </button>
          </div>

          ${showLogs ? html`
            <div
              ref=${activityRef}
              onScroll=${handleScroll}
              className="worker-activity-feed"
              style=${{ marginTop: '10px', maxHeight: '480px', overflowY: 'auto', overflowX: 'hidden' }}
            >
              ${relevantActivities.map((act, i) => {
                if (act.type === 'thinking') {
                  return html`
                    <details key=${i} className="claude-thinking">
                      <summary className="mono" style=${{ fontSize: '11px', cursor: 'pointer', color: '#6B7280', padding: '4px 0' }}>
                        \ud83e\udde0 Reasoning trace (${act.text ? Math.ceil(act.text.length / 5) + ' words' : '\u2026'})
                      </summary>
                      <div
                        className="mono"
                        style=${{
                          whiteSpace: 'pre-wrap',
                          fontSize: '10.5px',
                          marginTop: '4px',
                          color: '#6B7280',
                          wordBreak: 'break-word',
                          overflowWrap: 'anywhere',
                          maxHeight: '300px',
                          overflowY: 'auto',
                          padding: '6px 8px',
                          background: '#F9FAFB',
                          borderRadius: '4px',
                          borderLeft: '2px solid #E5E7EB'
                        }}
                      >
                        ${act.text}
                      </div>
                    </details>
                  `;
                } else if (act.type === 'text') {
                  if (!act.text || !act.text.trim()) return null;
                  return html`
                    <div key=${i} style=${{ padding: '5px 0', borderBottom: '1px solid #F3F4F1' }}>
                      <${MarkdownView} content=${act.text} />
                    </div>
                  `;
                } else if (act.type === 'tool') {
                  const shortArgs = typeof act.args === 'string'
                    ? act.args
                    : JSON.stringify(act.args || {});
                  return html`
                    <div key=${i} className="tool-card ${act.running ? 'run' : act.ok ? 'ok' : 'bad'}">
                      <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11.5px', flexWrap: 'wrap' }}>
                        <span className="mono" style=${{ fontWeight: 600 }}>${act.toolName}</span>
                        ${act.attempt ? html`<span className="mono" style=${{ fontSize: '10px', color: '#5B6B64' }}>att ${act.attempt}</span>` : null}
                        <span className="mono" style=${{ marginLeft: 'auto', fontSize: '10.5px', color: '#5B6B64' }}>
                          ${act.running
                            ? '\u23f3 running\u2026'
                            : (act.duration_s != null ? `${act.duration_s}s \u00b7 ` : '') + `exit ${act.exit_code ?? '\u2014'}`}
                        </span>
                      </div>
                      ${shortArgs ? html`
                        <div className="mono" style=${{ fontSize: '10.5px', color: '#5B6B64', wordBreak: 'break-all', overflowWrap: 'anywhere', marginTop: '2px' }}>
                          ${shortArgs.length > 220 ? shortArgs.slice(0, 217) + '\u2026' : shortArgs}
                        </div>
                      ` : null}
                      ${(act.error || act.stdout) ? html`
                        <details style=${{ marginTop: '4px', fontSize: '10.5px' }}>
                          <summary style=${{ cursor: 'pointer', color: '#4B5B54', userSelect: 'none' }}>Output / Logs</summary>
                          <pre
                            className="mono"
                            style=${{
                              margin: '4px 0',
                              padding: '6px 8px',
                              background: '#F8F9F7',
                              borderRadius: '4px',
                              overflowX: 'auto',
                              overflowY: 'auto',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-all',
                              overflowWrap: 'anywhere',
                              maxHeight: '220px',
                              maxWidth: '100%',
                              fontSize: '10px'
                            }}
                          >${act.error || act.stdout}</pre>
                        </details>
                      ` : null}
                    </div>
                  `;
                } else if (act.type === 'vision_check') {
                  const imgName = act.image ? act.image.split(/[/\\]/).pop() : 'image';
                  const isStarted = act.state === 'started';
                  const isOk = act.verdict === 'ok';
                  const isBad = act.verdict === 'needs_revision';
                  const isNotVerified = act.verdict === 'not_verified' || act.verdict === 'insufficient_data';

                  if (isStarted) {
                    return html`
                      <div key=${i} className="tool-card run" style=${{ padding: '6px 8px', borderLeft: '3px solid #3B82F6', marginTop: '6px' }}>
                        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
                          <span className="mono" style=${{ fontWeight: 600 }}>🔍 Starting Visual QA: ${imgName}</span>
                          ${act.index && act.total ? html`
                            <span className="mono" style=${{ marginLeft: 'auto', fontSize: '10.5px', color: '#6B7280' }}>
                              ${act.index} / ${act.total}
                            </span>
                          ` : null}
                        </div>
                      </div>
                    `;
                  }

                  return html`
                    <div key=${i} className="tool-card ${isOk ? 'ok' : isBad ? 'bad' : isNotVerified ? 'bad' : ''}" style=${{ padding: '6px 8px' }}>
                      <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
                        <span className="mono" style=${{ fontWeight: 600 }}>\ud83d\udc41\ufe0f Visual QA: ${imgName}</span>
                        <span className="mono" style=${{ marginLeft: 'auto', fontSize: '10.5px', color: isOk ? '#065F46' : isBad ? '#991B1B' : isNotVerified ? '#B45309' : '#5B6B64' }}>
                          ${act.verdict || 'checking\u2026'}
                        </span>
                      </div>
                      ${act.text && act.text !== 'ok' ? html`
                        <div style=${{ fontSize: '10.5px', color: '#4B5B54', marginTop: '4px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>${act.text}</div>
                      ` : null}
                    </div>
                  `;
                } else if (act.type && act.type.startsWith('vision_')) {
                  return html`<${ValidationViewer} key=${i} activity=${act} />`;
                }
                return null;
              })}
            </div>
          ` : null}
        </div>
      ` : null}

    </div>
  `;
}
