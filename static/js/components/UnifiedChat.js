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
          if (item.taskId) {
            const tagClass = item.taskId === 'task_1' ? 't1' : item.taskId === 'task_2' ? 't2' : 't3';
            const taskLabel = item.taskId === 'task_1' ? 'Container #1' : item.taskId === 'task_2' ? 'Container #2' : 'Container #3';

            let eventContent = '';
            if (item.type === 'tool_start') {
              eventContent = `Tool: ${item.toolName} (attempt ${item.attempt || 1})`;
            } else if (item.type === 'tool_end') {
              eventContent = `Tool ${item.ok ? 'succeeded ✓' : 'failed ✗'} (exit ${item.exit_code}, ${item.duration_s || 0}s)`;
            } else if (item.type === 'vision_check') {
              eventContent = `Vision [${item.image}]: ${item.state === 'started' ? 'Inspecting map...' : `${item.verdict}${item.text ? ' - ' + item.text : ''}`}`;
            } else if (item.type === 'plan_ready') {
              eventContent = 'Analysis plan proposed — review required';
            } else if (item.type === 'finish') {
              eventContent = `Task ${item.status.toUpperCase()}: ${item.error || 'Completed'}`;
            } else {
              eventContent = item.text || '';
            }

            return html`
              <div key=${idx} className="event-row">
                <span className="task-tag ${tagClass}">${taskLabel}</span>
                <span style=${{ flex: 1, wordBreak: 'break-word' }}>${eventContent}</span>
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

