import { html, React } from '../html.js';

const { useState, useEffect, useRef } = React;

export function StacModal({
  isOpen,
  onClose,
  initialBbox,
  onAssetStaged,
}) {
  // ALL hooks must be called unconditionally before any early return (Rules of Hooks)
  const [collections, setCollections] = useState([]);
  const [selectedCollections, setSelectedCollections] = useState(['sentinel-2-l2a', 'sentinel-1-rtc']);
  const [selectedModality, setSelectedModality] = useState('all');

  // Dates default: recent or historical event
  const [startDate, setStartDate] = useState('2024-04-10');
  const [endDate, setEndDate] = useState('2024-05-20');
  const [maxCloud, setMaxCloud] = useState(25);
  const [bboxInput, setBboxInput] = useState(
    initialBbox ? initialBbox.join(', ') : '55.15, 25.05, 55.45, 25.35' // Dubai default
  );

  const [loading, setLoading] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [errorMsg, setErrorMsg] = useState(null);
  const [stagingKeys, setStagingKeys] = useState({});
  // useRef so mutations don't trigger re-renders — prevents infinite toast loop
  const stagedKeysRef = useRef({});
  const searchAbortRef = useRef(null);
  const [activeDownloads, setActiveDownloads] = useState({});

  // Poll real-time download progress from backend every 500ms (only while modal is open)
  useEffect(() => {
    if (!isOpen) return; // don't poll when modal is closed — avoids disrupting globe AOI drawing
    let timer = null;
    const fetchProgress = async () => {
      try {
        const resp = await fetch('/api/stac/downloads');
        if (resp.ok) {
          const data = await resp.json();
          if (data.downloads) {
            setActiveDownloads(data.downloads);
            // Check completed downloads and trigger onAssetStaged
            Object.values(data.downloads).forEach((dl) => {
              if (dl.status === 'completed' && !stagedKeysRef.current[dl.stage_id]) {
                stagedKeysRef.current[dl.stage_id] = true;
                if (onAssetStaged) {
                  onAssetStaged({
                    ok: true,
                    filename: dl.filename,
                    path: dl.path,
                    size_mb: dl.downloaded_mb,
                    collection: dl.collection,
                    item_id: dl.item_id,
                    asset_key: dl.asset_key,
                  });
                }
              }
            });
          }
        }
      } catch (e) {
        // silent
      }
    };

    fetchProgress();
    timer = setInterval(fetchProgress, 500);
    return () => clearInterval(timer);
  }, [isOpen]);

  // Load collections dynamically from backend
  useEffect(() => {
    fetch('/api/stac/collections')
      .then((r) => r.json())
      .then((data) => {
        if (data.collections) {
          setCollections(data.collections);
        }
      })
      .catch((e) => console.warn('Could not load STAC collections:', e));
  }, []);

  // Update BBOX if initialBbox changes from globe
  useEffect(() => {
    if (initialBbox) {
      setBboxInput(initialBbox.map((n) => parseFloat(n).toFixed(4)).join(', '));
    }
  }, [initialBbox]);

  // Guard AFTER all hooks — ref survives close/reopen cycles (Rules of Hooks compliance)
  if (!isOpen) return null;

  const handleSearch = async () => {
    setErrorMsg(null);
    setLoading(true);
    setSearchResults([]);

    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
    }
    const controller = new AbortController();
    searchAbortRef.current = controller;

    try {
      const raw = bboxInput.split(',').map((s) => parseFloat(s.trim()));
      if (raw.length !== 4 || raw.some(isNaN)) {
        throw new Error('Bounding box must contain 4 numbers: min_lon, min_lat, max_lon, max_lat');
      }
      const minX = Math.min(raw[0], raw[2]);
      const maxX = Math.max(raw[0], raw[2]);
      const minY = Math.min(raw[1], raw[3]);
      const maxY = Math.max(raw[1], raw[3]);
      const parsedBbox = [minX, minY, maxX, maxY];

      const toIsoDate = (val, fallback) => {
        if (!val) return fallback;
        const s = String(val).trim();
        const isoMatch = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
        if (isoMatch) {
          const y = isoMatch[1];
          const m = isoMatch[2].padStart(2, '0');
          const d = isoMatch[3].padStart(2, '0');
          return `${y}-${m}-${d}`;
        }
        const dmyMatch = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})/);
        if (dmyMatch) {
          const p1 = parseInt(dmyMatch[1], 10);
          const p2 = parseInt(dmyMatch[2], 10);
          const y = dmyMatch[3];
          let d = p1;
          let m = p2;
          if (p1 > 12 && p2 <= 12) {
            d = p1; m = p2;
          } else if (p2 > 12 && p1 <= 12) {
            d = p2; m = p1;
          }
          return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        }
        return s.slice(0, 10);
      };

      let sDate = toIsoDate(startDate, '2024-04-10');
      let eDate = toIsoDate(endDate, '2024-05-20');
      if (sDate && eDate && sDate > eDate) {
        const tmp = sDate;
        sDate = eDate;
        eDate = tmp;
      }
      setStartDate(sDate);
      setEndDate(eDate);

      const resp = await fetch('/api/stac/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          bbox: parsedBbox,
          start_date: sDate,
          end_date: eDate,
          collections: selectedCollections,
          max_cloud_cover: maxCloud,
          limit: 12,
        }),
      });

      const data = await resp.json();
      if (!data.ok) {
        throw new Error(data.error || 'STAC search failed');
      }

      setSearchResults(data.items || []);
      if ((data.items || []).length === 0) {
        setErrorMsg('No satellite scenes found matching this AOI, date range, and cloud threshold.');
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setErrorMsg('Search request cancelled.');
      } else {
        setErrorMsg(err.message);
      }
    } finally {
      setLoading(false);
      searchAbortRef.current = null;
    }
  };

  const handleCancelSearch = () => {
    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
      searchAbortRef.current = null;
    }
    setLoading(false);
  };

  const handleStageAsset = async (item, assetKey) => {
    const stageId = `${item.id}_${assetKey}`;
    setStagingKeys((prev) => ({ ...prev, [stageId]: true }));
    try {
      const resp = await fetch('/api/stac/stage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          collection: item.collection,
          item_id: item.id,
          asset_key: assetKey,
        }),
      });

      const data = await resp.json();
      if (!data.ok) {
        throw new Error(data.error || 'Failed to start download');
      }
    } catch (err) {
      alert(`Asset ${assetKey} download start failed: ${err.message}`);
      setStagingKeys((prev) => {
        const next = { ...prev };
        delete next[stageId];
        return next;
      });
    }
  };

  const handleCancelDownload = async (stageId) => {
    try {
      await fetch('/api/stac/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage_id: stageId }),
      });
      setStagingKeys((prev) => {
        const next = { ...prev };
        delete next[stageId];
        return next;
      });
    } catch (err) {
      console.error('Failed to cancel download:', err);
    }
  };

  const handleCancelAllDownloads = async () => {
    const active = Object.values(activeDownloads).filter(
      (d) => d.status === 'downloading' || d.status === 'starting' || d.status === 'fetching_metadata'
    );
    await Promise.all(active.map((d) => handleCancelDownload(d.stage_id)));
  };

  const handleCancelItemDownloads = async (item) => {
    const activeItemDls = Object.values(activeDownloads).filter(
      (d) => d.item_id === item.id && (d.status === 'downloading' || d.status === 'starting' || d.status === 'fetching_metadata')
    );
    await Promise.all(activeItemDls.map((d) => handleCancelDownload(d.stage_id)));
  };

  const handleDownloadAllCore = async (item) => {
    let coreBands = [];
    if (item.collection.includes('sentinel-2') || item.collection.includes('landsat')) {
      coreBands = ['B02', 'B03', 'B04', 'B08', 'blue', 'green', 'red', 'nir08'];
    } else if (item.collection.includes('sentinel-1')) {
      coreBands = ['vv', 'vh'];
    } else if (item.collection.includes('emit')) {
      coreBands = ['reflectance'];
    } else if (item.collection.includes('dem') || item.collection.includes('worldcover')) {
      coreBands = ['data', 'map'];
    }

    const targets = (item.assets || []).filter((a) => coreBands.includes(a.key));
    if (targets.length === 0) {
      alert('No matching core assets found to batch download.');
      return;
    }

    // Launch all concurrently
    await Promise.all(targets.map((a) => handleStageAsset(item, a.key)));
  };

  const filteredCollections = selectedModality === 'all'
    ? collections
    : collections.filter((c) => c.modality === selectedModality);

  return html`
    <div className="stac-modal-backdrop" onClick=${onClose}>
      <div className="stac-modal-container" onClick=${(e) => e.stopPropagation()}>
        <!-- Header -->
        <div className="stac-modal-header">
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style=${{ fontSize: '18px' }}>🛰️</span>
            <div>
              <div style=${{ fontWeight: 600, fontSize: '15px', color: '#14201C' }}>
                Microsoft Planetary Computer Satellite Data
              </div>
              <div style=${{ fontSize: '11px', color: '#5B6B64' }}>
                Search & retrieve Optical, SAR, Hyperspectral, and DEM assets for your Area of Interest
              </div>
            </div>
          </div>
          <button type="button" className="close-btn" onClick=${onClose}>×</button>
        </div>

        <!-- Filter Controls -->
        <div className="stac-modal-body">
          <div className="stac-controls-grid">
            <!-- Modality Category Pills -->
            <div className="control-field" style=${{ gridColumn: 'span 2' }}>
              <label className="field-label">Sensor Modality</label>
              <div className="pills-row">
                ${['all', 'optical', 'sar', 'hyperspectral', 'dem', 'landcover'].map((mod) => html`
                  <button
                    key=${mod}
                    type="button"
                    className="modality-pill ${selectedModality === mod ? 'active' : ''}"
                    onClick=${() => {
                      setSelectedModality(mod);
                      const matching = collections.filter((c) => mod === 'all' || c.modality === mod).map((c) => c.id);
                      setSelectedCollections(matching.slice(0, 2));
                    }}
                  >
                    ${mod === 'all' ? '🌐 All Sensors' :
                      mod === 'optical' ? '🛰️ Optical' :
                      mod === 'sar' ? '📡 Radar (SAR)' :
                      mod === 'hyperspectral' ? '🌈 Hyperspectral (EMIT)' :
                      mod === 'dem' ? '🏔️ Elevation (DEM)' : '🌲 Land Cover'}
                  </button>
                `)}
              </div>
            </div>

            <!-- Target Collection Checkboxes -->
            <div className="control-field" style=${{ gridColumn: 'span 2' }}>
              <label className="field-label">Target Collections</label>
              <div className="collection-checkboxes">
                ${filteredCollections.map((c) => {
                  const isChecked = selectedCollections.includes(c.id);
                  return html`
                    <label key=${c.id} className="collection-chip ${isChecked ? 'checked' : ''}">
                      <input
                        type="checkbox"
                        checked=${isChecked}
                        onChange=${() => {
                          if (isChecked) {
                            setSelectedCollections(selectedCollections.filter((id) => id !== c.id));
                          } else {
                            setSelectedCollections([...selectedCollections, c.id]);
                          }
                        }}
                      />
                      <span>${c.title}</span>
                    </label>
                  `;
                })}
              </div>
            </div>

            <!-- AOI BBOX -->
            <div className="control-field" style=${{ gridColumn: 'span 2' }}>
              <label className="field-label">Area of Interest (BBOX: West, South, East, North)</label>
              <input
                type="text"
                className="stac-input mono"
                value=${bboxInput}
                onChange=${(e) => setBboxInput(e.target.value)}
                placeholder="min_lon, min_lat, max_lon, max_lat"
              />
            </div>

            <!-- Date Range -->
            <div className="control-field">
              <label className="field-label">Start Date</label>
              <input
                type="date"
                className="stac-input"
                value=${startDate}
                onChange=${(e) => setStartDate(e.target.value)}
              />
            </div>

            <div className="control-field">
              <label className="field-label">End Date</label>
              <input
                type="date"
                className="stac-input"
                value=${endDate}
                onChange=${(e) => setEndDate(e.target.value)}
              />
            </div>

            <!-- Cloud Cover Threshold -->
            <div className="control-field" style=${{ gridColumn: 'span 2' }}>
              <div style=${{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <label className="field-label" style=${{ margin: 0 }}>Max Cloud Cover</label>
                <span className="mono" style=${{ fontSize: '11px', color: '#5B6B64' }}>${maxCloud}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value=${maxCloud}
                onChange=${(e) => setMaxCloud(e.target.value)}
                style=${{ width: '100%', accentColor: '#0F766E' }}
              />
            </div>
          </div>

          <!-- Search Action -->
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
            ${loading ? html`
              <button
                type="button"
                className="stac-download-cancel-btn"
                onClick=${handleCancelSearch}
                style=${{ padding: '6px 12px', fontSize: '12px' }}
                title="Abort in-flight search"
              >
                ✕ Cancel Search
              </button>
            ` : null}
            <button
              type="button"
              className="stac-search-btn"
              onClick=${handleSearch}
              disabled=${loading || selectedCollections.length === 0}
            >
              ${loading ? 'Searching STAC Catalog…' : '🔍 Search Matching Satellite Scenes'}
            </button>
          </div>

          <!-- Error Alert -->
          ${errorMsg ? html`
            <div className="stac-alert error">${errorMsg}</div>
          ` : null}

          <!-- Active Downloads Real-time Progress Bar Panel -->
          ${Object.keys(activeDownloads).length > 0 ? html`
            <div className="stac-downloads-panel">
              <div className="stac-downloads-header" style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>📥 Satellite Downloads</span>
                  <span style=${{ fontSize: '11px', color: '#5B6B64', fontWeight: 'normal' }}>
                    (${Object.values(activeDownloads).filter((d) => d.status === 'downloading' || d.status === 'starting' || d.status === 'fetching_metadata').length} in progress)
                  </span>
                </div>
                ${Object.values(activeDownloads).some((d) => d.status === 'downloading' || d.status === 'starting' || d.status === 'fetching_metadata') ? html`
                  <button
                    type="button"
                    className="stac-download-cancel-btn"
                    onClick=${handleCancelAllDownloads}
                    title="Cancel all active downloads"
                    style=${{ padding: '2px 8px', fontSize: '10.5px' }}
                  >
                    ✕ Cancel All
                  </button>
                ` : null}
              </div>
              <div className="stac-downloads-list">
                ${Object.values(activeDownloads).map((dl) => {
                  const isDone = dl.status === 'completed';
                  const isFail = dl.status === 'failed';
                  const isCancelled = dl.status === 'cancelled';
                  const isInProgress = dl.status === 'downloading' || dl.status === 'starting' || dl.status === 'fetching_metadata';
                  const pct = isDone ? 100 : (dl.percent || 0);

                  return html`
                    <div key=${dl.stage_id} className="stac-download-item">
                      <div className="stac-download-meta">
                        <span className="stac-download-filename" title=${dl.filename}>
                          ${isDone ? '✓ ' : (isFail ? '✗ ' : (isCancelled ? '⊘ ' : '⏳ '))}${dl.filename}
                        </span>
                        <div className="stac-download-stats">
                          ${isDone ? html`
                            <span style=${{ color: '#16A34A', fontWeight: 600 }}>Staged (${dl.total_mb || dl.downloaded_mb} MB)</span>
                          ` : isCancelled ? html`
                            <span style=${{ color: '#D97706', fontWeight: 600 }}>Cancelled</span>
                          ` : isFail ? html`
                            <span style=${{ color: '#DC2626' }}>Failed: ${dl.error || 'Network error'}</span>
                          ` : html`
                            <span>${dl.downloaded_mb || 0} / ${dl.total_mb ? `${dl.total_mb} MB` : 'calc…'} (${Math.round(pct)}%)</span>
                            ${dl.speed_mbps ? html`<span style=${{ opacity: 0.7 }}>• ${dl.speed_mbps} MB/s</span>` : null}
                            <button
                              type="button"
                              className="stac-download-cancel-btn"
                              onClick=${() => handleCancelDownload(dl.stage_id)}
                              title="Cancel this download"
                            >
                              ✕ Cancel
                            </button>
                          `}
                        </div>
                      </div>
                      <div className="stac-progress-track">
                        <div
                          className="stac-progress-fill ${isDone ? 'completed' : ''} ${isFail ? 'failed' : ''} ${isCancelled ? 'cancelled' : ''}"
                          style=${{ width: `${Math.max(pct, isDone ? 100 : 4)}%` }}
                        ></div>
                      </div>
                    </div>
                  `;
                })}
              </div>
            </div>
          ` : null}

          <!-- Search Results Gallery -->
          ${searchResults.length > 0 ? html`
            <div className="stac-results-section">
              <div className="results-count-bar">
                <span>Found <strong>${searchResults.length}</strong> matching satellite scene(s)</span>
              </div>

              <div className="results-grid">
                ${searchResults.map((item) => {
                  const dt = (item.datetime || '').slice(0, 10);
                  const cloud = item.cloud_cover != null ? `${Math.round(item.cloud_cover)}% clouds` : null;

                  return html`
                    <div key=${item.id} className="stac-item-card">
                      <div className="card-thumb">
                        ${item.thumbnail ? html`
                          <img src=${item.thumbnail} alt="Thumbnail" loading="lazy" />
                        ` : html`
                          <div className="no-thumb-placeholder">📡 Scene</div>
                        `}
                      </div>

                      <div className="card-meta">
                        <div className="card-title" title=${item.id}>${item.id}</div>
                        <div className="card-tags">
                          <span className="meta-tag date">${dt}</span>
                          <span className="meta-tag collection">${item.collection}</span>
                          ${cloud ? html`<span className="meta-tag cloud">${cloud}</span>` : null}
                        </div>

                        <!-- Downloadable Assets -->
                        <div className="assets-drawer">
                          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                            <span className="assets-label" style=${{ margin: 0 }}>Available Bands / Assets:</span>
                            <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <button
                                type="button"
                                className="stage-asset-chip core-btn"
                                onClick=${() => handleDownloadAllCore(item)}
                                title="Download essential bands together"
                              >
                                ⚡ Download Core Bands (${item.collection.includes('sentinel-1') ? 'VV+VH' : 'RGB+NIR'})
                              </button>
                              ${Object.values(activeDownloads).some(
                                (d) => d.item_id === item.id && (d.status === 'downloading' || d.status === 'starting' || d.status === 'fetching_metadata')
                              ) ? html`
                                <button
                                  type="button"
                                  className="stac-download-cancel-btn"
                                  onClick=${() => handleCancelItemDownloads(item)}
                                  title="Cancel all downloads for this scene"
                                >
                                  ✕ Cancel
                                </button>
                              ` : null}
                            </div>
                          </div>
                          <div className="asset-buttons-row" style=${{ flexWrap: 'wrap', gap: '4px' }}>
                            ${(item.assets || []).map((a) => {
                              const stageId = `${item.id}_${a.key}`;
                              const dlInfo = activeDownloads[stageId];
                              const isCancelled = dlInfo && dlInfo.status === 'cancelled';
                              const isDownloading = !isCancelled && ((dlInfo && (dlInfo.status === 'downloading' || dlInfo.status === 'starting' || dlInfo.status === 'fetching_metadata')) || !!stagingKeys[stageId]);
                              const isStaged = (dlInfo && dlInfo.status === 'completed') || !!stagedKeysRef.current[stageId];
                              const pctText = dlInfo && dlInfo.percent != null && dlInfo.percent > 0 ? `${Math.round(dlInfo.percent)}%` : 'Staging…';

                              return html`
                                <button
                                  key=${a.key}
                                  type="button"
                                  className="stage-asset-chip ${isStaged ? 'staged' : ''} ${isDownloading ? 'downloading' : ''}"
                                  onClick=${() => {
                                    if (isDownloading) {
                                      handleCancelDownload(stageId);
                                    } else {
                                      handleStageAsset(item, a.key);
                                    }
                                  }}
                                  title=${isDownloading ? 'Click to cancel download' : (a.description || a.title)}
                                >
                                  ${isDownloading ? html`<span>⏳ ${pctText} <span style=${{ color: '#EF4444', marginLeft: '3px', fontWeight: 'bold' }}>✕</span></span>` : (isStaged ? `✓ ${a.key}` : `⬇ ${a.key}`)}
                                </button>
                              `;
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  `;
                })}
              </div>
            </div>
          ` : null}
        </div>
      </div>
    </div>
  `;
}
