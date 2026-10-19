// Astryx Unified Multi-Agent Chat & Progress Console
import { html, React } from '/static/js/html.js';
const { useState, useEffect, useRef } = React;

export function UnifiedChat({
  feedItems,
  onSendMessage,
  onDispatchProposedJob,
  onClearChat
}) {
  const [inputText, setInputText] = useState('');
  const feedEndRef = useRef(null);

  useEffect(() => {
    if (feedEndRef.current) {
      feedEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [feedItems]);

  const handleSend = () => {
    if (!inputText.trim()) return;
    onSendMessage(inputText.trim());
    setInputText('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

  return html`
    <div className="chat-console-card">
      <div className="chat-console-header">
        <div className="chat-console-title">
          <span>Supervisor Console & Multi-Task Feed</span>
          <span className="pill-badge" style=${{ background: '#334155', color: '#38bdf8' }}>
            Unified
          </span>
        </div>
        <button
          className="btn btn-secondary btn-sm"
          style=${{ padding: '2px 8px', fontSize: '10px' }}
          onClick=${onClearChat}
        >
          Clear
        </button>
      </div>

      <div className="unified-feed">
        ${feedItems.length === 0 ? html`
          <div style=${{ textAlign: 'center', color: '#64748b', fontSize: '12px', marginTop: '20px' }}>
            Multi-task timeline and supervisor chat will appear here.
          </div>
        ` : feedItems.map((item, idx) => {
          if (item.type === 'progress') {
            const tagClass = item.taskId === 'task_1' ? 't1' : item.taskId === 'task_2' ? 't2' : 't3';
            const taskLabel = item.taskId === 'task_1' ? 'Container #1' : item.taskId === 'task_2' ? 'Container #2' : 'Container #3';

            return html`
              <div key=${idx} className="event-row">
                <span className="task-tag ${tagClass}">${taskLabel}</span>
                <span style=${{ flex: 1 }}>${humanizeProgress(item.text)}</span>
              </div>
            `;
          } else if (item.type === 'user') {
            return html`
              <div key=${idx} className="chat-item user">
                <span className="sender-label">👤 You</span>
                <div className="msg-bubble">${item.text}</div>
              </div>
            `;
          } else if (item.type === 'assistant') {
            return html`
              <div key=${idx} className="chat-item assistant">
                <span className="sender-label">🤖 Supervisor Agent</span>
                <div className="msg-bubble">${item.text}</div>
                ${item.proposedJob ? html`
                  <div style=${{ marginTop: '6px' }}>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick=${() => onDispatchProposedJob(item.proposedJob)}
                    >
                      🚀 Dispatch Proposed Analysis
                    </button>
                  </div>
                ` : null}
              </div>
            `;
          }
          return null;
        })}
        <div ref=${feedEndRef} />
      </div>

      <div className="chat-composer-row">
        <input
          className="chat-composer-input"
          placeholder="Ask supervisor agent about any container or dataset..."
          value=${inputText}
          onInput=${(e) => setInputText(e.target.value)}
          onKeyDown=${handleKeyDown}
        />
        <button className="btn btn-primary btn-sm" onClick=${handleSend}>
          Send
        </button>
      </div>
    </div>
  `;
}


/**
 * Converts raw engine log lines into natural, human-readable progress sentences.
 * The raw events come from pi_harness.py on_event() and step() calls.
 */
function humanizeProgress(rawText) {
  if (!rawText) return '';

  // Strip timestamps like [14:11:34]
  let text = rawText
    .replace(/\[\d{1,2}:\d{2}:\d{2}\]/g, '')
    .replace(/^\d{1,2}:\d{2}:\d{2}\s*/, '')
    .trim();

  // --- Exact pattern matches → natural language ---

  // "Pi is thinking" → "Analyzing the data and deciding next steps"
  if (/^Pi is thinking$/i.test(text)) {
    return 'Analyzing the data and deciding next steps';
  }

  // "Pi is reading data and drafting an analysis plan"
  if (/reading data and drafting/i.test(text)) {
    return 'Reading your datasets and drafting an analysis plan';
  }

  // "Pi running sandbox tool (call N)" → "Running analysis code (step N)"
  const toolCallMatch = text.match(/running sandbox tool \(call (\d+)\)/i);
  if (toolCallMatch) {
    const n = toolCallMatch[1];
    return `Running analysis code — step ${n} of the pipeline`;
  }

  // "Sandbox run finished (isError=False)" → "Code execution completed successfully"
  if (/sandbox run finished.*isError=False/i.test(text)) {
    return 'Code execution completed successfully';
  }

  // "Sandbox run finished (isError=True)" → "Code execution encountered an error"
  if (/sandbox run finished.*isError=True/i.test(text)) {
    return 'Code execution encountered an error — agent will attempt a fix';
  }

  // "Plan submitted — waiting for user approval"
  if (/plan submitted.*waiting for.*approval/i.test(text)) {
    return 'Analysis plan is ready — waiting for your approval';
  }

  // "Plan approved — running substantive code execution"
  if (/plan approved.*running.*code/i.test(text)) {
    return 'Plan approved — now executing the full analysis';
  }

  // "Plan approved — executing code"
  if (/plan approved.*executing/i.test(text)) {
    return 'Plan approved — executing the analysis code';
  }

  // "Plan auto-approved (CLI mode)"
  if (/plan auto-approved/i.test(text)) {
    return 'Plan auto-approved — starting full analysis';
  }

  // "First analysis finished"
  if (/first analysis finished/i.test(text)) {
    return 'Initial analysis complete — verifying outputs';
  }

  // "Vision model checking N map(s) (round M)"
  const visionCheckMatch = text.match(/vision.*checking (\d+) map.*round (\d+)/i);
  if (visionCheckMatch) {
    return `Quality-checking ${visionCheckMatch[1]} output map(s) — round ${visionCheckMatch[2]}`;
  }

  // "Vision check passed"
  if (/vision check passed/i.test(text)) {
    return 'All output maps passed quality inspection ✓';
  }

  // "Vision check warning: ..."
  const visionWarnMatch = text.match(/vision check warning:\s*(.+)/i);
  if (visionWarnMatch) {
    return `Quality check warning: ${visionWarnMatch[1]}`;
  }

  // "Pi fixing N map issue(s) (retry M/K)"
  const fixingMatch = text.match(/fixing (\d+) map issue.*retry (\d+)\/(\d+)/i);
  if (fixingMatch) {
    return `Fixing ${fixingMatch[1]} map issue(s) — attempt ${fixingMatch[2]} of ${fixingMatch[3]}`;
  }

  // "Revising plan (N/3): feedback..."
  const reviseMatch = text.match(/revising plan \((\d+)\/(\d+)\):\s*(.+)/i);
  if (reviseMatch) {
    return `Revising the plan based on your feedback (revision ${reviseMatch[1]})`;
  }

  // "Finished (ok)" / "Finished (failed)" / "Finished (partial)"
  const finishedMatch = text.match(/finished \((\w+)\)/i);
  if (finishedMatch) {
    const status = finishedMatch[1].toLowerCase();
    if (status === 'ok') return 'Analysis completed successfully — all outputs are ready';
    if (status === 'partial') return 'Analysis partially completed — some outputs may be incomplete';
    if (status === 'failed') return 'Analysis failed — check error details';
    return `Analysis finished with status: ${status}`;
  }

  // "Pi session problem: ..."
  const sessionMatch = text.match(/pi session problem:\s*(.+)/i);
  if (sessionMatch) {
    return `Session issue: ${sessionMatch[1]}`;
  }

  // "Task dispatched: ..."
  const dispatchMatch = text.match(/^Task dispatched:\s*"?(.+)"?$/i);
  if (dispatchMatch) {
    return `Task dispatched: "${dispatchMatch[1].slice(0, 70)}..."`;
  }

  // "Analysis plan proposed — review required"
  if (/analysis plan proposed/i.test(text)) {
    return 'Analysis plan proposed — review required';
  }

  // "Plan approved — executing code"
  if (/^Plan approved/i.test(text)) {
    return 'Plan approved — executing the analysis';
  }

  // "Task aborted by user"
  if (/aborted by user/i.test(text)) {
    return 'Task cancelled by user';
  }

  // "Task DONE: All deliverables ready"
  if (/task done.*deliverables/i.test(text)) {
    return 'Task complete — all deliverables are ready for download';
  }

  // "Task FAILED: ..."
  const failedMatch = text.match(/task failed:\s*(.+)/i);
  if (failedMatch) {
    return `Task failed: ${failedMatch[1]}`;
  }

  // --- Fallback: strip "Pi" prefix and capitalize ---
  text = text
    .replace(/\(isError=False\)/gi, 'succeeded')
    .replace(/\(isError=True\)/gi, 'failed');

  if (text.startsWith('Pi is ')) {
    text = text.slice(6);
  } else if (text.startsWith('Pi ')) {
    text = text.slice(3);
  }

  return text.charAt(0).toUpperCase() + text.slice(1);
}
