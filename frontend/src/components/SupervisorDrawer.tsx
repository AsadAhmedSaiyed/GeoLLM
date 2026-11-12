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
  }, [messages, sending]);

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const txt = inputVal.trim();
    if (!txt || sending) return;

    const userEntry: ChatEntry = { role: 'user', content: txt };
    const updatedMessages = [...messages, userEntry];
    setMessages(updatedMessages);
    setInputVal('');
    setSending(true);

    try {
      const history = updatedMessages.map((m) => ({
        role: m.role,
        content: m.content,
      }));
      const res = await api.sendChatMessage(txt, history);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.reply || 'No response received from supervisor.',
          isRunJob: res.is_run_job,
          proposedJob: res.proposed_job,
        },
      ]);
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `⚠️ Failed to reach supervisor AI: ${
            err instanceof Error ? err.message : String(err)
          }`,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const dynamicFeedItems = feedItems.filter((item) => {
    if (!item.taskId && item.type === 'assistant') return false;
    return true;
  });

  if (!isOpen) return null;

  return (
    <aside className="fixed top-12 right-0 bottom-0 w-96 max-w-full z-40 bg-card border-l border-border flex flex-col shadow-2xl text-foreground select-none">
      {/* Drawer Header */}
      <div className="px-4 py-3 border-b border-border bg-card flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="relative flex items-center justify-center">
            <Bot className="h-4 w-4 text-purple-400" />
            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-none bg-emerald-400" />
          </div>
          <div>
            <div className="font-semibold text-xs text-foreground">Supervisor AI</div>
            <div className="text-[10.5px] text-muted-foreground">
              Container Intelligence & Dispatch
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="flex bg-muted border border-border rounded-none p-0.5">
            <button
              type="button"
              onClick={() => setActiveSubTab('chat')}
              className={`flex items-center gap-1 px-2 py-1 rounded-none text-[11px] font-medium cursor-pointer transition-colors ${
                activeSubTab === 'chat'
                  ? 'bg-background text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <MessageSquare className="h-3 w-3" />
              <span>Chat</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveSubTab('telemetry')}
              className={`flex items-center gap-1 px-2 py-1 rounded-none text-[11px] font-medium cursor-pointer transition-colors ${
                activeSubTab === 'telemetry'
                  ? 'bg-background text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Activity className="h-3 w-3" />
              <span>Feed ({dynamicFeedItems.length})</span>
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-none text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
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
                  className={`max-w-[85%] rounded-none p-2.5 text-xs ${
                    m.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted border border-border text-foreground'
                  }`}
                >
                  <MarkdownView content={m.content} />

                  {m.isRunJob && m.proposedJob && (
                    <div className="mt-2 pt-2 border-t border-border">
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
                <div className="bg-muted border border-border rounded-none px-3 py-2 text-xs text-muted-foreground flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                  <span>Supervisor analyzing…</span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {dynamicFeedItems.length === 0 ? (
              <div className="py-8 px-4 text-center text-muted-foreground text-xs">
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
                    className={`flex items-start gap-2 p-2 rounded-none border text-xs ${
                      isErr
                        ? 'bg-destructive/15 border-destructive/30 text-destructive'
                        : 'bg-muted border-border text-foreground'
                    }`}
                  >
                    <span className="font-mono text-[10px] font-bold bg-background text-primary px-1.5 py-0.5 rounded-none border border-border shrink-0">
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
      <div className="flex items-center gap-1.5 px-3 py-2 bg-card border-t border-border overflow-x-auto">
        <button
          type="button"
          onClick={() =>
            setInputVal('Give me a full status report of all active containers.')
          }
          className="flex items-center gap-1 bg-muted hover:bg-background border border-border text-foreground text-[10.5px] px-2.5 py-1 rounded-none cursor-pointer whitespace-nowrap"
        >
          <BarChart3 className="h-3 w-3 text-primary" />
          <span>Container Status</span>
        </button>
        <button
          type="button"
          onClick={() =>
            setInputVal(
              'Explain the deliverables and scientific findings completed so far.'
            )
          }
          className="flex items-center gap-1 bg-muted hover:bg-background border border-border text-foreground text-[10.5px] px-2.5 py-1 rounded-none cursor-pointer whitespace-nowrap"
        >
          <Package className="h-3 w-3 text-[#14B8A6]" />
          <span>Explain Findings</span>
        </button>
      </div>

      {/* Drawer Footer Input */}
      <form
        onSubmit={handleSendMessage}
        className="p-3 bg-card border-t border-border flex items-center gap-2"
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
