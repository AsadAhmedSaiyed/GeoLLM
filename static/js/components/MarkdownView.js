// Markdown View Component using vendor marked parser
import { html, React } from '/static/js/html.js';

export function renderMarkdownToHtml(markdownText) {
  if (!markdownText) return '';
  const textStr = String(markdownText);

  if (typeof window !== 'undefined' && window.marked) {
    try {
      if (typeof window.marked.parse === 'function') {
        return window.marked.parse(textStr, { gfm: true, breaks: true });
      }
      return window.marked(textStr);
    } catch (e) {
      console.warn('Markdown parsing error:', e);
    }
  }

  // Safe fallback if marked is not yet loaded
  return textStr
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br />');
}

export function MarkdownView({ content, className = 'markdown-body' }) {
  if (!content) return null;
  const htmlMarkup = renderMarkdownToHtml(content);

  return html`
    <div
      className=${className}
      dangerouslySetInnerHTML=${{ __html: htmlMarkup }}
    />
  `;
}
