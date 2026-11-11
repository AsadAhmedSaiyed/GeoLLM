import React, { useState, useEffect, useRef } from 'react';
import { api } from '@/services/api';
import { ArtifactItem } from '@/types/sse';
import { MarkdownView } from '@/components/MarkdownView';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Bot,
  X,
  Send,
  Zap,
  MessageSquare,
  Activity,
  BarChart3,
  Package,
  Loader2,
} from 'lucide-react';

export interface SupervisorFeedItem {
  id?: string | number;
  type: string;
  taskId?: string;
  text?: string;
  step?: string;
  status?: string;
  toolName?: string;
  args?: unknown;
  attempt?: number;
  ok?: boolean;
  exit_code?: number;
  duration_s?: number;
  error?: string | null;
  image?: string;
  state?: string;
  verdict?: string;
  plan?: string;
  artifacts?: Array<string | ArtifactItem>;
  meta?: unknown;
  timestamp?: string;
}

interface ChatEntry {
  role: 'user' | 'assistant';
  content: string;
  isRunJob?: boolean;
  proposedJob?: string;
}

export interface SupervisorDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  feedItems: SupervisorFeedItem[];
  onDispatchTask?: (question: string) => void;
}

export const SupervisorDrawer: React.FC<SupervisorDrawerProps> = ({
  isOpen,
  onClose,
  feedItems = [],
  onDispatchTask,
}) => {
  const [messages, setMessages] = useState<ChatEntry[]>([
    {
      role: 'assistant',
      content:
        '**Supervisor AI Online.** I oversee all 3 Docker worker sandboxes and coordinate geospatial queries. You can ask for status updates, explore satellite collections, or ask me to dispatch a new analysis job.',
    },
  ]);
  const [inputVal, setInputVal] = useState('');
  const [sending, setSending] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState<'chat' | 'telemetry'>('chat');
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const isChatUserScrolledUp = useRef(false);

  const handleChatWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (e.deltaY < 0) {
      isChatUserScrolledUp.current = true;
    }
  };

  const handleChatScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom <= 24) {
      isChatUserScrolledUp.current = false;
    } else if (distanceToBottom > 40) {
      isChatUserScrolledUp.current = true;
    }
  };

  useEffect(() => {
    if (!chatScrollRef.current || isChatUserScrolledUp.current) return;
    const el = chatScrollRef.current;
    const rafId = requestAnimationFrame(() => {
      if (el && !isChatUserScrolledUp.current) {
        el.scrollTop = el.scrollHeight;
      }
    });
    return () => cancelAnimationFrame(rafId);
  }, [messages, feedItems, activeSubTab]);

  const handleSendMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const query = inputVal.trim();
    if (!query || sending) return;

    setInputVal('');
    const userMsg: ChatEntry = { role: 'user', content: query };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setSending(true);

    try {
      const data = await api.sendChatMessage(
        query,
        updated.map((m) => ({ role: m.role, content: m.content }))
      );

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
        {
          role: 'assistant',
          content: `⚠️ Error contacting Supervisor: ${
            err instanceof Error ? err.message : String(err)
          }`,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  if (!isOpen) return null;

  const dynamicFeedItems = feedItems.filter((item) => {
    if (!item.taskId && item.type === 'assistant') return false;
    return true;
  });

  return (
    <aside className="fixed top-12 right-0 bottom-0 w-96 max-w-full z-40 bg-[#0B0F17] border-l border-[#1E293B] flex flex-col shadow-2xl text-slate-100 select-none">
      {/* Drawer Header */}
      <div className="px-4 py-3 border-b border-[#1E293B] bg-[#0F172A] flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="relative flex items-center justify-center">
            <Bot className="h-4 w-4 text-purple-400" />
            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400" />
          </div>
          <div>
            <div className="font-semibold text-xs text-slate-100">Supervisor AI</div>
            <div className="text-[10.5px] text-slate-400">
              Container Intelligence & Dispatch
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="flex bg-[#111827] border border-[#1E293B] rounded-md p-0.5">
            <button
              type="button"
              onClick={() => setActiveSubTab('chat')}
              className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors ${
                activeSubTab === 'chat'
                  ? 'bg-[#1E293B] text-sky-400'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <MessageSquare className="h-3 w-3" />
              <span>Chat</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveSubTab('telemetry')}
              className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors ${
                activeSubTab === 'telemetry'
                  ? 'bg-[#1E293B] text-sky-400'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Activity className="h-3 w-3" />
              <span>Feed ({dynamicFeedItems.length})</span>
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-[#1E293B] cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Drawer Content */}
      <div
        ref={chatScrollRef}
        onWheel={handleChatWheel}
        onScroll={handleChatScroll}
        className="flex-1 overflow-y-auto p-3.5 space-y-2.5 select-text scroll-smooth"
        style={{ overscrollBehavior: 'contain' }}
      >
        {activeSubTab === 'chat' ? (
          <div className="space-y-3">
            {messages.map((m, idx) => (
              <div
                key={idx}
                className={`flex ${
                  m.role === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                <div
                  className={`max-w-[85%] rounded-lg p-2.5 text-xs ${
                    m.role === 'user'
                      ? 'bg-[#0F766E] text-white'
                      : 'bg-[#111827] border border-[#1E293B] text-slate-200'
                  }`}
                >
                  <MarkdownView content={m.content} />

                  {m.isRunJob && m.proposedJob && (
                    <div className="mt-2 pt-2 border-t border-[#1E293B]">
                      <Button
                        type="button"
                        size="sm"
                        variant="teal"
                        className="w-full h-7 text-[11px] gap-1"
                        onClick={() => onDispatchTask?.(m.proposedJob!)}
                      >
                        <Zap className="h-3 w-3" />
                        <span>Dispatch Job to Available Sandbox</span>
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {sending && (
              <div className="flex justify-start">
                <div className="bg-[#111827] border border-[#1E293B] rounded-lg px-3 py-2 text-xs text-slate-400 flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-400" />
                  <span>Supervisor analyzing…</span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {dynamicFeedItems.length === 0 ? (
              <div className="py-8 px-4 text-center text-slate-500 text-xs">
                No task events yet — run an analysis task to stream live progress.
              </div>
            ) : (
              dynamicFeedItems.slice(-60).map((item, idx) => {
                const taskTag = item.taskId
                  ? item.taskId === 'task_1'
                    ? '#1'
                    : item.taskId === 'task_2'
                    ? '#2'
                    : '#3'
                  : 'SYS';
                const isErr =
                  item.ok === false ||
                  (item.type === 'finish' && item.status === 'failed');

                let content = '';
                let isMarkdown = false;

                if (item.type === 'text') {
                  content = item.text || '';
                  isMarkdown = true;
                } else if (item.type === 'thinking') {
                  const words = item.text
                    ? item.text.trim().split(/\s+/).filter(Boolean).length
                    : 0;
                  const snippet = (item.text || '').replace(/\s+/g, ' ').trim();
                  content = `🧠 Reasoning (${words} words): ${
                    snippet.length > 140 ? `…${snippet.slice(-140)}` : snippet
                  }`;
                } else if (item.type === 'tool_start') {
                  content = `🛠️ Running tool \`${item.toolName || 'tool'}\`${
                    item.attempt ? ` (attempt ${item.attempt})` : ''
                  }…`;
                  isMarkdown = true;
                } else if (item.type === 'tool_end') {
                  const statusIcon = item.ok !== false ? '✅' : '❌';
                  const dur = item.duration_s != null ? `${item.duration_s}s · ` : '';
                  content = `${statusIcon} Tool \`${
                    item.toolName || 'execution'
                  }\` finished (${dur}exit ${item.exit_code ?? 0})${
                    item.ok === false && item.error
                      ? ` — ${String(item.error).slice(0, 120)}`
                      : ''
                  }`;
                  isMarkdown = true;
                } else if (item.type === 'progress' || item.type === 'milestone') {
                  content = item.text || '';
                  if (
                    content.includes('**') ||
                    content.includes('#') ||
                    content.includes('\n')
                  ) {
                    isMarkdown = true;
                  }
                } else if (item.type === 'plan_ready') {
                  content = '📋 Analysis plan drafted — awaiting operator review';
                } else if (item.type === 'finish') {
                  content =
                    item.status === 'done'
                      ? '🏁 Task completed successfully — all deliverables verified'
                      : `🔴 Task ended (${item.status}): ${
                          item.error || 'Execution stopped'
                        }`;
                } else if (item.type === 'vision_check') {
                  const imgName = item.image
                    ? item.image.split(/[/\\]/).pop()
                    : 'image';
                  if (item.state === 'started') {
                    content = `👁️ Visual QA started: analyzing ${imgName}…`;
                  } else {
                    content = `👁️ Visual QA [${imgName}]: ${
                      item.verdict || 'checked'
                    }${item.text ? ` — ${item.text}` : ''}`;
                    if (content.includes('\n') || content.includes(';')) {
                      isMarkdown = true;
                    }
                  }
                } else if (item.type === 'artifacts') {
                  const arts = item.artifacts || [];
                  const names = arts
                    .map((a) =>
                      typeof a === 'string'
                        ? a.split(/[/\\]/).pop()
                        : a.name || 'file'
                    )
                    .join(', ');
                  content = `📦 ${arts.length} deliverable${
                    arts.length !== 1 ? 's' : ''
                  } ready${names ? `: ${names}` : ''}`;
                } else if (item.type === 'status') {
                  content = item.text || item.step || item.status || '';
                } else {
                  content = item.text || item.step || '';
                }

                if (!content || !content.trim()) return null;

                return (
                  <div
                    key={idx}
                    className={`flex items-start gap-2 p-2 rounded border text-xs ${
                      isErr
                        ? 'bg-rose-500/10 border-rose-500/30 text-rose-200'
                        : 'bg-[#111827] border-[#1E293B] text-slate-200'
                    }`}
                  >
                    <span className="font-mono text-[10px] font-bold bg-[#1E293B] text-sky-400 px-1.5 py-0.5 rounded shrink-0">
                      {taskTag}
                    </span>
                    <div className="flex-1 min-w-0 break-words">
                      {isMarkdown ? (
                        <MarkdownView content={content} />
                      ) : (
                        <span>{content}</span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* Quick Suggested Status Inquiries */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-[#070A0F] border-t border-[#1E293B] overflow-x-auto">
        <button
          type="button"
          onClick={() =>
            setInputVal('Give me a full status report of all active containers.')
          }
          className="flex items-center gap-1 bg-[#111827] hover:bg-[#1E293B] border border-[#1E293B] text-slate-300 text-[10.5px] px-2.5 py-1 rounded-full cursor-pointer whitespace-nowrap"
        >
          <BarChart3 className="h-3 w-3 text-sky-400" />
          <span>Container Status</span>
        </button>
        <button
          type="button"
          onClick={() =>
            setInputVal(
              'Explain the deliverables and scientific findings completed so far.'
            )
          }
          className="flex items-center gap-1 bg-[#111827] hover:bg-[#1E293B] border border-[#1E293B] text-slate-300 text-[10.5px] px-2.5 py-1 rounded-full cursor-pointer whitespace-nowrap"
        >
          <Package className="h-3 w-3 text-teal-400" />
          <span>Explain Findings</span>
        </button>
      </div>

      {/* Drawer Footer Input */}
      <form
        onSubmit={handleSendMessage}
        className="p-3 bg-[#0F172A] border-t border-[#1E293B] flex items-center gap-2"
      >
        <Input
          type="text"
          placeholder="Ask supervisor or type 'run: <analysis>'…"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          disabled={sending}
          className="flex-1 h-8 text-xs"
        />
        <Button
          type="submit"
          size="icon"
          variant="teal"
          disabled={sending || !inputVal.trim()}
          className="h-8 w-8 shrink-0"
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      </form>
    </aside>
  );
};

