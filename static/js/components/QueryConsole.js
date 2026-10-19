// Astryx Query Console Component (High UX Prompt & Dataset Selector)
import { html, React } from '/static/js/html.js';
const { useState } = React;

export function QueryConsole({
  files,
  selectedFiles,
  setSelectedFiles,
  onSubmitTask,
  onUploadFiles,
  isSubmitting
}) {
  const [prompt, setPrompt] = useState('');
  const [fileSearch, setFileSearch] = useState('');

  const filteredFiles = files.filter(f =>
    f.name.toLowerCase().includes(fileSearch.toLowerCase())
  );

  const toggleFile = (fileName) => {
    if (selectedFiles.includes(fileName)) {
      setSelectedFiles(selectedFiles.filter(f => f !== fileName));
    } else {
      setSelectedFiles([...selectedFiles, fileName]);
    }
  };

  const removeSelectedFile = (fileName) => {
    setSelectedFiles(selectedFiles.filter(f => f !== fileName));
  };

  const selectAll = () => {
    setSelectedFiles(files.map(f => f.name));
  };

  const clearAll = () => {
    setSelectedFiles([]);
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleRun();
    }
  };

  const handleRun = () => {
    if (!prompt.trim()) return;
    onSubmitTask(prompt.trim(), selectedFiles);
    setPrompt('');
  };

  return html`
    <section className="command-console">
      <div className="command-layout">
        <div className="prompt-pane">
          <div className="textarea-container">
            <textarea
              className="console-textarea"
              placeholder="Describe the geospatial task (e.g. Compare 2016 and 2024 Sentinel-1 radar backscatter over Dubai, run Otsu thresholding, save change GeoTIFF and summary)..."
              value=${prompt}
              onInput=${(e) => setPrompt(e.target.value)}
              onKeyDown=${handleKeyDown}
            />

            <div className="textarea-footer">
              <div className="active-files-summary">
                <span style=${{ fontSize: '11px', color: '#94a3b8' }}>Selected (${selectedFiles.length}):</span>
                ${selectedFiles.length === 0 ? html`
                  <span style=${{ fontSize: '11px', color: '#64748b' }}>No datasets attached</span>
                ` : selectedFiles.map(fn => html`
                  <span key=${fn} className="selected-chip">
                    ${fn}
                    <span className="chip-remove" onClick=${() => removeSelectedFile(fn)}>✕</span>
                  </span>
                `)}
              </div>

              <button
                className="btn btn-primary"
                onClick=${handleRun}
                disabled=${isSubmitting || !prompt.trim() || selectedFiles.length === 0}
              >
                ▶ Run Task
                <span className="kbd-tag">Ctrl+↵</span>
              </button>
            </div>
          </div>
        </div>

        <div className="dataset-pane">
          <div className="dataset-pane-header">
            <span>Datasets in data/ (${files.length})</span>
            <div style=${{ display: 'flex', gap: '6px' }}>
              <button
                className="btn btn-secondary btn-sm"
                style=${{ padding: '2px 6px', fontSize: '10px' }}
                onClick=${selectAll}
                type="button"
              >
                All
              </button>
              <button
                className="btn btn-secondary btn-sm"
                style=${{ padding: '2px 6px', fontSize: '10px' }}
                onClick=${clearAll}
                type="button"
              >
                Clear
              </button>
              <label
                className="btn btn-secondary btn-sm"
                style=${{ padding: '2px 6px', fontSize: '10px', cursor: 'pointer' }}
              >
                Upload
                <input
                  type="file"
                  multiple
                  style=${{ display: 'none' }}
                  onChange=${(e) => onUploadFiles(e.target.files)}
                />
              </label>
            </div>
          </div>

          <input
            className="dataset-search-input"
            placeholder="Search datasets..."
            value=${fileSearch}
            onInput=${(e) => setFileSearch(e.target.value)}
          />

          <div className="dataset-list">
            ${filteredFiles.length === 0 ? html`
              <div style=${{ padding: '10px', fontSize: '11px', color: '#64748b', textAlign: 'center' }}>
                No matching files
              </div>
            ` : filteredFiles.map(file => {
              const isChecked = selectedFiles.includes(file.name);
              return html`
                <div
                  key=${file.name}
                  className="dataset-item ${isChecked ? 'checked' : ''}"
                  onClick=${() => toggleFile(file.name)}
                >
                  <div className="dataset-item-left">
                    <input
                      type="checkbox"
                      checked=${isChecked}
                      onChange=${() => {}}
                      style=${{ cursor: 'pointer' }}
                    />
                    <span>${file.name}</span>
                  </div>
                  <span style=${{ color: '#94a3b8', fontSize: '10px' }}>${file.size_mb} MB</span>
                </div>
              `;
            })}
          </div>
        </div>
      </div>
    </section>
  `;
}
