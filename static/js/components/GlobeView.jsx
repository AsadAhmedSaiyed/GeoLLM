// GeoLLM 3D Globe & Map View (React 18 JSX Component)
import React, { useState, useEffect, useRef, memo } from 'https://esm.sh/react@18.2.0';

export const GlobeView = memo(function GlobeView({
  tasks = {},
  activeTaskId = 'task_1',
  activeWorkspaceName = '',
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
  const [showInspector, setShowInspector] = useState(false);
  const [overlaysCollapsed, setOverlaysCollapsed] = useState(false);

  // Initialize MapLibre 3D Globe
  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (typeof maplibregl === 'undefined') {
      console.warn('MapLibre GL JS not loaded yet');
      return;
    }

    if (mapInstanceRef.current) return;

    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        preserveDrawingBuffer: true,
        fadeDuration: 0,
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
        center: [55.27, 25.20],
        zoom: 3.2,
        pitch: 25,
        bearing: 0,
      });

      map.on('style.load', () => {
        try {
          if (typeof map.setProjection === 'function') {
            map.setProjection({ type: 'globe' });
          }
        } catch (e) {
          console.warn('Globe projection fallback:', e);
        }

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

      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');

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

  // Handle ESC key to clear AOI or cancel draw mode
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (aoiMode) {
          setAoiMode(false);
          if (mapInstanceRef.current) mapInstanceRef.current.getCanvas().style.cursor = '';
        } else if (selectedBbox) {
          clearAoi();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [aoiMode, selectedBbox]);

  // Handle Interactive AOI Drag Selection
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    let startCoord = null;
    let isDrawing = false;

    const onMouseDown = (e) => {
      if (!aoiMode) return;
      if (e.originalEvent.button !== 0) return;
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

    tiffArtifacts.forEach(async (art) => {
      const layerId = `overlay-${art.filename.replace(/[^a-zA-Z0-9]/g, '_')}`;
      if (map.getLayer(layerId)) return;

      try {
        const resp = await fetch(`/api/raster/bounds?path=${encodeURIComponent(art.fullPath)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.ok || !data.coordinates) return;

        const sourceId = `src-${layerId}`;
        if (!map.getSource(sourceId)) {
          const imgUrl = data.png_url || `/api/raster/png?path=${encodeURIComponent(art.fullPath)}`;
          map.addSource(sourceId, {
            type: 'image',
            url: imgUrl,
            coordinates: data.coordinates,
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
          if (!resp.ok) return;
          const data = await resp.json();
          if (!data.ok || !data.coordinates) return;

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

  const clearAoi = () => {
    setSelectedBbox(null);
    setAoiAreaKm2(null);
    setAoiMode(false);
    const map = mapInstanceRef.current;
    if (map) {
      map.getCanvas().style.cursor = '';
      const source = map.getSource('aoi-source');
      if (source) {
        source.setData({ type: 'FeatureCollection', features: [] });
      }
    }
  };

  // Dynamic Inspector Data (Zero hardcoded values)
  const activeTask = tasks[activeTaskId] || {};
  const stacPreview = activeTask.stacPreview || null;
  const activeScene = (stacPreview?.scenes && stacPreview.scenes.length > 0) ? stacPreview.scenes[0] : null;

  const currentBbox = selectedBbox || (activeLayers.length > 0 ? activeLayers[0].bbox : null);
  const activeCrs = (activeLayers.length > 0 && activeLayers[0].crs) ? activeLayers[0].crs : (selectedBbox ? 'EPSG:4326 (WGS 84)' : null);

  const footprintStr = currentBbox
    ? `${currentBbox[0].toFixed(4)}, ${currentBbox[1].toFixed(4)} → ${currentBbox[2].toFixed(4)}, ${currentBbox[3].toFixed(4)}`
    : null;
  const centreStr = currentBbox
    ? `${((currentBbox[0] + currentBbox[2]) / 2).toFixed(4)}, ${((currentBbox[1] + currentBbox[3]) / 2).toFixed(4)}`
    : null;

  return (
    <div className="globe-view-wrapper" style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      
      {/* 3D Globe WebGL Container */}
      <div ref={mapContainerRef} className="globe-maplibre-canvas" style={{ width: '100%', height: '100%' }} />

      {/* Top Floating HUD Toolbar on Far Right Corner */}
      <div className="globe-hud-toolbar" style={{ position: 'absolute', top: '14px', right: '16px', left: 'auto', transform: 'none', zIndex: 20, display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', justifyContent: 'flex-end' }}>
        
        {/* Draw AOI Button or Active Drawing Status */}
        {!aoiMode ? (
          <button
            type="button"
            className="hud-btn"
            style={{
              background: '#0F766E',
              color: '#FFFFFF',
              border: 'none',
              padding: '7px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 2px 8px rgba(0,0,0,0.4)'
            }}
            onClick={() => setAoiMode(true)}
            title="Click and drag on the 3D globe to draw an Area of Interest"
          >
            <span>⬛ Draw AOI Bounding Box</span>
          </button>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(15, 23, 42, 0.95)', padding: '4px 6px', borderRadius: '6px', border: '1px solid #14B8A6' }}>
            <span style={{ fontSize: '11.5px', color: '#14B8A6', fontWeight: 600, padding: '0 6px' }}>
              ✍️ Click & Drag on Globe...
            </span>
            <button
              type="button"
              onClick={clearAoi}
              style={{
                background: '#EF4444',
                color: '#FFFFFF',
                border: 'none',
                padding: '4px 10px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              Cancel Drawing
            </button>
          </div>
        )}

        {/* When AOI is active: Clearly show stats and UNMISTAKABLE CLEAR / CANCEL BUTTON */}
        {selectedBbox && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(15, 23, 42, 0.95)', backdropFilter: 'blur(8px)', padding: '4px 8px', borderRadius: '6px', border: '1px solid #334155', boxShadow: '0 2px 10px rgba(0,0,0,0.5)' }}>
            <span className="mono" style={{ color: '#38BDF8', fontSize: '11px', fontWeight: 600, padding: '0 4px' }}>
              📍 AOI: {aoiAreaKm2 ? `${aoiAreaKm2} km²` : 'Selected'}
            </span>

            {/* HIGH VISIBILITY CANCEL / CLEAR AOI BUTTON */}
            <button
              type="button"
              className="cancel-aoi-btn"
              onClick={clearAoi}
              title="Clear selected Area of Interest (Esc)"
              style={{
                background: '#EF4444',
                color: '#FFFFFF',
                border: 'none',
                padding: '5px 10px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <span>✕</span>
              <span>Clear AOI</span>
            </button>

            <button
              type="button"
              style={{ background: '#0284C7', color: '#FFFFFF', border: 'none', padding: '5px 12px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, cursor: 'pointer' }}
              onClick={() => onOpenStacSearchWithAoi(selectedBbox)}
              title="Search Microsoft Planetary Computer satellite data for this area"
            >
              🛰️ Retrieve Satellite Data
            </button>

            <button
              type="button"
              style={{ background: '#0F766E', color: '#FFFFFF', border: 'none', padding: '5px 12px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, cursor: 'pointer' }}
              onClick={() => onSendAoiToTask(selectedBbox, activeTaskId)}
              title={`Send AOI coordinates into ${activeWorkspaceName || activeTaskId}`}
            >
              ⚡ Send to Workspace
            </button>
          </div>
        )}

        {/* Toggle Metadata Inspector Button */}
        <button
          type="button"
          style={{
            background: showInspector ? 'rgba(20, 184, 166, 0.2)' : 'rgba(15, 23, 42, 0.9)',
            color: showInspector ? '#14B8A6' : '#94A3B8',
            border: showInspector ? '1px solid #14B8A6' : '1px solid #334155',
            padding: '7px 12px',
            borderRadius: '6px',
            fontSize: '11.5px',
            cursor: 'pointer',
            fontWeight: 500,
            backdropFilter: 'blur(8px)'
          }}
          onClick={() => setShowInspector(!showInspector)}
          title="Toggle Metadata Inspector Panel"
        >
          {showInspector ? 'Hide Inspector' : 'Show Inspector'}
        </button>
      </div>

      {/* Right-Hand Floating Stack below Top Toolbar (Never overlaps top toolbar or bottom-right zoom controls) */}
      {(showInspector || activeLayers.length > 0) && (
        <div
          className="globe-right-floating-stack"
          style={{
            position: 'absolute',
            top: '58px',
            right: '16px',
            bottom: 'auto',
            zIndex: 18,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: '10px',
            maxHeight: 'calc(100% - 190px)',
            pointerEvents: 'none',
          }}
        >
          {/* Floating Metadata Inspector Card (100% Dynamic, Zero Hardcoded Values) */}
          {showInspector && (
            <div
              className="globe-metadata-inspector"
              style={{
                position: 'relative',
                width: '280px',
                background: 'rgba(9, 13, 20, 0.94)',
                backdropFilter: 'blur(12px)',
                border: '1px solid #1E293B',
                borderRadius: '8px',
                padding: '14px',
                fontSize: '11.5px',
                color: '#94A3B8',
                boxShadow: '0 8px 30px rgba(0,0,0,0.7)',
                pointerEvents: 'auto',
                flexShrink: 0,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px', borderBottom: '1px solid #1E293B', paddingBottom: '6px' }}>
                <span style={{ fontWeight: 700, color: '#F1F5F9', fontSize: '12px' }}>Metadata Inspector</span>
                <button
                  type="button"
                  onClick={() => setShowInspector(false)}
                  style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', fontSize: '14px', padding: '0 4px' }}
                >
                  ×
                </button>
              </div>

              {currentBbox ? (
                <>
                  {/* Geometry Section */}
                  <div style={{ marginBottom: '12px' }}>
                    <div style={{ fontWeight: 700, color: '#38BDF8', fontSize: '10.5px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
                      Geometry
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontFamily: 'monospace', fontSize: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: '#64748B' }}>Footprint</span>
                        <span style={{ color: '#E2E8F0', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={footprintStr}>
                          {footprintStr}
                        </span>
                      </div>
                      {aoiAreaKm2 && (
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Area</span>
                          <span style={{ color: '#E2E8F0' }}>{aoiAreaKm2} km²</span>
                        </div>
                      )}
                      {centreStr && (
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Centre</span>
                          <span style={{ color: '#E2E8F0' }}>{centreStr}</span>
                        </div>
                      )}
                      {activeCrs && (
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>CRS</span>
                          <span style={{ color: '#14B8A6' }}>{activeCrs}</span>
                        </div>
                      )}
                      {activeScene?.native_resolution_m && (
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Pixel size</span>
                          <span style={{ color: '#E2E8F0' }}>{activeScene.native_resolution_m} m</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Acquisition Section (Only shown when actual STAC/scene data exists) */}
                  {activeScene && (
                    <div>
                      <div style={{ fontWeight: 700, color: '#38BDF8', fontSize: '10.5px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
                        Acquisition
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontFamily: 'monospace', fontSize: '10px' }}>
                        {activeScene.datetime && (
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#64748B' }}>Captured</span>
                            <span style={{ color: '#E2E8F0' }}>{activeScene.datetime.slice(0, 10)}</span>
                          </div>
                        )}
                        {activeScene.collection && (
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#64748B' }}>Platform</span>
                            <span style={{ color: '#E2E8F0' }}>{activeScene.collection}</span>
                          </div>
                        )}
                        {activeScene.cloud_cover != null && (
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#64748B' }}>Cloud cover</span>
                            <span style={{ color: '#E2E8F0' }}>{activeScene.cloud_cover}%</span>
                          </div>
                        )}
                        {activeScene.aoi_coverage_pct != null && (
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#64748B' }}>AOI Coverage</span>
                            <span style={{ color: '#E2E8F0' }}>{activeScene.aoi_coverage_pct}%</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div style={{ padding: '16px 4px', textAlign: 'center', color: '#64748B', fontSize: '11px' }}>
                  No active selection. Draw a bounding box on the globe to inspect coordinates.
                </div>
              )}
            </div>
          )}

          {/* Layers & Visualization Overlays (Stacked cleanly below Inspector & Top Toolbar) */}
          {activeLayers.length > 0 && (
            <div
              className="globe-layers-panel"
              style={{
                position: 'relative',
                top: 'auto',
                bottom: 'auto',
                right: 'auto',
                width: '250px',
                background: 'rgba(9, 13, 20, 0.94)',
                backdropFilter: 'blur(10px)',
                border: '1px solid #1E293B',
                borderRadius: '8px',
                padding: '10px',
                boxShadow: '0 8px 24px rgba(0,0,0,0.65)',
                pointerEvents: 'auto',
                display: 'flex',
                flexDirection: 'column',
                minHeight: 0,
              }}
            >
              <div
                className="layers-header"
                onClick={() => setOverlaysCollapsed(!overlaysCollapsed)}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: overlaysCollapsed ? 0 : '8px',
                  padding: 0,
                  borderBottom: 'none',
                  cursor: 'pointer',
                  userSelect: 'none',
                }}
              >
                <span style={{ fontWeight: 600, fontSize: '11.5px', color: '#F1F5F9' }}>🗺️ Analysis Overlays</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span className="mono" style={{ fontSize: '10px', color: '#38BDF8', background: 'rgba(56, 189, 248, 0.15)', padding: '1px 6px', borderRadius: '10px' }}>
                    {activeLayers.length}
                  </span>
                  <span style={{ fontSize: '10px', color: '#94A3B8' }}>{overlaysCollapsed ? '▼' : '▲'}</span>
                </div>
              </div>

              {!overlaysCollapsed && (
                <>
                  <div style={{ marginBottom: '8px' }}>
                    <label style={{ fontSize: '10px', color: '#94A3B8', display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span>Opacity</span>
                      <span>{Math.round(layerOpacity * 100)}%</span>
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={layerOpacity}
                      onChange={(e) => {
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
                      style={{ width: '100%', accentColor: '#14B8A6' }}
                    />
                  </div>

                  <div className="layers-list" style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '160px', overflowY: 'auto', padding: 0 }}>
                    {activeLayers.map((l) => (
                      <div key={l.id} className="layer-item" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#111827', padding: '5px 8px', borderRadius: '4px' }}>
                        <span className="layer-name mono" title={l.title} style={{ fontSize: '10px', color: '#E2E8F0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '175px' }}>{l.title}</span>
                        <button
                          type="button"
                          className="layer-zoom-btn"
                          onClick={() => zoomToExtent(l.bbox)}
                          title="Zoom to raster bounds"
                          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '11px' }}
                        >
                          🔍
                        </button>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

    </div>
  );
});
