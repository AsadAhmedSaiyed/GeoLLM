import React, { useCallback, useMemo, useState } from 'react';
import { Renderer } from '@openuidev/react-lang';
import { openuiChatLibrary, ThemeProvider as OpenUIThemeProvider } from '@openuidev/react-ui';
import '@openuidev/react-ui/components.css';
import { MarkdownView } from './MarkdownView';
import { cn } from '@/lib/utils';

interface OpenUIRendererProps {
  content?: string | null;
  className?: string;
  isStreaming?: boolean;
  /** Called when a generated button / follow-up asks to continue the conversation. */
  onSendMessage?: (message: string) => void;
}

interface ParsedSegment {
  type: 'markdown' | 'openui';
  text: string;
}

// An OpenUI Lang program always defines `root = <Component>(...)`.
const ROOT_STATEMENT = /^\s*root\s*=\s*[A-Z][A-Za-z]*\s*\(/m;
const FIRST_ASSIGNMENT = /^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*[A-Z][A-Za-z]*\s*\(/m;

/**
 * Split a reply into markdown and OpenUI Lang segments.
 * Supports, in order of preference:
 *  1. Fenced ```openui / ```openui-lang blocks embedded in markdown.
 *  2. A whole reply (with optional short lead-in text) containing `root = Card(...)`,
 *     even if helper statements (`hdr = ...`, `kpis = ...`) appear before `root = ...`.
 */
function parseSegments(rawText?: string | null): ParsedSegment[] {
  if (!rawText) return [];
  const text = String(rawText).trim();

  const fenced = /```(?:openui-lang|openuilang|openui)\s*\n([\s\S]*?)```/gi;
  const segments: ParsedSegment[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = fenced.exec(text)) !== null) {
    const before = text.slice(last, m.index).trim();
    if (before) segments.push({ type: 'markdown', text: before });
    if (m[1].trim()) segments.push({ type: 'openui', text: m[1].trim() });
    last = fenced.lastIndex;
  }
  if (segments.length > 0) {
    const after = text.slice(last).trim();
    if (after) segments.push({ type: 'markdown', text: after });
    return segments;
  }

  // Whole-reply program: keep all preceding `id = Comp(...)` statements together with `root = ...`
  const rootMatch = ROOT_STATEMENT.exec(text);
  if (rootMatch) {
    const firstMatch = FIRST_ASSIGNMENT.exec(text);
    const startIdx = firstMatch && firstMatch.index < rootMatch.index ? firstMatch.index : rootMatch.index;
    const lead = text.slice(0, startIdx).trim();
    const program = text.slice(startIdx).trim();
    return [
      ...(lead ? [{ type: 'markdown' as const, text: lead }] : []),
      { type: 'openui' as const, text: program },
    ];
  }

  return [{ type: 'markdown', text }];
}

const OpenUIBlock: React.FC<{
  program: string;
  isStreaming: boolean;
  onSendMessage?: (message: string) => void;
}> = ({ program, isStreaming, onSendMessage }) => {
  const [error, setError] = useState<string | null>(null);

  const handleAction = useCallback(
    (event: { type: string; params: Record<string, unknown>; humanFriendlyMessage: string }) => {
      if (event.type === 'open_url') {
        const url = typeof event.params?.url === 'string' ? event.params.url : '';
        if (/^https?:\/\//i.test(url)) window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }
      if (event.type === 'continue_conversation') {
        const msg =
          (typeof event.params?.message === 'string' && event.params.message) ||
          event.humanFriendlyMessage;
        if (msg && onSendMessage) onSendMessage(msg);
      }
    },
    [onSendMessage]
  );

  if (error && !isStreaming) {
    // Never show a broken widget: fall back to the raw text so the answer is still readable.
    return <MarkdownView content={'```\n' + program + '\n```'} />;
  }

  return (
    <OpenUIThemeProvider mode="dark">
      <div className="openui-host my-1 overflow-x-auto rounded-xl text-[13px]">
        <Renderer
          response={program}
          library={openuiChatLibrary}
          isStreaming={isStreaming}
          onAction={handleAction}
          onError={(errs: Array<{ code?: string; message: string; severity?: string }>) => {
            // Ignore recoverable per-prop type-mismatch warnings so the rest of the Card/Chart/Table renders
            const fatal = errs?.find(
              (e) => e.severity !== 'warning' && e.code !== 'type-mismatch' && e.code !== 'unknown-component'
            );
            setError(fatal ? fatal.message : null);
          }}
        />
      </div>
    </OpenUIThemeProvider>
  );
};

export const OpenUIRenderer: React.FC<OpenUIRendererProps> = ({
  content,
  className,
  isStreaming = false,
  onSendMessage,
}) => {
  const segments = useMemo(() => parseSegments(content), [content]);
  if (!content) return null;

  if (!segments.some((s) => s.type === 'openui')) {
    return <MarkdownView content={content} className={className} />;
  }

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {segments.map((segment, idx) =>
        segment.type === 'markdown' ? (
          <MarkdownView key={idx} content={segment.text} />
        ) : (
          <OpenUIBlock
            key={idx}
            program={segment.text}
            isStreaming={isStreaming}
            onSendMessage={onSendMessage}
          />
        )
      )}
    </div>
  );
};
