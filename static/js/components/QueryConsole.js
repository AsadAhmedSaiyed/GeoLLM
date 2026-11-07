// GeoLLM Query Console Component (Refined layout and reset behavior)
import { html, React } from '/static/js/html.js';
const { useState } = React;

export function QueryConsole({
  files = [],
  selectedFiles = [],
  setSelectedFiles,
  onSubmitTask,
  isSubmitting = false,
  onNotify
}) {
  const [prompt, setPrompt] = useState('');

  const removeSelectedFile = (fileName) => {
    setSelectedFiles(selectedFiles.filter(f => f !== fileName));
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleRun();
    }
  };

  const handleRun = () => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      if (onNotify) onNotify('Please enter a task description before running.', 'warning');
      return;
    }

    // Preserve task data before resetting state (empty array triggers Autonomous STAC Discovery)
    const currentPrompt = trimmedPrompt;
    const currentFiles = [...(selectedFiles || [])];

    // Submit task
    onSubmitTask(currentPrompt, currentFiles);

    // Reset prompt and clear selected dataset files
    setPrompt('');
    setSelectedFiles([]);
  };

  return html`
    <section className="card comp">
      <label className="h" htmlFor="q">New task</label>

      <textarea
        id="q"
        placeholder="Describe your task or location & dates in plain English (e.g. 'Show how green farming area changed near Basra, Iraq between May 2020 and May 2025')..."
        value=${prompt}
        onInput=${(e) => setPrompt(e.target.value)}
        onKeyDown=${handleKeyDown}
        aria-label="New task prompt"
      />

      <div className="att">
        ${selectedFiles.length === 0 ? html`
          <span style=${{ fontSize: '12px', color: '#0F766E', fontWeight: 500 }}>
            \ud83d\udef0\ufe0f Autonomous STAC Mode \u2014 Agent will search & preview satellite imagery for your query (or select local files in sidebar)
          </span>
        ` : selectedFiles.map(fn => html`
          <span key=${fn} className="at mono">
            ${fn}
            <span
              className="at-remove"
              onClick=${() => removeSelectedFile(fn)}
              title="Remove dataset"
            >
              \u2715
            </span>
          </span>
        `)}
      </div>

      <div className="bar">
        <div className="sp"></div>

        <button
          className="btn p"
          onClick=${handleRun}
          disabled=${isSubmitting || !prompt.trim()}
          type="button"
          style=${{ height: '40px', padding: '0 20px', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
        >
          <span>Run task</span>
          <span className="mono" style=${{ fontSize: '11px', opacity: 0.85 }}>Ctrl+Enter</span>
        </button>
      </div>
    </section>
  `;
}
