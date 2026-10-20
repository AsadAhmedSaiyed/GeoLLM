// Astryx Worker Sandbox Slots Component (Balanced 3-Container Grid Deck)
import { html, React } from '/static/js/html.js';
import {
  IconLayers,
  IconImage,
  IconFileText,
  IconDownload,
  IconCheck,
  IconX,
  IconAlertTriangle,
  IconRefresh,
  IconStopCircle,
  IconEye
} from '/static/js/icons.js';
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
              <summary className="thinking-summary">
                <span className="thinking-dot"></span>
                <span>Sub-agent Reasoning</span>
              </summary>
              <div className="thinking-content">${act.text}</div>
            </details>
          `;
        } else if (act.type === 'text') {
          return html`
            <div key=${i} className="claude-text">${act.text}</div>
          `;
        } else if (act.type === 'tool') {
          const shortArgs = typeof act.args === 'string'
            ? act.args.slice(0, 90)
            : act.args ? JSON.stringify(act.args).slice(0, 90) : '';

          return html`
            <div key=${i} className="tool-card ${act.running ? 'running' : act.ok ? 'success' : 'failed'}">
              <div className="tool-card-header">
                <span className="tool-status-icon">
                  ${act.running ? html`<span className="spinner-icon-sm"></span>` : act.ok ? html`<${IconCheck} size=${12} />` : html`<${IconX} size=${12} />`}
                </span>
                <span className="tool-name">${act.toolName}</span>
                ${act.attempt ? html`<span className="tool-attempt">pass ${act.attempt}</span>` : null}
                ${!act.running ? html`
                  <span className="tool-meta">
                    ${act.duration_s != null ? `${act.duration_s}s · ` : ''}exit ${act.exit_code}
                  </span>
                ` : null}
              </div>
              ${shortArgs ? html`<div className="tool-args">${shortArgs}</div>` : null}
              ${(act.error || act.stdout) ? html`
                <details className="tool-details">
                  <summary>Console Output</summary>
                  <pre>${(act.error || act.stdout).slice(-500)}</pre>
                </details>
              ` : null}
            </div>
          `;
        } else if (act.type === 'vision_check') {
          const isDone = act.state === 'done';
          return html`
            <div key=${i} className="vision-row ${isDone ? (act.verdict === 'ok' ? 'pass' : 'fail') : 'checking'}">
              <div className="vision-header">
                <${IconEye} size=${12} />
                <span className="vision-img">${act.image}</span>
                <span className="vision-verdict ${act.verdict === 'ok' ? 'ok' : 'review'}">
                  ${isDone ? (act.verdict === 'ok' ? 'VERIFIED' : 'DEFECTS DETECTED') : 'ANALYZING...'}
                </span>
              </div>
              ${act.text ? html`<div className="vision-text">${act.text}</div>` : null}
            </div>
          `;
        }
        return null;
      })}
    </div>
  `;
}

