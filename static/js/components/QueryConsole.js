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
    if (!selectedFiles || selectedFiles.length === 0) {
      if (onNotify) onNotify('Please select at least one dataset from the sidebar.', 'warning');
      return;
    }

    // Preserve task data before resetting state
    const currentPrompt = trimmedPrompt;
    const currentFiles = [...selectedFiles];

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
        placeholder="Describe the geospatial task (e.g. Compare 2016 and 2024 Sentinel-1 radar backscatter over Dubai, run Otsu thresholding, save change GeoTIFF and summary)..."
        value=${prompt}
        onInput=${(e) => setPrompt(e.target.value)}
        onKeyDown=${handleKeyDown}
        aria-label="New task prompt"
      />

      <div className="att">
        ${selectedFiles.length === 0 ? html`
          <span style=${{ fontSize: '12px', color: '#5B6B64', fontStyle: 'italic' }}>
            No datasets attached · select files in sidebar to attach
          </span>
        ` : selectedFiles.map(fn => html`
          <span key=${fn} className="at mono">
            ${fn}
            <span
              className="at-remove"
              onClick=${() => removeSelectedFile(fn)}
              title="Remove dataset"
            >
              ✕
            </span>
          </span>
        `)}
      </div>

      <div className="bar">
        <div className="sp"></div>

        <button
          className="btn p"
          onClick=${handleRun}
          disabled=${isSubmitting || !prompt.trim() || selectedFiles.length === 0}
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
