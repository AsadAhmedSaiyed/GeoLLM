// GeoLLM Query Console Component (Styled from design/reference.html)
import { html, React } from '/static/js/html.js';
const { useState } = React;

const TEMPLATES = [
  {
    id: 'none',
    label: 'Choose template (optional)...',
    prompt: '',
    files: []
  },
  {
    id: 'radar_change',
    label: 'Template: radar change detection',
    prompt: 'These radar images cover the same area on 12 April 2024 and 18 May 2024, each in two channels. Run Otsu thresholding on VV and VH backscatter difference to outline flood changes, export change GeoTIFF and area metrics.',
    files: ['after_VH.tif', 'after_VV.tif', 'before_VH.tif', 'before_VV.tif']
  },
  {
    id: 'land_cover',
    label: 'Template: optical land-cover change',
    prompt: 'These are natural-colour and infrared satellite images from 2016 and 2024. Compute NDVI and NDWI, classify water, vegetation, bare sand and built-up surfaces, and generate change maps.',
    files: ['S2_2024_B04.tif', 'S2_2024_B08.tif', 'L8_2016_nir08.tif', 'L8_2016_red.tif']
  },
  {
    id: 'hyperspectral',
    label: 'Template: hyperspectral material mapping',
    prompt: 'Analyze EMIT hyperspectral surface reflectance across all 285 bands. Identify diagnostic mineral absorption features, extract spectral endmembers, and map ground materials.',
    files: ['EMIT_reflectance.tif']
  }
];

export function QueryConsole({
  files = [],
  selectedFiles = [],
  setSelectedFiles,
  onSubmitTask,
  isSubmitting = false,
  onNotify
}) {
  const [prompt, setPrompt] = useState('');
  const [maxTurns, setMaxTurns] = useState(25);
  const [explainResults, setExplainResults] = useState(true);

  const handleTemplateChange = (e) => {
    const tId = e.target.value;
    const tpl = TEMPLATES.find(t => t.id === tId);
    if (!tpl || tId === 'none') return;

    setPrompt(tpl.prompt);

    // Filter available files matching template recommendations
    if (tpl.files && tpl.files.length > 0 && files.length > 0) {
      const availableNames = files.map(f => f.name);
      const matched = tpl.files.filter(fn => availableNames.includes(fn));
      if (matched.length > 0) {
        setSelectedFiles(matched);
      }
    }

    if (onNotify) {
      onNotify(`Applied ${tpl.label}`, 'info');
    }
  };

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
    if (!prompt.trim()) {
      if (onNotify) onNotify('Please enter a task description before running.', 'warning');
      return;
    }
    if (selectedFiles.length === 0) {
      if (onNotify) onNotify('Please select at least one dataset from the sidebar.', 'warning');
      return;
    }

    onSubmitTask(prompt.trim(), selectedFiles);
    setPrompt('');
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
            No datasets attached · check files in sidebar
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
        <select
          aria-label="Template"
          onChange=${handleTemplateChange}
          defaultValue="none"
        >
          ${TEMPLATES.map(t => html`
            <option key=${t.id} value=${t.id}>${t.label}</option>
          `)}
        </select>

        <label>
          Max turns
          <input
            type="number"
            min="5"
            max="100"
            value=${maxTurns}
            onInput=${(e) => setMaxTurns(e.target.value)}
            style=${{ width: '64px' }}
          />
        </label>

        <label>
          <input
            type="checkbox"
            checked=${explainResults}
            onChange=${(e) => setExplainResults(e.target.checked)}
          />
          Explain results
        </label>

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
