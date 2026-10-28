import { html, React } from '../html.js';

const { useState, useEffect, useRef } = React;

export function GlobeView({
  tasks,
  activeTaskId,
  onOpenStacSearchWithAoi,
  onSendAoiToTask,
  pendingOverlay,
  onPendingOverlayConsumed,
}) {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);

  const [aoiMode, setAoiMode] = useState(false);
  const [selectedBbox, setSelectedBbox] = useState(null); // [min_lon, min_lat, max_lon, max_lat]
  const [aoiAreaKm2, setAoiAreaKm2] = useState(null);
  const [activeLayers, setActiveLayers] = useState([]);
  const [layerOpacity, setLayerOpacity] = useState(0.85);
  const [inspectorInfo, setInspectorInfo] = useState(null);

  // Initialize MapLibre 3D Globe
  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (typeof maplibregl === 'undefined') {
      console.warn('MapLibre GL JS not loaded yet');
      return;
    }

    if (mapInstanceRef.current) return; // already initialized

    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: {
          version: 8,
          sources: {
            'satellite-tiles': {
              type: 'raster',
              tiles: [
                'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
              ],
              tileSize: 256,
              attribution: 'Esri, Maxar, Earthstar Geographics',
            },
          },
          layers: [
            {
              id: 'satellite-basemap',
              type: 'raster',
              source: 'satellite-tiles',
              minzoom: 0,
              maxzoom: 19,
            },
          ],
          sky: {
            'sky-color': '#0B1015',
            'sky-horizon-blend': 0.6,
            'horizon-color': '#1E2C33',
            'horizon-fog-blend': 0.8,
            'fog-color': '#080E13',
            'fog-ground-blend': 0.5,
          },
        },
        center: [55.27, 25.20], // Dubai default view
        zoom: 3.2,
        pitch: 25,
        bearing: 0,
      });

      // Set native 3D Globe projection
      map.on('style.load', () => {
        try {
          if (typeof map.setProjection === 'function') {
            map.setProjection({ type: 'globe' });
          }
        } catch (e) {
          console.warn('Globe projection fallback:', e);
        }

        // Add AOI vector source & layers
        map.addSource('aoi-source', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        });

        map.addLayer({
          id: 'aoi-fill',
          type: 'fill',
          source: 'aoi-source',
          paint: {
            'fill-color': '#0F766E',
            'fill-opacity': 0.25,
          },
        });

        map.addLayer({
          id: 'aoi-stroke',
          type: 'line',
          source: 'aoi-source',
          paint: {
            'line-color': '#14B8A6',
            'line-width': 2.5,
            'line-dasharray': [2, 1],
          },
        });
      });

      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-left');

      mapInstanceRef.current = map;
    } catch (err) {
      console.error('Failed to initialize 3D Globe:', err);
    }

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  // Handle Interactive AOI Drag Selection
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    let startCoord = null;
    let isDrawing = false;

    const onMouseDown = (e) => {
      if (!aoiMode) return;
      if (e.originalEvent.button !== 0) return; // only left click
      isDrawing = true;
      startCoord = [e.lngLat.lng, e.lngLat.lat];
      map.getCanvas().style.cursor = 'crosshair';
      e.preventDefault();
    };

    const onMouseMove = (e) => {
      if (!isDrawing || !startCoord) return;
      const curCoord = [e.lngLat.lng, e.lngLat.lat];
      const minX = Math.min(startCoord[0], curCoord[0]);
      const maxX = Math.max(startCoord[0], curCoord[0]);
      const minY = Math.min(startCoord[1], curCoord[1]);
      const maxY = Math.max(startCoord[1], curCoord[1]);

      const aoiPoly = {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [minX, minY],
              [maxX, minY],
              [maxX, maxY],
              [minX, maxY],
              [minX, minY],
            ],
          ],
        },
      };

      const source = map.getSource('aoi-source');
      if (source) {
        source.setData({
          type: 'FeatureCollection',
          features: [aoiPoly],
        });
      }
    };

    const onMouseUp = (e) => {
      if (!isDrawing || !startCoord) return;
      isDrawing = false;
      const curCoord = [e.lngLat.lng, e.lngLat.lat];
      const minX = Math.min(startCoord[0], curCoord[0]);
      const maxX = Math.max(startCoord[0], curCoord[0]);
      const minY = Math.min(startCoord[1], curCoord[1]);
      const maxY = Math.max(startCoord[1], curCoord[1]);

      if (Math.abs(maxX - minX) > 0.005 && Math.abs(maxY - minY) > 0.005) {
        const bbox = [
          parseFloat(minX.toFixed(5)),
          parseFloat(minY.toFixed(5)),
          parseFloat(maxX.toFixed(5)),
          parseFloat(maxY.toFixed(5)),
        ];
        setSelectedBbox(bbox);

        // Approximate area calculation in km²
        const midLat = (minY + maxY) / 2;
        const widthKm = Math.abs(maxX - minX) * 111.32 * Math.cos((midLat * Math.PI) / 180);
        const heightKm = Math.abs(maxY - minY) * 110.574;
        const area = (widthKm * heightKm).toFixed(2);
        setAoiAreaKm2(area);
      }
      setAoiMode(false);
      map.getCanvas().style.cursor = '';
    };

    map.on('mousedown', onMouseDown);
    map.on('mousemove', onMouseMove);
    map.on('mouseup', onMouseUp);

    return () => {
      map.off('mousedown', onMouseDown);
      map.off('mousemove', onMouseMove);
      map.off('mouseup', onMouseUp);
    };
  }, [aoiMode]);

  // Load Task Deliverables as Georeferenced Overlays on the Globe
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Collect all generated GeoTIFFs across active tasks
    const tiffArtifacts = [];
    Object.entries(tasks || {}).forEach(([tid, tdata]) => {
      (tdata.artifacts || []).forEach((art) => {
        const filename = typeof art === 'string' ? art : art.name || '';
        const artUrl = typeof art === 'string' ? null : art.url;
        if (filename.toLowerCase().endsWith('.tif') || filename.toLowerCase().endsWith('.tiff')) {
          tiffArtifacts.push({
            taskId: tid,
            filename: filename.split(/[/\\]/).pop(),
            fullPath: artUrl || filename,
          });
        }
      });
    });

    if (tiffArtifacts.length === 0) return;

    // Check bounds and load layer for each GeoTIFF
    tiffArtifacts.forEach(async (art) => {
      const layerId = `overlay-${art.filename.replace(/[^a-zA-Z0-9]/g, '_')}`;
      if (map.getLayer(layerId)) return; // already added

      try {
        const resp = await fetch(`/api/raster/bounds?path=${encodeURIComponent(art.fullPath)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.ok || !data.coordinates) return;

        // Add Image Source with true georeferenced coordinates and rendered PNG
        const sourceId = `src-${layerId}`;
        if (!map.getSource(sourceId)) {
          const imgUrl = data.png_url || `/api/raster/png?path=${encodeURIComponent(art.fullPath)}`;
          map.addSource(sourceId, {
            type: 'image',
            url: imgUrl,
            coordinates: data.coordinates, // [top-left, top-right, bottom-right, bottom-left]
          });

          map.addLayer({
            id: layerId,
            type: 'raster',
            source: sourceId,
            paint: {
              'raster-opacity': layerOpacity,
              'raster-fade-duration': 300,
            },
          });

          setActiveLayers((prev) => [
            ...prev.filter(l => l.id !== layerId),
            {
              id: layerId,
              title: art.filename,
              taskId: art.taskId,
              bbox: data.bbox,
              crs: data.crs,
            },
          ]);
        }
      } catch (err) {
        console.warn('Could not overlay raster:', art.filename, err);
      }
    });
  }, [tasks, layerOpacity]);

  // Handle explicit artifact overlay request from globe icon button
  useEffect(() => {
    if (!pendingOverlay) return;

    let cancelled = false;
    let timerId = null;

    const execute = () => {
      if (cancelled) return;
      const map = mapInstanceRef.current;
      if (!map) {
        // Map is still mounting, retry in 100ms
        timerId = setTimeout(execute, 100);
        return;
      }

      const art = pendingOverlay;
      const fname = typeof art === 'string' ? art : art.name || '';
      const artUrl = typeof art === 'string' ? null : art.url;
      if (!artUrl && !fname) {
        if (onPendingOverlayConsumed) onPendingOverlayConsumed();
        return;
      }

      const fullPath = artUrl || fname;
      const filename = fname.split(/[/\\]/).pop();
      const layerId = `overlay-${filename.replace(/[^a-zA-Z0-9]/g, '_')}`;

      const loadOverlay = async () => {
        try {
          const resp = await fetch(`/api/raster/bounds?path=${encodeURIComponent(fullPath)}`);
          if (!resp.ok) {
            console.warn('Raster bounds failed with HTTP', resp.status);
            return;
          }
          const data = await resp.json();
          if (!data.ok || !data.coordinates) {
            console.warn('Raster bounds data invalid:', data);
            return;
          }

          const sourceId = `src-${layerId}`;
          const pngUrl = data.png_url || `/api/raster/png?path=${encodeURIComponent(fullPath)}`;

          if (!map.getSource(sourceId)) {
            map.addSource(sourceId, {
              type: 'image',
              url: pngUrl,
              coordinates: data.coordinates,
            });
            map.addLayer({
              id: layerId,
              type: 'raster',
              source: sourceId,
              paint: { 'raster-opacity': layerOpacity, 'raster-fade-duration': 300 },
            });
            setActiveLayers(prev => [
              ...prev.filter(l => l.id !== layerId),
              { id: layerId, title: filename, bbox: data.bbox, crs: data.crs },
            ]);
          }

          // Smoothly zoom globe to raster extent
          if (data.bbox) {
            map.fitBounds(
              [[data.bbox[0], data.bbox[1]], [data.bbox[2], data.bbox[3]]],
              { padding: 80, duration: 1800 }
            );
          }
        } catch (err) {
          console.warn('Globe overlay failed:', filename, err);
        } finally {
          if (onPendingOverlayConsumed) onPendingOverlayConsumed();
        }
      };

      let called = false;
      const safeLoadOverlay = () => {
        if (called || cancelled) return;
        called = true;
        loadOverlay();
      };

      if (map.isStyleLoaded()) {
        safeLoadOverlay();
      } else {
        map.once('load', safeLoadOverlay);
        map.once('style.load', safeLoadOverlay);
      }
    };

    execute();

    return () => {
      cancelled = true;
      if (timerId) clearTimeout(timerId);
    };
  }, [pendingOverlay]);

  // Zoom to BBOX or Layer
  const zoomToExtent = (bbox) => {
    const map = mapInstanceRef.current;
    if (!map || !bbox) return;
    map.fitBounds(
      [
        [bbox[0], bbox[1]],
        [bbox[2], bbox[3]],
      ],
      { padding: 80, duration: 1800 }
    );
  };

  // Clear Selected AOI
  const clearAoi = () => {
    setSelectedBbox(null);
    setAoiAreaKm2(null);
    const map = mapInstanceRef.current;
    if (map) {
      const source = map.getSource('aoi-source');
      if (source) {
        source.setData({ type: 'FeatureCollection', features: [] });
      }
    }
  };

  return html`
    <div className="globe-view-wrapper">
      <!-- 3D Globe WebGL Container -->
      <div ref=${mapContainerRef} className="globe-maplibre-canvas" />

      <!-- Top Overlay Toolbar -->
      <div className="globe-hud-toolbar">
        <div className="hud-pill-group">
          <button
            type="button"
            className="hud-btn ${aoiMode ? 'active-draw' : ''}"
            onClick=${() => setAoiMode(!aoiMode)}
            title="Click and drag on the 3D globe to draw an Area of Interest"
          >
            <span>${aoiMode ? '✍️ Drag box on globe…' : '⬛ Draw AOI Bounding Box'}</span>
          </button>

          ${selectedBbox ? html`
            <div className="hud-badge aoi-stats">
              <span>📍 AOI: ${aoiAreaKm2 ? `${aoiAreaKm2} km²` : 'Selected'}</span>
              <button type="button" className="clear-aoi-btn" onClick=${clearAoi} title="Clear AOI">×</button>
            </div>

            <button
              type="button"
              className="hud-btn highlight-btn"
              onClick=${() => onOpenStacSearchWithAoi(selectedBbox)}
              title="Search Microsoft Planetary Computer satellite data for this area"
            >
              <span>🛰️ Retrieve Satellite Data</span>
            </button>

            <button
              type="button"
              className="hud-btn action-btn"
              onClick=${() => onSendAoiToTask(selectedBbox, activeTaskId)}
              title="Send coordinates into prompt of active task"
            >
              <span>⚡ Send to #${activeTaskId.replace('task_', '')}</span>
            </button>
          ` : null}
        </div>
      </div>

      <!-- Layers & Visualization Floating Widget -->
      ${activeLayers.length > 0 ? html`
        <div className="globe-layers-panel">
          <div className="layers-header">
            <span style=${{ fontWeight: 600 }}>🗺️ Analysis Overlays</span>
            <span className="mono" style=${{ fontSize: '11px', color: '#8FA39A' }}>${activeLayers.length}</span>
          </div>

          <div style=${{ padding: '8px 12px' }}>
            <label style=${{ fontSize: '11px', color: '#8FA39A', display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span>Opacity</span>
              <span>${Math.round(layerOpacity * 100)}%</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value=${layerOpacity}
              onChange=${(e) => {
                const val = parseFloat(e.target.value);
                setLayerOpacity(val);
                const map = mapInstanceRef.current;
                if (map) {
                  activeLayers.forEach((l) => {
                    if (map.getLayer(l.id)) {
                      map.setPaintProperty(l.id, 'raster-opacity', val);
                    }
                  });
                }
              }}
              style=${{ width: '100%', accentColor: '#14B8A6' }}
            />
          </div>

          <div className="layers-list">
            ${activeLayers.map((l) => html`
              <div key=${l.id} className="layer-item">
                <span className="layer-name" title=${l.title}>${l.title}</span>
                <button
                  type="button"
                  className="layer-zoom-btn"
                  onClick=${() => zoomToExtent(l.bbox)}
                  title="Zoom to raster bounds"
                >
                  🔍
                </button>
              </div>
            `)}
          </div>
        </div>
      ` : null}

      <!-- Bottom Hint Bar -->
      <div className="globe-footer-hint">
        <span>💡 3D Globe: Rotate 360° with Left Click • Tilt with Right Click / Ctrl+Drag • Scroll to Zoom</span>
      </div>
    </div>
  `;
}
