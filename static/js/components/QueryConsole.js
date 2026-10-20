// Astryx Query Console Component (Categorized Datasets, Starter Presets, Non-blocking Notifications)
import { html, React } from '/static/js/html.js';
import { IconPlay, IconSearch, IconUpload, IconX } from '/static/js/icons.js';
const { useState, useMemo } = React;

function getDatasetCategory(fileName) {
  const name = (fileName || '').toLowerCase();
  if (name.startsWith('s1_') || name.includes('_vh') || name.includes('_vv') || name.includes('sar')) {
    return 'Sentinel-1 SAR';
  }
  if (name.startsWith('s2_') || name.includes('sentinel2') || name.includes('optical')) {
    return 'Sentinel-2';
  }
  if (name.startsWith('l8_') || name.includes('landsat')) {
    return 'Landsat 8';
  }
  if (name.includes('emit') || name.includes('hyperspectral')) {
    return 'EMIT Hyperspectral';
  }
  return 'Other';
}

const STARTER_PROMPTS = [
  {
    label: 'Radar Flood / Water Detection',
    badge: 'Sentinel-1 SAR',
    prompt: 'Compare 2016 and 2024 Sentinel-1 radar backscatter (VV/VH) over Dubai, apply Otsu thresholding to segment open water, compute inundation change, and export change GeoTIFF and area metrics.',
    targetSensors: ['Sentinel-1 SAR']
  },
  {
    label: 'NDVI Vegetation Change',
    badge: 'Sentinel-2',
    prompt: 'Compute NDVI using Sentinel-2 Red (B04) and NIR (B08) bands. Segment vegetation canopy density, classify healthy versus stressed cover, and generate summary change maps.',
    targetSensors: ['Sentinel-2']
  },
  {
    label: 'Hyperspectral Mineral Mapping',
    badge: 'EMIT',
    prompt: 'Analyze EMIT hyperspectral surface reflectance across all 285 bands. Identify diagnostic mineral absorption features, extract spectral endmembers, and map dominant surface materials.',
    targetSensors: ['EMIT Hyperspectral']
  }
];

