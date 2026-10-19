// Astryx Worker Sandbox Slots Component (3 Concurrent Sandboxes)
import { html, React } from '/static/js/html.js';
const { useState, useEffect, useRef } = React;

function TaskActivityFeed({ activities }) {
  const feedRef = useRef(null);
  const userScrolledUpRef = useRef(false);

  const handleScroll = (e) => {
    const el = e.target;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    userScrolledUpRef.current = !isAtBottom;
  };

  useEffect(() => {
    if (feedRef.current && !userScrolledUpRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [activities]);

  if (!activities || activities.length === 0) return null;

  return html`
    <div className="worker-activity-feed" ref=${feedRef} onScroll=${handleScroll}>
      ${activities.map((act, i) => {
        if (act.type === 'thinking') {
          return html`
            <details key=${i} className="claude-thinking">
              <summary>💭 Thinking</summary>
              <div className="thinking-content">${act.text}</div>
            </details>
          `;
        } else if (act.type === 'text') {
          return html`
            <div key=${i} className="claude-text">${act.text}</div>
          `;
        } else if (act.type === 'tool') {
          const shortArgs = typeof act.args === 'string'
            ? act.args.slice(0, 80)
            : act.args ? JSON.stringify(act.args).slice(0, 80) : '';
          return html`
            <div key=${i} className="tool-card ${act.running ? 'running' : act.ok ? 'success' : 'failed'}">
              <div className="tool-card-header">
                <span className="tool-status-icon">
                  ${act.running ? html`<span className="spinner-icon-sm"></span>` : act.ok ? '✓' : '✗'}
                </span>
                <span className="tool-name">${act.toolName}</span>
                ${act.attempt ? html`<span className="tool-attempt">att ${act.attempt}</span>` : null}
                ${!act.running ? html`
                  <span className="tool-meta">
                    ${act.duration_s != null ? `${act.duration_s}s · ` : ''}exit ${act.exit_code}
                  </span>
                ` : null}
              </div>
              ${shortArgs ? html`<div className="tool-args">${shortArgs}</div>` : null}
              ${(act.error || act.stdout) ? html`
                <details className="tool-details">
                  <summary>output / stderr</summary>
                  <pre>${(act.error || act.stdout).slice(-500)}</pre>
                </details>
              ` : null}
            </div>
          `;
        } else if (act.type === 'vision_check') {
          const isDone = act.state === 'done';
          return html`
            <div key=${i} className="vision-row ${isDone ? (act.verdict === 'ok' ? 'pass' : 'fail') : 'checking'}">
              <span className="vision-img">${act.image}</span>
              <span className="vision-verdict">${isDone ? act.verdict : 'checking...'}</span>
              ${act.text ? html`<span className="vision-text">${act.text}</span>` : null}
            </div>
          `;
        }
        return null;
      })}
    </div>
  `;
}

export function WorkerSlots({
  tasks,
  onApprovePlan,
  onRevisePlan,
  onCancelTask,
  onPreviewFile
}) {
  const [feedbackMap, setFeedbackMap] = useState({});

  const handleFeedbackChange = (taskId, text) => {
    setFeedbackMap(prev => ({ ...prev, [taskId]: text }));
  };

  const handleRevise = (taskId) => {
    const text = feedbackMap[taskId] || '';
    if (!text.trim()) {
      alert('Please enter revision feedback.');
      return;
    }
    onRevisePlan(taskId, text.trim());
    handleFeedbackChange(taskId, '');
  };

  const slotOrder = ['task_1', 'task_2', 'task_3'];

  return html`
    <div className="workers-section">
      <div className="section-headline">
        <div className="headline-text">
          <span>Worker Sandboxes</span>
          <span className="pill-badge" style=${{ background: '#e2e8f0', color: '#334155' }}>
            3 Isolated Docker Containers
          </span>
        </div>
      </div>

      <div style=${{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
        ${slotOrder.map((taskId, idx) => {
          const task = tasks[taskId] || {
            status: 'idle',
            question: 'Slot idle — awaiting task assignment',
            step: 'Ready',
            elapsed: 0,
            plan: null,
            artifacts: [],
            attempt: null,
            activities: []
          };

          const isRunning = task.status === 'running';
          const isPendingApproval = task.status === 'pending_approval';

          // De-duplicate deliverables by URL before rendering
          const uniqueArtifacts = [];
          const seenUrls = new Set();
          (task.artifacts || []).forEach(art => {
            if (art && art.url && !seenUrls.has(art.url)) {
              seenUrls.add(art.url);
              uniqueArtifacts.push(art);
            }
          });

          // Latest real event text truncated, never fixed string
          const headerStep = task.step
            ? (task.step.length > 70 ? task.step.slice(0, 67) + '...' : task.step)
            : (isRunning ? 'Running...' : 'Ready');

          return html`
            <div
              key=${taskId}
              className="worker-card ${isRunning ? 'active-run' : ''} ${isPendingApproval ? 'review-gate' : ''}"
            >
              <div className="card-topbar">
                <div className="card-slot-title">
                  <span className="slot-name">CONTAINER #${idx + 1}</span>
                  ${task.attempt ? html`<span className="attempt-pill">attempt ${task.attempt} of 15</span>` : null}
                  <span className="slot-timer">${formatSeconds(task.elapsed)}</span>
                </div>
                <span className="status-pill ${task.status}">
                  ${task.status.replace('_', ' ')}
                </span>
              </div>

              <div className="card-query-banner">
                <div style=${{
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  fontWeight: 500
                }}>
                  ${task.question}
                </div>
              </div>

              <div className="human-progress-bar">
                ${isRunning ? html`<span className="spinner-icon"></span>` : null}
                <span style=${{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  ${headerStep}
                </span>
              </div>

              <${TaskActivityFeed} activities=${task.activities} />

              ${isPendingApproval && task.plan ? html`
                <div className="plan-review-box">
                  <div className="plan-review-header">
                    <span>⚠️ Proposed Plan — Review Required</span>
                    <span style=${{ fontSize: '10px', fontFamily: 'var(--font-mono)' }}>GATE</span>
                  </div>
                  <div className="plan-code-view">${task.plan}</div>
                  <input
                    className="feedback-input"
                    placeholder="Enter change request (e.g. use Otsu thresholding, save GeoTIFF)..."
                    value=${feedbackMap[taskId] || ''}
                    onInput=${(e) => handleFeedbackChange(taskId, e.target.value)}
                  />
                  <div style=${{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick=${() => handleRevise(taskId)}
                    >
                      ↺ Request Changes
                    </button>
                    <button
                      className="btn btn-success btn-sm"
                      onClick=${() => onApprovePlan(taskId)}
                    >
                      ✓ Approve & Execute
                    </button>
                  </div>
                </div>
              ` : null}

              ${uniqueArtifacts.length > 0 ? html`
                <div className="artifacts-shelf">
                  <span style=${{ fontSize: '11px', color: '#64748b', fontWeight: 600 }}>Deliverables:</span>
                  ${uniqueArtifacts.map((art) => {
                    const isTif = art.ext === '.tif' || art.ext === '.tiff';
                    const isImg = art.type === 'image';

                    if (isTif) {
                      return html`
                        <button
                          key=${art.name}
                          className="artifact-btn"
                          onClick=${() => onPreviewFile(art.url, art.name, 'tif')}
                          title="Click to preview GeoTIFF"
                        >
                          🗺️ ${art.name} <span style=${{ color: '#2563eb', fontWeight: 700 }}>Preview</span>
                        </button>
                      `;
                    } else if (isImg) {
                      return html`
                        <button
                          key=${art.name}
                          className="artifact-btn"
                          onClick=${() => onPreviewFile(art.url, art.name, 'image')}
                          title="Click to preview Map Image"
                        >
                          📊 ${art.name}
                        </button>
                      `;
                    } else {
                      return html`
                        <a
                          key=${art.name}
                          href=${art.url}
                          download
                          className="artifact-btn"
                          title="Download file"
                        >
                          📁 ${art.name}
                        </a>
                      `;
                    }
                  })}
                </div>
              ` : null}

              <div className="card-footer">
                <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#94a3b8' }}>
                  geollm_${taskId}
                </span>
                <button
                  className="btn btn-outline-danger btn-sm"
                  disabled=${task.status === 'idle' || task.status === 'done' || task.status === 'failed'}
                  onClick=${() => onCancelTask(taskId)}
                >
                  ✕ Abort
                </button>
              </div>
            </div>
          `;
        })}
      </div>
    </div>
  `;
}

function formatSeconds(secs) {
  if (!secs) return '00:00';
  const m = Math.floor(secs / 60).toString().padStart(2, '0');
  const s = Math.floor(secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

