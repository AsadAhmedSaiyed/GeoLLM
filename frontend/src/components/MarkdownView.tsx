import React, { useMemo } from 'react';
import { marked } from 'marked';
import { cn } from '@/lib/utils';

interface MarkdownViewProps {
  content?: string | null;
  className?: string;
}

export function renderMarkdownToHtml(markdownText?: string | null): string {
  if (!markdownText) return '';
  const textStr = String(markdownText);

  try {
    const parsed = marked.parse(textStr, { gfm: true, breaks: true, async: false });
    if (typeof parsed === 'string') {
      return parsed;
    }
  } catch (e) {
    console.warn('Markdown parsing error:', e);
  }

  return textStr
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br />');
}

export const MarkdownView: React.FC<MarkdownViewProps> = ({
  content,
  className = 'markdown-body',
}) => {
  const htmlMarkup = useMemo(() => renderMarkdownToHtml(content), [content]);

  if (!content) return null;

  return (
    <div
      className={cn(
        'max-w-none text-[13px] leading-relaxed text-foreground',
        className
      )}
      dangerouslySetInnerHTML={{ __html: htmlMarkup }}
    />
  );
};

