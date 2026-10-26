import { html, React } from '../html.js';
import { MarkdownView } from './MarkdownView.js';

const { useState, useEffect, useRef } = React;

export function SupervisorDrawer({
  isOpen,
  onClose,
  feedItems = [],
  onDispatchTask,
}) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        '**Supervisor AI Online.** I oversee all 3 Docker worker sandboxes and coordinate geospatial queries. You can ask for status updates, explore satellite collections, or ask me to dispatch a new analysis job.',
    },
  ]);
  const [inputVal, setInputVal] = useState('');
  const [sending, setSending] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState('chat'); // 'chat' or 'telemetry'
  const chatScrollRef = useRef(null);

  // Auto-scroll chat to bottom
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [messages, feedItems, activeSubTab]);

  const handleSendMessage = async (e) => {
    e?.preventDefault();
    const query = inputVal.trim();
    if (!query || sending) return;

    setInputVal('');
    const userMsg = { role: 'user', content: query };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setSending(true);

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: query,
          history: updated.map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || 'Supervisor chat error');
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.reply || '(No response)',
          isRunJob: data.is_run_job,
          proposedJob: data.proposed_job,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `⚠️ Error contacting Supervisor: ${err.message}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  if (!isOpen) return null;

  const dynamicFeedItems = feedItems.filter((item) => {
    if (!item.taskId && item.type === 'assistant') return false;
    // Skip raw tool invocation execution spam (no hardcoded passes)
    if (item.type === 'tool_start' || item.type === 'tool_end') return false;
    return true;
  });

  return html`
    <aside className="supervisor-drawer-container">
      <!-- Drawer Header -->
      <div className="supervisor-drawer-header">
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div className="supervisor-status-dot"></div>
          <div>
            <div style=${{ fontWeight: 600, fontSize: '13px', color: '#E2ECE6' }}>Supervisor AI</div>
            <div style=${{ fontSize: '10.5px', color: '#8FA39A' }}>Container Intelligence & Dispatch</div>
          </div>
        </div>

        <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div className="subtab-toggle">
            <button
              type="button"
              className="subtab-btn ${activeSubTab === 'chat' ? 'active' : ''}"
              onClick=${() => setActiveSubTab('chat')}
            >
              Chat
            </button>
            <button
              type="button"
              className="subtab-btn ${activeSubTab === 'telemetry' ? 'active' : ''}"
              onClick=${() => setActiveSubTab('telemetry')}
            >
              Feed (${dynamicFeedItems.length})
            </button>
          </div>
          <button type="button" className="drawer-close-btn" onClick=${onClose}>×</button>
        </div>
      </div>

      <!-- Drawer Content -->
      <div ref=${chatScrollRef} className="supervisor-drawer-content">
        ${activeSubTab === 'chat' ? html`
          <div className="chat-messages-stream">
            ${messages.map((m, idx) => html`
              <div key=${idx} className="chat-bubble-row ${m.role}">
                <div
                  className="chat-bubble ${m.role}"
                  style=${{
                    color: m.role === 'user' ? '#FFFFFF' : '#E2ECE6',
                    backgroundColor: m.role === 'user' ? '#0F766E' : '#182620',
                    border: m.role === 'user' ? 'none' : '1px solid #283C32'
                  }}
                >
                  <${MarkdownView} content=${m.content} className="markdown-chat" />

                  ${m.isRunJob && m.proposedJob ? html`
                    <div style=${{ marginTop: '8px', paddingTop: '6px', borderTop: '1px solid #2A3831' }}>
                      <button
                        type="button"
                        className="dispatch-job-btn"
                        onClick=${() => onDispatchTask && onDispatchTask(m.proposedJob)}
                      >
                        ⚡ Dispatch Job to Available Sandbox
                      </button>
                    </div>
                  ` : null}
                </div>
              </div>
            `)}

            ${sending ? html`
              <div className="chat-bubble-row assistant">
                <div className="chat-bubble assistant thinking" style=${{ color: '#E2ECE6' }}>
                  <span className="dot-flashing"></span>
                  <span style=${{ marginLeft: '8px', fontSize: '11px', color: '#8FA39A' }}>Supervisor analyzing…</span>
                </div>
              </div>
            ` : null}
          </div>
        ` : html`
          <!-- Dynamic Natural Language Telemetry Feed -->
          <div className="telemetry-feed-stream">
            ${dynamicFeedItems.length === 0 ? html`
              <div style=${{ padding: '24px 16px', textAlign: 'center', color: '#8FA39A', fontSize: '11.5px' }}>
                No task events yet — run an analysis task to stream live progress.
              </div>
            ` : dynamicFeedItems.slice(-60).map((item, idx) => {
              const taskTag = item.taskId
                ? (item.taskId === 'task_1' ? '#1' : item.taskId === 'task_2' ? '#2' : '#3')
                : 'SYS';
              const taskTagClass = item.taskId
                ? (item.taskId === 'task_1' ? 'task-1' : item.taskId === 'task_2' ? 'task-2' : 'task-3')
                : 'sys';
              const isErr = item.ok === false || (item.type === 'finish' && item.status === 'failed');

              let content = '';
              let isMarkdown = false;

              if (item.type === 'text') {
                content = item.text || '';
                isMarkdown = true;
              } else if (item.type === 'progress' || item.type === 'milestone') {
                content = item.text || '';
                if (content.includes('**') || content.includes('#') || content.includes('\n')) isMarkdown = true;
              } else if (item.type === 'plan_ready') {
                content = '📋 Analysis plan drafted — awaiting operator review';
              } else if (item.type === 'finish') {
                content = item.status === 'done'
                  ? '🏁 Task completed successfully — all deliverables verified'
                  : `🔴 Task ended (${item.status}): ${item.error || 'Execution stopped'}`;
              } else if (item.type === 'vision_check') {
                const imgName = item.image ? item.image.split(/[/\\]/).pop() : 'image';
                if (item.state === 'started') {
                  content = `👁️ Visual QA started: analyzing ${imgName}…`;
                } else {
                  content = `👁️ Visual QA [${imgName}]: ${item.verdict || 'checked'}${item.text ? ' — ' + item.text : ''}`;
                  if (content.includes('\n') || content.includes(';')) isMarkdown = true;
                }
              } else if (item.type === 'artifacts') {
                const arts = item.artifacts || [];
                const names = arts.map(a => typeof a === 'string' ? a.split(/[/\\]/).pop() : (a.name || 'file')).join(', ');
                content = `📦 ${arts.length} deliverable${arts.length !== 1 ? 's' : ''} ready${names ? ': ' + names : ''}`;
              } else if (item.type === 'status') {
                content = item.text || item.step || item.status || '';
              } else {
                content = item.text || item.step || '';
                if (!content) return null;
              }

              if (!content || !content.trim()) return null;

              return html`
                <div key=${idx} className="telemetry-log-item ${isErr ? 'error' : ''}" style=${{ color: isErr ? '#FCA5A5' : '#E2ECE6' }}>
                  <span className="log-tag mono ${taskTagClass}">${taskTag}</span>
                  <div className="log-text" style=${{ flex: 1, minWidth: 0, color: isErr ? '#FCA5A5' : '#E2ECE6' }}>
                    ${isMarkdown ? html`
                      <${MarkdownView} content=${content} className="markdown-chat" />
                    ` : html`
                      <span style=${{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>${content}</span>
                    `}
                  </div>
                </div>
              `;
            })}
          </div>
        `}
      </div>

      <!-- Quick Suggested Status Inquiries -->
      <div style=${{ display: 'flex', gap: '6px', padding: '6px 10px', background: '#121A16', overflowX: 'auto', borderTop: '1px solid #1C2822' }}>
        <button
          type="button"
          onClick=${() => { setInputVal('Give me a full status report of all active containers.'); }}
          style=${{ background: '#1B2A23', border: '1px solid #2A3E34', color: '#9EC7B3', fontSize: '10px', padding: '3px 8px', borderRadius: '12px', cursor: 'pointer', whiteSpace: 'nowrap' }}
        >
          📊 Container Status
        </button>
        <button
          type="button"
          onClick=${() => { setInputVal('Explain the deliverables and scientific findings completed so far.'); }}
          style=${{ background: '#1B2A23', border: '1px solid #2A3E34', color: '#9EC7B3', fontSize: '10px', padding: '3px 8px', borderRadius: '12px', cursor: 'pointer', whiteSpace: 'nowrap' }}
        >
          📦 Explain Findings
        </button>
      </div>

      <!-- Drawer Footer Input -->
      <form onSubmit=${handleSendMessage} className="supervisor-drawer-footer">
        <input
          type="text"
          className="supervisor-input mono"
          placeholder="Ask supervisor or type 'run: <analysis>'…"
          value=${inputVal}
          onChange=${(e) => setInputVal(e.target.value)}
          disabled=${sending}
        />
        <button type="submit" className="supervisor-send-btn" disabled=${sending || !inputVal.trim()}>
          ➤
        </button>
      </form>
    </aside>
  `;
}
