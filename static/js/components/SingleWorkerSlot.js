import { html, React } from '../html.js';
import { MarkdownView } from './MarkdownView.js';
import { TimeSeriesPanel } from './TimeSeriesPanel.js';

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
  const activityRef = useRef(null);

  // Auto-scroll activity feed to bottom as new events arrive
  useEffect(() => {
    if (activityRef.current && showLogs) {
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
    task.status === 'pending_approval' ? 'Plan Pending Approval' :
    task.status === 'done' ? 'Completed' :
    task.status === 'failed' ? (task.error || 'Failed') : 'Idle';

  const artifacts = task.artifacts || [];
  const hasTimeline = artifacts.some(a => {
    const name = typeof a === 'string' ? a : (a.name || '');
    return name.toLowerCase().includes('timeline.json');
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
    if (act.type === 'vision_check' && act.state === 'started') return false;
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
          ${task.status === 'running' || task.status === 'pending_approval' ? html`
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
          ${timelineFrame && timelineFrame.file ? (() => {
            const frameFname = getBasename(timelineFrame.file);
            const matchingArt = (artifacts || []).find((a) => getBasename(typeof a === 'string' ? a : a.name) === frameFname);
            const initialSrc = (matchingArt && matchingArt.url)
              ? matchingArt.url
              : (timelineFrame.png_url || `/api/tasks/${taskId || task.id}/artifacts/${frameFname}`);

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
                    if (e.target.dataset.triedFallback) return;
                    e.target.dataset.triedFallback = 'true';
                    const fbUrl = `/api/tasks/${taskId || task.id}/artifacts/${frameFname}`;
                    if (e.target.src !== fbUrl) e.target.src = fbUrl;
                  }}
                />
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
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
            <span style=${{ fontWeight: 600, fontSize: '13px' }}>
              Generated Deliverables (${artifacts.length} files)
            </span>
            <button
              type="button"
              className="btn s primary"
              style=${{ fontSize: '11px', backgroundColor: '#0F766E', color: '#FFFFFF' }}
              onClick=${() => onSwitchToGlobe && onSwitchToGlobe()}
              title="View all outputs overlaid on the 3D Globe"
            >
              \ud83c\udf0d View on 3D Globe
            </button>
          </div>
          <div className="deliverables-grid">
            ${artifacts.map((art, idx) => {
              const fname = typeof art === 'string' ? art : art.name || 'file';
              const artUrl = typeof art === 'string' ? null : art.url;
              const ext = fname.toLowerCase().split('.').pop();
              const isTif = ext === 'tif' || ext === 'tiff';
              const isImg = ext === 'png' || ext === 'gif' || ext === 'webp';
              const isPreviewable = isTif || isImg;
              // Non-previewable: json, geojson, csv, txt → trigger download
              const downloadUrl = artUrl || `/runs/${fname}`;
              return html`
                <div key=${idx} className="deliverable-chip">
                  <span className="file-icon">${isTif ? '\ud83d\uddfa\ufe0f' : isImg ? '\ud83d\uddbc\ufe0f' : '\ud83d\udcc4'}</span>
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
                        \ud83c\udf0d
                      </button>
                    ` : null}
                  </div>
                </div>
              `;
            })}
          </div>
        </div>
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
                  const isOk = act.verdict === 'ok';
                  const isBad = act.verdict === 'needs_revision';
                  return html`
                    <div key=${i} className="tool-card ${isOk ? 'ok' : isBad ? 'bad' : ''}" style=${{ padding: '6px 8px' }}>
                      <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
                        <span className="mono" style=${{ fontWeight: 600 }}>\ud83d\udc41\ufe0f Visual QA: ${imgName}</span>
                        <span className="mono" style=${{ marginLeft: 'auto', fontSize: '10.5px', color: isOk ? '#065F46' : isBad ? '#991B1B' : '#5B6B64' }}>
                          ${act.verdict || 'checking\u2026'}
                        </span>
                      </div>
                      ${act.text && act.text !== 'ok' ? html`
                        <div style=${{ fontSize: '10.5px', color: '#4B5B54', marginTop: '4px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>${act.text}</div>
                      ` : null}
                    </div>
                  `;
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
