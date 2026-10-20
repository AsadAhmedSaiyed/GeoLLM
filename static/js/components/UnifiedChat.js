// Astryx Unified Multi-Agent Chat & Progress Console
import { html, React } from '/static/js/html.js';
import { IconSparkles, IconUser, IconRocket } from '/static/js/icons.js';
const { useState, useEffect, useRef } = React;

export function UnifiedChat({
  feedItems = [],
  onSendMessage,
  onDispatchProposedJob,
  onClearChat,
  onNotify
}) {
  const [inputText, setInputText] = useState('');
  const [confirmClear, setConfirmClear] = useState(false);
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
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    onClearChat();
    setConfirmClear(false);
    if (onNotify) onNotify('Feed cleared', 'info');
  };

  return html`
    <div className="chat-console-card">
      <div className="chat-console-header">
        <div className="chat-console-title">
          <${IconSparkles} size=${15} className="sparkle-icon" />
          <span className="console-title-text">Supervisor Console & Feed</span>
          <span className="pill-badge unified-badge">Unified</span>
        </div>

        <button
          className="btn btn-secondary btn-xs btn-clear-feed"
          onClick=${handleClear}
          type="button"
          title="Clear supervisor feed"
        >
          ${confirmClear ? 'Confirm Clear?' : 'Clear'}
        </button>
      </div>

      <div className="unified-feed" role="log" aria-live="polite">
        ${feedItems.length === 0 ? html`
          <div className="feed-empty-state">
            Multi-task timeline and supervisor chat will appear here.
          </div>
        ` : feedItems.map((item, idx) => {
          if (item.taskId) {
            const tagClass = item.taskId === 'task_1' ? 't1' : item.taskId === 'task_2' ? 't2' : 't3';
            const taskLabel = item.taskId === 'task_1' ? 'Sandbox #1' : item.taskId === 'task_2' ? 'Sandbox #2' : 'Sandbox #3';

            let eventContent = '';
            if (item.type === 'tool_start') {
              eventContent = `Tool execution: ${item.toolName} (pass ${item.attempt || 1})`;
            } else if (item.type === 'tool_end') {
              eventContent = `Tool completed: ${item.toolName || 'task'} (${item.ok ? 'success' : 'failed'}, exit ${item.exit_code}, ${item.duration_s || 0}s)`;
            } else if (item.type === 'vision_check') {
              eventContent = `Vision inspection [${item.image}]: ${item.state === 'started' ? 'Analyzing map artifact...' : `${item.verdict === 'ok' ? 'Verified' : 'Defect found'}${item.text ? ' — ' + item.text : ''}`}`;
            } else if (item.type === 'plan_ready') {
              eventContent = 'Analysis plan drafted — awaiting operator review';
            } else if (item.type === 'finish') {
              eventContent = `Task ${item.status.toUpperCase()}: ${item.error || 'Execution finished successfully'}`;
            } else {
              eventContent = item.text || '';
            }

            return html`
              <div key=${idx} className="event-row">
                <span className="task-tag ${tagClass}">${taskLabel}</span>
                <span className="event-text">${eventContent}</span>
              </div>
            `;
          } else if (item.type === 'user') {
            return html`
              <div key=${idx} className="chat-item user">
                <div className="sender-label">
                  <${IconUser} size=${12} />
                  <span>Operator</span>
                </div>
                <div className="msg-bubble">${item.text}</div>
              </div>
            `;
          } else if (item.type === 'assistant') {
            return html`
              <div key=${idx} className="chat-item assistant">
                <div className="sender-label">
                  <${IconSparkles} size=${12} />
                  <span>Supervisor Agent</span>
                </div>
                <div className="msg-bubble">${item.text}</div>
                ${item.proposedJob ? html`
                  <div className="proposed-job-action">
                    <button
                      className="btn btn-primary btn-sm btn-dispatch"
                      onClick=${() => onDispatchProposedJob(item.proposedJob)}
                      type="button"
                    >
                      <${IconRocket} size=${12} />
                      <span>Dispatch Proposed Analysis</span>
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
          placeholder="Ask supervisor agent about any sandbox or dataset..."
          value=${inputText}
          onInput=${(e) => setInputText(e.target.value)}
          onKeyDown=${handleKeyDown}
          aria-label="Supervisor chat message"
        />
        <button
          className="btn btn-primary btn-sm btn-send-chat"
          onClick=${handleSend}
          disabled=${!inputText.trim()}
          type="button"
        >
          Send
        </button>
      </div>
    </div>
  `;
}
