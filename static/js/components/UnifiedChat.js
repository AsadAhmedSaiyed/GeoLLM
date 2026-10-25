// GeoLLM Unified Chat Component (Refined with Markdown rendering and clean layout)
import { html, React } from '/static/js/html.js';
import { MarkdownView } from '/static/js/components/MarkdownView.js?v=20261020';
const { useState, useEffect, useRef } = React;

export function UnifiedChat({
  feedItems = [],
  onSendMessage,
  onDispatchProposedJob,
  onClearChat,
  onNotify
}) {
  const [inputText, setInputText] = useState('');
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

  const getTimeString = (item) => {
    if (item.timestamp) return item.timestamp;
    const d = new Date();
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  };

  // Strip long system paths for clean display
  const cleanPath = (p) => {
    if (!p || typeof p !== 'string') return '';
    const parts = p.split(/[/\\]/);
    return parts[parts.length - 1];
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

      <div className="log" ref=${logRef} role="log" aria-live="polite">
        ${feedItems.length === 0 ? html`
          <div style=${{ padding: '24px 16px', textAlign: 'center', color: '#5B6B64', fontSize: '12px' }}>
            Feed is empty · Run a task or send a message to begin.
          </div>
        ` : feedItems.map((item, idx) => {
          const time = getTimeString(item);

          if (item.taskId) {
            const taskTag = item.taskId === 'task_1' ? '#1' : item.taskId === 'task_2' ? '#2' : '#3';
            const isError = item.type === 'tool_end' && !item.ok;

            let eventText = '';
            let isMarkdownEvent = false;

            if (item.type === 'tool_start') {
              eventText = `Tool invocation: ${item.toolName} (attempt ${item.attempt || 1})`;
            } else if (item.type === 'tool_end') {
              const durText = item.duration_s != null ? `${item.duration_s}s` : '0s';
              eventText = item.ok
                ? `Tool ${item.toolName || 'task'} finished (exit ${item.exit_code}, ${durText})`
                : `Tool ${item.toolName || 'task'} failed (exit ${item.exit_code}, ${durText})`;
            } else if (item.type === 'plan_ready') {
              eventText = 'Analysis plan proposed — review required.';
            } else if (item.type === 'finish') {
              eventText = `Task finished (${item.status}): ${item.error || 'All deliverables ready'}`;
            } else if (item.type === 'vision_check') {
              const imgName = cleanPath(item.image) || 'map image';
              const progressStr = (item.index && item.total) ? ` (${item.index}/${item.total})` : '';

              if (item.state === 'started') {
                eventText = `Visual check started: inspecting ${imgName}${progressStr}...`;
              } else {
                const verdict = item.verdict || (item.text === 'ok' ? 'ok' : 'checked');
                if (verdict === 'ok') {
                  eventText = `Visual check passed: ${imgName}${progressStr} (ok)`;
                } else if (verdict === 'needs_revision') {
                  const rawText = item.text || 'Revision required';
                  const bulletPoints = rawText.includes(';')
                    ? rawText.split(';').map(s => s.trim()).filter(Boolean).map(s => `\n- ${s}`).join('')
                    : `\n- ${rawText.trim()}`;
                  eventText = `**Visual check flagged issues for \`${imgName}\`${progressStr}:**${bulletPoints}`;
                  isMarkdownEvent = true;
                } else if (verdict === 'skipped') {
                  eventText = `Visual check skipped for ${imgName}${progressStr}: ${item.text || 'skipped'}`;
                } else {
                  eventText = `Visual check [${imgName}${progressStr}]: ${verdict}${item.text && item.text !== verdict ? ` — ${item.text}` : ''}`;
                  if (eventText.includes(';') || eventText.includes('\n')) {
                    isMarkdownEvent = true;
                  }
                }
              }
            } else {
              eventText = item.text || '';
              // Detect markdown elements like headers, tables, bold, lists
              if (eventText.includes('#') || eventText.includes('|') || eventText.includes('**') || eventText.includes('\n- ') || eventText.includes('`')) {
                isMarkdownEvent = true;
              }
            }

            if (!eventText || !eventText.trim()) {
              return null;
            }

            return html`
              <div key=${idx} className="lg ${isError ? 'e' : ''}">
                <time className="mono">${time}</time>
                <em className="mono">${taskTag}</em>
                <div className="event-body">
                  ${isMarkdownEvent ? html`
                    <${MarkdownView} content=${eventText} className="markdown-chat" />
                  ` : html`
                    <span style=${{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>${eventText}</span>
                  `}
                </div>
              </div>
            `;
          } else if (item.type === 'user') {
            return html`
              <div key=${idx} className="msg u">
                <b>You · ${time}</b>
                <p style=${{ wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>${item.text}</p>
              </div>
            `;
          } else if (item.type === 'assistant') {
            return html`
              <div key=${idx} className="msg a">
                <b>Main LLM · ${time}</b>
                <div className="msg-content">
                  <${MarkdownView} content=${item.text} className="markdown-chat" />
                </div>
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
