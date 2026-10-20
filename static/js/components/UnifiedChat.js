// GeoLLM Unified Chat Component (Styled from design/reference.html)
import { html, React } from '/static/js/html.js';
const { useState, useEffect, useRef, useMemo } = React;

export function UnifiedChat({
  feedItems = [],
  onSendMessage,
  onDispatchProposedJob,
  onClearChat,
  onNotify
}) {
  const [inputText, setInputText] = useState('');
  const [filter, setFilter] = useState('Everything');
  const [target, setTarget] = useState('Main LLM');
  const [confirmClear, setConfirmClear] = useState(false);
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [feedItems]);

  const handleSend = () => {
    if (!inputText.trim()) return;
    const msg = target === 'Main LLM' ? inputText.trim() : `[@${target}] ${inputText.trim()}`;
    onSendMessage(msg);
    setInputText('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickPrompt = (text) => {
    setInputText(text);
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

  // Filter feed items
  const filteredFeed = useMemo(() => {
    return feedItems.filter(item => {
      if (filter === 'Everything') return true;
      const isMsg = item.type === 'user' || item.type === 'assistant';
      if (filter === 'Chat only') return isMsg;
      if (filter === '#1') return item.taskId === 'task_1';
      if (filter === '#2') return item.taskId === 'task_2';
      if (filter === '#3') return item.taskId === 'task_3';
      return true;
    });
  }, [feedItems, filter]);

  const getTimeString = (item) => {
    if (item.timestamp) return item.timestamp;
    const d = new Date();
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  };

  return html`
    <aside className="con">
      <div className="ch">
        <span>Unified chat</span>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="tag" style=${{ background: '#16312C', color: '#7DD3C8' }}>
            Main LLM connected
          </span>
          <button
            type="button"
            className="btn s"
            onClick=${handleClear}
            style=${{ background: '#16201B', borderColor: '#2A3831', color: '#8FA39A', fontSize: '11px', height: '24px', padding: '0 8px' }}
            title="Clear chat feed"
          >
            ${confirmClear ? 'Confirm clear?' : 'Clear'}
          </button>
        </div>
      </div>

      <div className="mt">
        Talk to the main LLM, or send a message to one task. Task updates stream into the same thread.
      </div>

      <div className="seg">
        <button
          className=${filter === 'Everything' ? 'on' : ''}
          onClick=${() => setFilter('Everything')}
          type="button"
        >
          Everything
        </button>
        <button
          className=${filter === 'Chat only' ? 'on' : ''}
          onClick=${() => setFilter('Chat only')}
          type="button"
        >
          Chat only
        </button>
        <button
          className=${filter === '#1' ? 'on' : ''}
          onClick=${() => setFilter('#1')}
          type="button"
        >
          #1
        </button>
        <button
          className=${filter === '#2' ? 'on' : ''}
          onClick=${() => setFilter('#2')}
          type="button"
        >
          #2
        </button>
        <button
          className=${filter === '#3' ? 'on' : ''}
          onClick=${() => setFilter('#3')}
          type="button"
        >
          #3
        </button>
      </div>

      <div className="log" ref=${logRef} role="log" aria-live="polite">
        ${filteredFeed.length === 0 ? html`
          <div style=${{ padding: '24px 16px', textAlign: 'center', color: '#5B6B64', fontSize: '12px' }}>
            No updates in this view.
          </div>
        ` : filteredFeed.map((item, idx) => {
          const time = getTimeString(item);

          if (item.taskId) {
            const taskTag = item.taskId === 'task_1' ? '#1' : item.taskId === 'task_2' ? '#2' : '#3';
            const isError = item.type === 'tool_end' && !item.ok;

            let eventText = '';
            if (item.type === 'tool_start') {
              eventText = `Tool invocation: ${item.toolName} (attempt ${item.attempt || 1})`;
            } else if (item.type === 'tool_end') {
              eventText = item.ok
                ? `Tool ${item.toolName || 'task'} finished (exit ${item.exit_code}, ${item.duration_s || 0}s)`
                : `Tool ${item.toolName || 'task'} failed (exit ${item.exit_code}, ${item.duration_s || 0}s)`;
            } else if (item.type === 'vision_check') {
              eventText = `Map QA [${item.image}]: ${item.state === 'started' ? 'Inspecting raster...' : `${item.verdict === 'ok' ? 'Passed' : 'Defect detected'}${item.text ? ' — ' + item.text : ''}`}`;
            } else if (item.type === 'plan_ready') {
              eventText = 'Analysis plan proposed — review required.';
            } else if (item.type === 'finish') {
              eventText = `Task finished (${item.status}): ${item.error || 'All deliverables ready'}`;
            } else {
              eventText = item.text || '';
            }

            return html`
              <div key=${idx} className="lg ${isError ? 'e' : ''}">
                <time className="mono">${time}</time>
                <em className="mono">${taskTag}</em>
                <span>${eventText}</span>
              </div>
            `;
          } else if (item.type === 'user') {
            return html`
              <div key=${idx} className="msg u">
                <b>You · ${time}</b>
                <p>${item.text}</p>
              </div>
            `;
          } else if (item.type === 'assistant') {
            return html`
              <div key=${idx} className="msg a">
                <b>Main LLM · ${time}</b>
                <p>${item.text}</p>
                ${item.proposedJob ? html`
                  <div style=${{ marginTop: '8px' }}>
                    <button
                      className="btn s p"
                      onClick=${() => onDispatchProposedJob(item.proposedJob)}
                      type="button"
                      style=${{ height: '28px', fontSize: '11.5px' }}
                    >
                      Dispatch proposed analysis
                    </button>
                  </div>
                ` : null}
              </div>
            `;
          }
          return null;
        })}
      </div>

      <div className="cb">
        <div className="qs">
          <button
            type="button"
            onClick=${() => handleQuickPrompt('Summarise all tasks')}
          >
            Summarise all tasks
          </button>
          <button
            type="button"
            onClick=${() => handleQuickPrompt('Explain the last failure')}
          >
            Explain the last failure
          </button>
          <button
            type="button"
            onClick=${() => handleQuickPrompt('Compare #1 and #3')}
          >
            Compare #1 and #3
          </button>
        </div>

        <textarea
          aria-label="Message"
          placeholder="Message the main LLM about any task, dataset or result"
          value=${inputText}
          onInput=${(e) => setInputText(e.target.value)}
          onKeyDown=${handleKeyDown}
        />

        <div className="cr">
          <select
            aria-label="Send to"
            value=${target}
            onChange=${(e) => setTarget(e.target.value)}
          >
            <option value="Main LLM">To: Main LLM</option>
            <option value="Task #1">To: Task #1</option>
            <option value="Task #2">To: Task #2</option>
            <option value="Task #3">To: Task #3</option>
          </select>

          <div className="sp"></div>

          <span className="mono" style=${{ fontSize: '11px', color: '#8FA39A' }}>
            Enter to send
          </span>

          <button
            className="btn p"
            onClick=${handleSend}
            disabled=${!inputText.trim()}
            type="button"
            style=${{ height: '34px', padding: '0 18px' }}
          >
            Send
          </button>
        </div>
      </div>
    </aside>
  `;
}