export function QueryConsole({
  files = [],
  selectedFiles = [],
  setSelectedFiles,
  onSubmitTask,
  onUploadFiles,
  isSubmitting,
  onNotify
}) {
  const [prompt, setPrompt] = useState('');
  const [fileSearch, setFileSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState('All');

  // Categorize files
  const categorizedFiles = useMemo(() => {
    return files.map(f => ({
      ...f,
      category: getDatasetCategory(f.name)
    }));
  }, [files]);

  // Categories list with count
  const categories = useMemo(() => {
    const counts = { All: files.length };
    categorizedFiles.forEach(f => {
      counts[f.category] = (counts[f.category] || 0) + 1;
    });
    return [
      { id: 'All', label: 'All', count: counts['All'] || 0 },
      { id: 'Sentinel-1 SAR', label: 'Sentinel-1 SAR', count: counts['Sentinel-1 SAR'] || 0 },
      { id: 'Sentinel-2', label: 'Sentinel-2', count: counts['Sentinel-2'] || 0 },
      { id: 'Landsat 8', label: 'Landsat 8', count: counts['Landsat 8'] || 0 },
      { id: 'EMIT Hyperspectral', label: 'EMIT', count: counts['EMIT Hyperspectral'] || 0 }
    ].filter(c => c.id === 'All' || c.count > 0);
  }, [files, categorizedFiles]);

  // Filtered files
  const filteredFiles = useMemo(() => {
    return categorizedFiles.filter(f => {
      const matchesCategory = activeCategory === 'All' || f.category === activeCategory;
      const matchesSearch = !fileSearch.trim() || f.name.toLowerCase().includes(fileSearch.toLowerCase());
      return matchesCategory && matchesSearch;
    });
  }, [categorizedFiles, activeCategory, fileSearch]);

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

  const selectAllFiltered = () => {
    const currentFilteredNames = filteredFiles.map(f => f.name);
    const combined = Array.from(new Set([...selectedFiles, ...currentFilteredNames]));
    setSelectedFiles(combined);
    if (onNotify) {
      onNotify(`Selected all ${currentFilteredNames.length} filtered datasets`, 'info');
    }
  };

  const clearAll = () => {
    setSelectedFiles([]);
  };

  const handleApplyStarter = (starter) => {
    setPrompt(starter.prompt);
    // Find files matching the starter's sensors
    const matching = categorizedFiles
      .filter(f => starter.targetSensors.includes(f.category))
      .slice(0, 4)
      .map(f => f.name);

    if (matching.length > 0) {
      setSelectedFiles(matching);
      if (onNotify) {
        onNotify(`Preset applied: attached ${matching.length} relevant datasets`, 'info');
      }
    }
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleRun();
    }
  };

  const handleRun = () => {
    if (!prompt.trim()) {
      if (onNotify) {
        onNotify('Please enter a geospatial task description.', 'warning');
      }
      return;
    }
    if (selectedFiles.length === 0) {
      if (onNotify) {
        onNotify('Please attach at least one dataset raster before running the task.', 'warning');
      }
      return;
    }
    onSubmitTask(prompt.trim(), selectedFiles);
    setPrompt('');
  };

  return html`
    <section className="command-console">
      <div className="command-layout">
        <div className="prompt-pane">
          <div className="starter-presets-bar">
            <span className="starter-heading">Task Presets:</span>
            <div className="starter-chips">
              ${STARTER_PROMPTS.map(sp => html`
                <button
                  key=${sp.label}
                  type="button"
                  className="starter-chip"
                  onClick=${() => handleApplyStarter(sp)}
                  title="Click to populate prompt and attach matching rasters"
                >
                  <span className="starter-chip-badge">${sp.badge}</span>
                  <span className="starter-chip-label">${sp.label}</span>
                </button>
              `)}
            </div>
          </div>

          <div className="textarea-container">
            <textarea
              className="console-textarea"
              placeholder="Describe the geospatial task (e.g. Compare 2016 and 2024 Sentinel-1 radar backscatter over Dubai, run Otsu thresholding, save change GeoTIFF and summary)..."
              value=${prompt}
              onInput=${(e) => setPrompt(e.target.value)}
              onKeyDown=${handleKeyDown}
              aria-label="Geospatial Task Prompt"
            />

            <div className="textarea-footer">
              <div className="active-files-summary">
                <span className="active-files-label">Attached (${selectedFiles.length}):</span>
                ${selectedFiles.length === 0 ? html`
                  <span className="no-files-hint">No datasets attached — select from panel</span>
                ` : selectedFiles.map(fn => html`
                  <span key=${fn} className="selected-chip">
                    <span className="chip-text">${fn}</span>
                    <button
                      type="button"
                      className="chip-remove"
                      onClick=${() => removeSelectedFile(fn)}
                      aria-label="Remove ${fn}"
                    >
                      <${IconX} size=${11} />
                    </button>
                  </span>
                `)}
              </div>

              <button
                type="button"
                className="btn btn-primary btn-run"
                onClick=${handleRun}
                disabled=${isSubmitting || !prompt.trim() || selectedFiles.length === 0}
                aria-label="Run Geospatial Task"
              >
                <${IconPlay} size=${12} />
                <span>Run Task</span>
                <span className="kbd-tag">Ctrl+↵</span>
              </button>
            </div>
          </div>
        </div>

        <div className="dataset-pane">
          <div className="dataset-pane-header">
            <div className="dataset-header-title">
              <span>Datasets</span>
              <span className="dataset-count-badge">${files.length}</span>
            </div>

            <div className="dataset-actions">
              <button
                className="btn btn-secondary btn-xs"
                onClick=${selectAllFiltered}
                type="button"
                title="Select all currently filtered files"
              >
                All
              </button>
              <button
                className="btn btn-secondary btn-xs"
                onClick=${clearAll}
                type="button"
                title="Clear file selection"
              >
                Clear
              </button>
              <label
                className="btn btn-secondary btn-xs btn-upload"
                title="Upload rasters into data/"
              >
                <${IconUpload} size=${11} />
                <span>Upload</span>
                <input
                  type="file"
                  multiple
                  accept=".tif,.tiff,.geojson,.csv,.json,.zip"
                  style=${{ display: 'none' }}
                  onChange=${(e) => onUploadFiles(e.target.files)}
                />
              </label>
            </div>
          </div>

          <div className="dataset-filter-tabs">
            ${categories.map(cat => html`
              <button
                key=${cat.id}
                type="button"
                className="filter-tab ${activeCategory === cat.id ? 'active' : ''}"
                onClick=${() => setActiveCategory(cat.id)}
              >
                ${cat.label}
                <span className="tab-count">${cat.count}</span>
              </button>
            `)}
          </div>

          <div className="dataset-search-wrapper">
            <${IconSearch} size=${13} className="search-icon" />
            <input
              className="dataset-search-input"
              placeholder="Filter by name (e.g. VH, B04, EMIT)..."
              value=${fileSearch}
              onInput=${(e) => setFileSearch(e.target.value)}
              aria-label="Search datasets"
            />
            ${fileSearch ? html`
              <button
                className="search-clear-btn"
                type="button"
                onClick=${() => setFileSearch('')}
                aria-label="Clear search"
              >
                <${IconX} size=${11} />
              </button>
            ` : null}
          </div>

          <div className="dataset-list" role="list">
            ${filteredFiles.length === 0 ? html`
              <div className="dataset-empty-state">
                No datasets match the current filter
              </div>
            ` : filteredFiles.map(file => {
              const isChecked = selectedFiles.includes(file.name);
              const inputId = `dataset-check-${file.name.replace(/[^a-zA-Z0-9_-]/g, '_')}`;

              return html`
                <label
                  key=${file.name}
                  htmlFor=${inputId}
                  className="dataset-item ${isChecked ? 'checked' : ''}"
                >
                  <div className="dataset-item-left">
                    <input
                      type="checkbox"
                      id=${inputId}
                      checked=${isChecked}
                      onChange=${() => toggleFile(file.name)}
                      className="dataset-checkbox"
                    />
                    <span className="dataset-filename">${file.name}</span>
                  </div>

                  <div className="dataset-item-right">
                    <span className="sensor-tag">${file.category.split(' ')[0]}</span>
                    <span className="dataset-filesize">${file.size_mb} MB</span>
                  </div>
                </label>
              `;
            })}
          </div>
        </div>
      </div>
    </section>
  `;
}
