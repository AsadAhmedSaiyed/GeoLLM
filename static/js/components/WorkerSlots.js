// GeoLLM Task Cards / Worker Slots Component (Refined layout, no step bar, markdown output)
import { html, React } from '/static/js/html.js';
import { MarkdownView } from '/static/js/components/MarkdownView.js?v=20261020';
const { useState, useRef } = React;

function TaskActivityFeed({ activities }) {
  const feedRef = useRef(null);
  const [isOpen, setIsOpen] = useState(false);

  const relevantActivities = (activities || []).filter(act => {
    if (act.type === 'vision_check' && act.state === 'started') return false;
    return true;
  });

  if (relevantActivities.length === 0) return null;

  return html`
    <div style=${{ marginTop: '8px' }}>
      <button
        type="button"
        className="btn s"
        style=${{ fontSize: '11px', padding: '0 8px', height: '24px', color: '#4B5B54' }}
        onClick=${() => setIsOpen(!isOpen)}
      >
        ${isOpen ? 'Hide execution details' : `View execution details (${relevantActivities.length} events)`}
      </button>

      ${isOpen ? html`
        <div className="worker-activity-feed" ref=${feedRef} style=${{ marginTop: '6px' }}>
          ${relevantActivities.map((act, i) => {
            if (act.type === 'thinking') {
              return html`
                <details key=${i} className="claude-thinking">
                  <summary className="mono" style=${{ fontSize: '11px', cursor: 'pointer', color: '#4B5B54' }}>
                    Reasoning log
                  </summary>
                  <div className="mono" style=${{ whiteSpace: 'pre-wrap', fontSize: '10.5px', marginTop: '4px', color: '#5B6B64', wordBreak: 'break-word' }}>
                    ${act.text}
                  </div>
                </details>
              `;
            } else if (act.type === 'text') {
              return html`
                <div key=${i} className="activity-markdown" style=${{ padding: '6px 0', borderTop: '1px solid #EAECE8' }}>
                  <${MarkdownView} content=${act.text} />
                </div>
              `;
            } else if (act.type === 'tool') {
              const shortArgs = typeof act.args === 'string'
                ? act.args
                : act.args ? JSON.stringify(act.args) : '';

              return html`
                <div key=${i} className="tool-card ${act.running ? 'run' : act.ok ? 'ok' : 'bad'}">
                  <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11.5px', flexWrap: 'wrap' }}>
                    <span className="mono" style=${{ fontWeight: 600 }}>${act.toolName}</span>
                    ${act.attempt ? html`<span className="mono" style=${{ fontSize: '10px', color: '#5B6B64' }}>att ${act.attempt}</span>` : null}
                    <span className="mono" style=${{ marginLeft: 'auto', fontSize: '10.5px', color: '#5B6B64' }}>
                      ${act.duration_s != null ? `${act.duration_s}s · ` : ''}exit ${act.exit_code}
                    </span>
                  </div>
                  ${shortArgs ? html`
                    <div className="mono" style=${{ fontSize: '10.5px', color: '#5B6B64', wordBreak: 'break-all', overflowWrap: 'anywhere', marginTop: '2px' }}>
                      ${shortArgs.length > 200 ? shortArgs.slice(0, 197) + '...' : shortArgs}
                    </div>
                  ` : null}
                  ${(act.error || act.stdout) ? html`
                    <details style=${{ marginTop: '4px', fontSize: '10.5px' }}>
                      <summary style=${{ cursor: 'pointer', color: '#4B5B54' }}>Output</summary>
                      <pre className="mono" style=${{ margin: '4px 0', padding: '6px 8px', background: '#F8F9F7', borderRadius: '4px', overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: '180px' }}>${(act.error || act.stdout).slice(-1200)}</pre>
                    </details>
                  ` : null}
                </div>
              `;
            } else if (act.type === 'vision_check') {
              const imgName = act.image ? act.image.split(/[\\/]/).pop() : 'image';
              const isOk = act.verdict === 'ok';
              const isBad = act.verdict === 'needs_revision';
              return html`
                <div key=${i} className="tool-card ${isOk ? 'ok' : isBad ? 'bad' : 'ok'}" style=${{ padding: '6px 8px' }}>
                  <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
                    <span className="mono" style=${{ fontWeight: 600 }}>Visual QA: ${imgName}</span>
                    <span className="mono" style=${{ marginLeft: 'auto', fontSize: '10.5px', color: '#5B6B64' }}>
                      ${act.verdict || 'checked'}
                    </span>
                  </div>
                  ${act.text && act.text !== 'ok' ? html`
                    <div style=${{ fontSize: '10.5px', color: '#4B5B54', marginTop: '4px', whiteSpace: 'pre-wrap' }}>${act.text}</div>
                  ` : null}
                </div>
              `;
            }
            return null;
          })}
        </div>
      ` : null}
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
      if (onNotify) onNotify('Please enter revision feedback.', 'warning');
      return;
    }
    onRevisePlan(taskId, text.trim());
    handleFeedbackChange(taskId, '');
    if (onNotify) onNotify(`Revision request sent to Task #${taskId.slice(-1)}`, 'info');
  };

  const formatSeconds = (task) => {
    if (task.status === 'idle') return 'Not started';
    if (!task.elapsed) return '00:00';
    const total = Math.floor(task.elapsed);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const slotOrder = ['task_1', 'task_2', 'task_3'];

  // Count active vs done
  const activeCount = Object.values(tasks).filter(t => t.status === 'running' || t.status === 'pending_approval').length;
  const doneCount = Object.values(tasks).filter(t => t.status === 'done').length;

  return html`
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div className="sec">
        <span>Tasks · 3 sandboxes</span>
        <span style=${{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
          ${activeCount > 0 ? `${activeCount} running · ` : ''}${doneCount} done
        </span>
      </div>

      ${slotOrder.map((taskId, idx) => {
        const taskNum = idx + 1;
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

        // Title derivation
        let taskTitle = `Task #${taskNum}`;
        if (task.question && task.question !== 'Slot idle — awaiting task assignment') {
          const qFirst = task.question.split('.')[0].trim();
          taskTitle = qFirst.length > 40 ? qFirst.slice(0, 38) + '...' : qFirst;
        }

        // Unique artifacts
        const uniqueArtifacts = [];
        const seenUrls = new Set();
        (task.artifacts || []).forEach(art => {
          if (art && art.url && !seenUrls.has(art.url)) {
            seenUrls.add(art.url);
            uniqueArtifacts.push(art);
          }
        });

        // Determine if question has markdown
        const hasMarkdown = task.question && (task.question.includes('**') || task.question.includes('#') || task.question.includes('|'));

        return html`
          <article key=${taskId} className="card tc">
            <div className="hd">
              <span className="num">${taskNum}</span>
              <span className="ttl">${taskTitle}</span>

              ${isDone ? html`<span className="pill ok">Done</span>` : null}
              ${isRunning ? html`<span className="pill run">Running</span>` : null}
              ${isPendingApproval ? html`<span className="pill run">Review gate</span>` : null}
              ${isFailed ? html`<span className="pill bad">Failed</span>` : null}
              ${task.status === 'idle' ? html`<span className="pill" style=${{ background: '#F3F4F1', color: '#5B6B64' }}>Idle</span>` : null}

              <span className="sp"></span>
              <span className="mono" style=${{ fontSize: '12px', color: '#4B5B54' }}>
                ${formatSeconds(task)}
              </span>
            </div>

            <div className="q-container">
              ${hasMarkdown ? html`
                <${MarkdownView} content=${task.question} className="q-markdown" />
              ` : html`
                <p className="q">${task.question}</p>
              `}
            </div>

            <div className="meta">
              ${task.attempt ? html`<span>Attempt ${task.code_attempt || task.attempt} of ${task.max_attempts || 4}</span>` : null}
              ${task.status === 'idle' ? html`<span>Waiting for assignment</span>` : null}
              ${task.step && task.status !== 'idle' ? html`<span style=${{ wordBreak: 'break-word' }}>${task.step}</span>` : null}
              ${uniqueArtifacts.length > 0 ? html`<span><b>${uniqueArtifacts.length}</b> deliverables ready</span>` : null}
            </div>

            <!-- Deliverable File Chips -->
            <div className="files">
              ${uniqueArtifacts.length === 0 ? html`
                <span style=${{ fontSize: '12px', color: '#5B6B64', fontStyle: 'italic' }}>
                  ${isRunning ? 'Generating raster maps & data...' : 'No files produced yet'}
                </span>
              ` : uniqueArtifacts.map(art => {
                const isTif = art.ext === '.tif' || art.ext === '.tiff';
                const isImg = art.type === 'image' || art.name.endsWith('.png');

                return html`
                  <span key=${art.name} className="f mono">
                    <span className="f-name" title=${art.name}>${art.name}</span>
                    ${(isTif || isImg) ? html`
                      <u onClick=${() => onPreviewFile(art.url, art.name, isTif ? 'tif' : 'image')}>Preview</u>
                    ` : null}
                  </span>
                `;
              })}
            </div>

            <!-- Actions Row -->
            <div className="act">
              ${uniqueArtifacts.some(a => a.ext === '.tif' || a.ext === '.tiff' || a.type === 'image' || a.name.endsWith('.png')) ? html`
                <button
                  type="button"
                  className="btn s"
                  onClick=${() => {
                    const firstPreview = uniqueArtifacts.find(a => a.ext === '.tif' || a.ext === '.tiff' || a.type === 'image' || a.name.endsWith('.png'));
                    if (firstPreview) {
                      const isTif = firstPreview.ext === '.tif' || firstPreview.ext === '.tiff';
                      onPreviewFile(firstPreview.url, firstPreview.name, isTif ? 'tif' : 'image');
                    }
                  }}
                >
                  Open on map
                </button>
              ` : null}

              ${uniqueArtifacts.length > 0 ? html`
                <button
                  type="button"
                  className="btn s"
                  onClick=${() => {
                    uniqueArtifacts.forEach(art => {
                      const a = document.createElement('a');
                      a.href = art.url;
                      a.download = art.name;
                      document.body.appendChild(a);
                      a.click();
                      document.body.removeChild(a);
                    });
                    if (onNotify) onNotify(`Downloading ${uniqueArtifacts.length} deliverables`, 'info');
                  }}
                >
                  Download all
                </button>
              ` : null}

              ${(isRunning || isPendingApproval) ? html`
                ${confirmCancelTaskId === taskId ? html`
                  <div style=${{ display: 'inline-flex', gap: '6px', alignItems: 'center' }}>
                    <span style=${{ fontSize: '12px', color: '#991B1B' }}>Confirm stop?</span>
                    <button
                      className="btn s d"
                      type="button"
                      onClick=${() => {
                        onCancelTask(taskId);
                        setConfirmCancelTaskId(null);
                        if (onNotify) onNotify(`Cancelled Task #${taskNum}`, 'warning');
                      }}
                    >
                      Yes, stop
                    </button>
                    <button
                      className="btn s"
                      type="button"
                      onClick=${() => setConfirmCancelTaskId(null)}
                    >
                      Keep
                    </button>
                  </div>
                ` : html`
                  <button
                    className="btn s d"
                    type="button"
                    onClick=${() => setConfirmCancelTaskId(taskId)}
                  >
                    Abort
                  </button>
                `}
              ` : null}
            </div>

            <!-- Plan Review Approval Gate -->
            ${isPendingApproval && task.plan ? html`
              <div style=${{ marginTop: '10px', padding: '12px', background: '#FEF9EE', border: '1px solid #FDE68A', borderRadius: '8px' }}>
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style=${{ fontSize: '12.5px', fontWeight: 600, color: '#92400E' }}>
                    Proposed Plan — Review Required
                  </span>
                  <span className="mono" style=${{ fontSize: '10px', background: '#FEF3C7', color: '#92400E', padding: '2px 6px', borderRadius: '4px' }}>
                    GATE
                  </span>
                </div>

                <div className="mono" style=${{ fontSize: '11px', background: '#fff', border: '1px solid #DCE1DB', padding: '8px', borderRadius: '6px', maxHeight: '140px', overflowY: 'auto', whiteSpace: 'pre-wrap', color: '#14201C', wordBreak: 'break-word' }}>
                  ${task.plan}
                </div>

                <input
                  type="text"
                  placeholder="Enter change request (e.g. use Otsu thresholding, export GeoTIFF)..."
                  value=${feedbackMap[taskId] || ''}
                  onInput=${(e) => handleFeedbackChange(taskId, e.target.value)}
                  style=${{ width: '100%', height: '32px', margin: '8px 0', border: '1px solid #C9D1CB', borderRadius: '6px', padding: '0 8px', fontSize: '12px' }}
                />

                <div style=${{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  <button
                    className="btn s"
                    onClick=${() => handleRevise(taskId)}
                    type="button"
                  >
                    Request changes
                  </button>
                  <button
                    className="btn s"
                    style=${{ background: '#0F766E', color: '#fff', borderColor: '#0F766E' }}
                    onClick=${() => {
                      onApprovePlan(taskId);
                      if (onNotify) onNotify(`Approved execution for Task #${taskNum}`, 'success');
                    }}
                    type="button"
                  >
                    Approve & execute
                  </button>
                </div>
              </div>
            ` : null}

            <!-- Expandable execution details -->
            <${TaskActivityFeed} activities=${task.activities} />
          </article>
        `;
      })}
    </div>
  `;
}