export function WorkerSlots({
  tasks = {},
  onApprovePlan,
  onRevisePlan,
  onCancelTask,
  onPreviewFile,
  onNotify
}) {
  const [feedbackMap, setFeedbackMap] = useState({});
  const [confirmCancelTaskId, setConfirmCancelTaskId] = useState(null);

  const handleFeedbackChange = (taskId, text) => {
    setFeedbackMap(prev => ({ ...prev, [taskId]: text }));
  };

  const handleRevise = (taskId) => {
    const text = feedbackMap[taskId] || '';
    if (!text.trim()) {
      if (onNotify) {
        onNotify('Please describe your proposed plan adjustments before requesting changes.', 'warning');
      }
      return;
    }
    onRevisePlan(taskId, text.trim());
    handleFeedbackChange(taskId, '');
    if (onNotify) {
      onNotify(`Revision request sent to Container #${taskId.slice(-1)}`, 'info');
    }
  };

  const slotOrder = ['task_1', 'task_2', 'task_3'];

  const formatSeconds = (sec) => {
    if (!sec || isNaN(sec)) return '00:00';
    const total = Math.floor(sec);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return html`
    <div className="workers-section">
      <div className="section-headline">
        <div className="headline-text">
          <span className="headline-title">Sandbox Worker Deck</span>
          <span className="pill-badge sandbox-badge">
            3 Isolated Docker Sandboxes
          </span>
        </div>
      </div>

      <div className="workers-grid">
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
          const isDone = task.status === 'done';
          const isFailed = task.status === 'failed';
          const isPartial = task.status === 'partial';

          // De-duplicate deliverables by URL before rendering
          const uniqueArtifacts = [];
          const seenUrls = new Set();
          (task.artifacts || []).forEach(art => {
            if (art && art.url && !seenUrls.has(art.url)) {
              seenUrls.add(art.url);
              uniqueArtifacts.push(art);
            }
          });

          // Truncated progress text
          const headerStep = task.step
            ? (task.step.length > 70 ? task.step.slice(0, 67) + '...' : task.step)
            : (isRunning ? 'Processing pipeline...' : 'Ready');

          return html`
            <div
              key=${taskId}
              className="worker-card ${isRunning ? 'active-run' : ''} ${isPendingApproval ? 'review-gate' : ''} ${isDone ? 'finished' : ''}"
            >
              <div className="card-topbar">
                <div className="card-slot-title">
                  <span className="slot-name">SANDBOX #${idx + 1}</span>
                  ${task.attempt ? html`<span className="attempt-pill">Pass ${task.attempt}/15</span>` : null}
                  <span className="slot-timer">${formatSeconds(task.elapsed)}</span>
                </div>

                <span className="status-pill status-${task.status}">
                  ${isRunning ? html`<span className="spinner-icon-xs"></span>` : null}
                  ${isDone ? html`<${IconCheck} size=${11} />` : null}
                  ${isPendingApproval ? html`<${IconAlertTriangle} size=${11} />` : null}
                  <span className="status-text">${task.status.replace('_', ' ')}</span>
                </span>
              </div>

              <div className="card-query-banner">
                <div className="card-query-text" title=${task.question}>
                  ${task.question}
                </div>
              </div>

              <div className="human-progress-bar">
                ${isRunning ? html`<span className="spinner-icon-sm"></span>` : null}
                <span className="progress-step-text">
                  ${headerStep}
                </span>
              </div>

              <div className="card-body-scrollable">
                <${TaskActivityFeed} activities=${task.activities} />

                ${isPendingApproval && task.plan ? html`
                  <div className="plan-review-box">
                    <div className="plan-review-header">
                      <div className="plan-review-title">
                        <${IconAlertTriangle} size=${14} />
                        <span>Proposed Analysis Plan</span>
                      </div>
                      <span className="plan-gate-tag">REVIEW GATE</span>
                    </div>

                    <div className="plan-code-view">${task.plan}</div>

                    <input
                      className="feedback-input"
                      placeholder="Enter change request (e.g. use Otsu thresholding, save GeoTIFF)..."
                      value=${feedbackMap[taskId] || ''}
                      onInput=${(e) => handleFeedbackChange(taskId, e.target.value)}
                    />

                    <div className="plan-btn-row">
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick=${() => handleRevise(taskId)}
                        type="button"
                      >
                        <${IconRefresh} size=${12} />
                        <span>Request Changes</span>
                      </button>
                      <button
                        className="btn btn-success btn-sm"
                        onClick=${() => {
                          onApprovePlan(taskId);
                          if (onNotify) onNotify(`Plan approved for Sandbox #${idx + 1}. Execution started.`, 'success');
                        }}
                        type="button"
                      >
                        <${IconCheck} size=${12} />
                        <span>Approve & Execute</span>
                      </button>
                    </div>
                  </div>
                ` : null}

                ${uniqueArtifacts.length > 0 ? html`
                  <div className="artifacts-shelf">
                    <span className="artifacts-shelf-title">Deliverables (${uniqueArtifacts.length}):</span>
                    <div className="artifacts-list">
                      ${uniqueArtifacts.map((art) => {
                        const isTif = art.ext === '.tif' || art.ext === '.tiff';
                        const isImg = art.type === 'image';

                        if (isTif) {
                          return html`
                            <button
                              key=${art.name}
                              className="artifact-btn artifact-tif"
                              onClick=${() => onPreviewFile(art.url, art.name, 'tif')}
                              title="Click to preview GeoTIFF with band analysis"
                              type="button"
                            >
                              <${IconLayers} size=${13} />
                              <span className="artifact-name">${art.name}</span>
                              <span className="artifact-action-tag">Preview</span>
                            </button>
                          `;
                        } else if (isImg) {
                          return html`
                            <button
                              key=${art.name}
                              className="artifact-btn artifact-img"
                              onClick=${() => onPreviewFile(art.url, art.name, 'image')}
                              title="Click to view full-resolution map"
                              type="button"
                            >
                              <${IconImage} size=${13} />
                              <span className="artifact-name">${art.name}</span>
                            </button>
                          `;
                        } else {
                          return html`
                            <a
                              key=${art.name}
                              href=${art.url}
                              download
                              className="artifact-btn artifact-file"
                              title="Download data deliverable"
                            >
                              <${IconFileText} size=${13} />
                              <span className="artifact-name">${art.name}</span>
                              <${IconDownload} size=${11} />
                            </a>
                          `;
                        }
                      })}
                    </div>
                  </div>
                ` : null}
              </div>

              <div className="card-footer-action">
                <span className="container-id-tag">container: geollm_${taskId}</span>

                ${(isRunning || isPendingApproval) ? html`
                  ${confirmCancelTaskId === taskId ? html`
                    <div className="confirm-abort-row">
                      <span className="confirm-abort-prompt">Stop task?</span>
                      <button
                        className="btn btn-danger btn-xs"
                        onClick=${() => {
                          onCancelTask(taskId);
                          setConfirmCancelTaskId(null);
                          if (onNotify) onNotify(`Cancelled task in Sandbox #${idx + 1}`, 'warning');
                        }}
                        type="button"
                      >
                        Yes, Stop
                      </button>
                      <button
                        className="btn btn-secondary btn-xs"
                        onClick=${() => setConfirmCancelTaskId(null)}
                        type="button"
                      >
                        Keep
                      </button>
                    </div>
                  ` : html`
                    <button
                      className="btn btn-outline-danger btn-xs btn-abort"
                      onClick=${() => setConfirmCancelTaskId(taskId)}
                      title="Cancel active execution in this sandbox"
                      type="button"
                    >
                      <${IconStopCircle} size=${12} />
                      <span>Abort</span>
                    </button>
                  `}
                ` : html`
                  <span className="slot-idle-indicator">
                    ${isDone ? 'Execution completed' : isFailed ? 'Execution failed' : 'Slot standby'}
                  </span>
                `}
              </div>
            </div>
          `;
        })}
      </div>
    </div>
  `;
}
