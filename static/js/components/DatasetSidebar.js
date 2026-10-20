// GeoLLM Dataset Sidebar Component (Styled from design/reference.html)
import { html, React } from '/static/js/html.js';
const { useState, useMemo } = React;

function getFileInfo(fileName) {
  const name = (fileName || '').toLowerCase();
  if (name.includes('s1_2016')) return { group: 'Sentinel-1 radar', meta: '18 Apr 2016 · 20 m · UTM 40N', sensor: 'Radar' };
  if (name.includes('s1_2024pre')) return { group: 'Sentinel-1 radar', meta: '12 Apr 2024 · 20 m · UTM 40N', sensor: 'Radar' };
  if (name.includes('s1_2024post')) return { group: 'Sentinel-1 radar', meta: '18 May 2024 · 20 m · UTM 40N', sensor: 'Radar' };
  if (name.includes('after_v') || name.includes('before_v') || name.includes('sar')) {
    return { group: 'Sentinel-1 radar', meta: 'Apr/May 2024 · 20 m · UTM 40N', sensor: 'Radar' };
  }
  if (name.includes('l8_2016')) return { group: 'Landsat 8 optical', meta: '20 Mar 2016 · 30 m · 6 bands', sensor: 'Optical' };
  if (name.includes('l8_2024')) return { group: 'Landsat 8 optical', meta: '13 May 2024 · 30 m · 6 bands', sensor: 'Optical' };
  if (name.includes('s2_2024pre')) return { group: 'Sentinel-2 optical', meta: 'Early Apr 2024 · 10 m · partial', sensor: 'Optical' };
  if (name.includes('s2_2024') || name.includes('sentinel2')) {
    return { group: 'Sentinel-2 optical', meta: '17 May 2024 · 10 m · 6 bands', sensor: 'Optical' };
  }
  if (name.includes('emit') || name.includes('hyperspectral')) {
    return { group: 'Hyperspectral', meta: '20 Aug 2022 · 285 bands · EPSG:4326', sensor: 'Hyperspectral' };
  }
  return { group: 'Other datasets', meta: 'Local raster deliverable', sensor: 'Other' };
}

export function DatasetSidebar({
  files = [],
  selectedFiles = [],
  setSelectedFiles,
  onUploadFiles,
  onNotify
}) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('All');

  const fileItems = useMemo(() => {
    return files.map(f => {
      const info = getFileInfo(f.name);
      return {
        ...f,
        group: info.group,
        meta: info.meta,
        sensor: info.sensor
      };
    });
  }, [files]);

  const filteredItems = useMemo(() => {
    return fileItems.filter(item => {
      const matchesFilter =
        filter === 'All' ||
        (filter === 'Radar' && item.sensor === 'Radar') ||
        (filter === 'Optical' && item.sensor === 'Optical') ||
        (filter === 'Hyperspectral' && item.sensor === 'Hyperspectral');

      const matchesSearch =
        !search.trim() ||
        item.name.toLowerCase().includes(search.toLowerCase()) ||
        item.group.toLowerCase().includes(search.toLowerCase());

      return matchesFilter && matchesSearch;
    });
  }, [fileItems, filter, search]);

  const groups = useMemo(() => {
    const map = new Map();
    filteredItems.forEach(item => {
      if (!map.has(item.group)) {
        map.set(item.group, []);
      }
      map.get(item.group).push(item);
    });
    return Array.from(map.entries());
  }, [filteredItems]);

  const toggleFile = (fileName) => {
    if (selectedFiles.includes(fileName)) {
      setSelectedFiles(selectedFiles.filter(f => f !== fileName));
    } else {
      setSelectedFiles([...selectedFiles, fileName]);
    }
  };

  const handleSelectAllFiltered = () => {
    const names = filteredItems.map(f => f.name);
    const combined = Array.from(new Set([...selectedFiles, ...names]));
    setSelectedFiles(combined);
    if (onNotify) onNotify(`Selected ${names.length} files`, 'info');
  };

  const handleClear = () => {
    setSelectedFiles([]);
  };

  return html`
    <aside className="side">
      <div className="sh">Datasets · data/ (${files.length})</div>

      <input
        className="in"
        type="search"
        aria-label="Search datasets"
        placeholder="Search datasets"
        value=${search}
        onInput=${(e) => setSearch(e.target.value)}
      />

      <div className="chips">
        <button
          className="fc ${filter === 'All' ? 'on' : ''}"
          onClick=${() => setFilter('All')}
          type="button"
        >
          All
        </button>
        <button
          className="fc ${filter === 'Radar' ? 'on' : ''}"
          onClick=${() => setFilter('Radar')}
          type="button"
        >
          Radar
        </button>
        <button
          className="fc ${filter === 'Optical' ? 'on' : ''}"
          onClick=${() => setFilter('Optical')}
          type="button"
        >
          Optical
        </button>
        <button
          className="fc ${filter === 'Hyperspectral' ? 'on' : ''}"
          onClick=${() => setFilter('Hyperspectral')}
          type="button"
        >
          Hyperspectral
        </button>
      </div>

      <div className="list">
        ${groups.length === 0 ? html`
          <div style=${{ padding: '20px 16px', fontSize: '12px', color: '#5B6B64', textAlign: 'center' }}>
            No matching datasets found
          </div>
        ` : groups.map(([groupName, items]) => html`
          <div key=${groupName}>
            <div className="gh">
              ${groupName} <span>${items.length} ${items.length === 1 ? 'file' : 'files'}</span>
            </div>

            ${items.map(item => {
              const isChecked = selectedFiles.includes(item.name);
              return html`
                <div
                  key=${item.name}
                  className="ds ${isChecked ? 'sel' : ''}"
                  onClick=${() => toggleFile(item.name)}
                  role="checkbox"
                  aria-checked=${isChecked}
                  tabIndex="0"
                  onKeyDown=${(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault();
                      toggleFile(item.name);
                    }
                  }}
                  style=${{ cursor: 'pointer', userSelect: 'none' }}
                >
                  <input
                    type="checkbox"
                    checked=${isChecked}
                    onClick=${(e) => e.stopPropagation()}
                    onChange=${(e) => {
                      e.stopPropagation();
                      toggleFile(item.name);
                    }}
                    tabIndex="-1"
                  />
                  <span className="mono">${item.name}</span>
                  <small>${item.meta} · ${item.size_mb} MB</small>
                </div>
              `;
            })}
          </div>
        `)}
      </div>

      <div className="sf">
        <span><b>${selectedFiles.length}</b> selected</span>
        <div style=${{ display: 'flex', gap: '6px' }}>
          ${selectedFiles.length > 0 ? html`
            <button
              className="btn s"
              onClick=${handleClear}
              type="button"
              style=${{ color: '#5B6B64' }}
            >
              Clear
            </button>
          ` : null}
          <label className="btn s" style=${{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center' }}>
            Upload
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
    </aside>
  `;
}
