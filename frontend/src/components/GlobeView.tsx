import React, { useState, useEffect, useRef, memo } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';

if (typeof maplibregl.setWorkerUrl === 'function') {
  maplibregl.setWorkerUrl(maplibreWorkerUrl);
}
import { TaskState } from '@/types/task';
import { ArtifactItem } from '@/types/sse';
import { api } from '@/services/api';
import {
  SquareDashedMousePointer,
  Satellite,
  Zap,
  X,
  Info,
  Layers,
  Search,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

export interface GlobeViewProps {
  tasks: Record<string, TaskState>;
  activeTaskId?: string;
  activeWorkspaceName?: string;
  onOpenStacSearchWithAoi?: (bbox: number[]) => void;
  onSendAoiToTask?: (bbox: number[], taskId: string) => void;
  pendingOverlay?: string | ArtifactItem | null;
  onPendingOverlayConsumed?: () => void;
}

interface ActiveOverlayLayer {
  id: string;
  title: string;
  taskId?: string;
  bbox?: [number, number, number, number];
  crs?: string;
}

export const GlobeView: React.FC<GlobeViewProps> = memo(function GlobeView({
  tasks = {},
  activeTaskId = 'task_1',
  activeWorkspaceName = '',
  onOpenStacSearchWithAoi,
  onSendAoiToTask,
  pendingOverlay,
  onPendingOverlayConsumed,
}) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<maplibregl.Map | null>(null);

  const [aoiMode, setAoiMode] = useState(false);
  const [selectedBbox, setSelectedBbox] = useState<number[] | null>(null);
  const [aoiAreaKm2, setAoiAreaKm2] = useState<string | null>(null);
  const [activeLayers, setActiveLayers] = useState<ActiveOverlayLayer[]>([]);
  const [layerOpacity, setLayerOpacity] = useState<number>(0.85);
  const [showInspector, setShowInspector] = useState<boolean>(false);
  const [overlaysCollapsed, setOverlaysCollapsed] = useState<boolean>(false);

  const clearAoi = () => {
    setSelectedBbox(null);
    setAoiAreaKm2(null);
    setAoiMode(false);
    const map = mapInstanceRef.current;
    if (map) {
      map.getCanvas().style.cursor = '';
      const source = map.getSource('aoi-source') as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData({ type: 'FeatureCollection', features: [] });
      }
    }
  };

  // Initialize MapLibre 3D Globe + ResizeObserver for smooth ResizablePanel dragging
  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (mapInstanceRef.current) return;

    let resizeObserver: ResizeObserver | null = null;
    let rafId: number | null = null;

    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        canvasContextAttributes: { preserveDrawingBuffer: true },
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
        } as maplibregl.StyleSpecification,
        center: [55.27, 25.2],
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

      map.addControl(
        new maplibregl.NavigationControl({ visualizePitch: true }),
        'bottom-right'
      );

      mapInstanceRef.current = map;

      resizeObserver = new ResizeObserver(() => {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(() => {
          mapInstanceRef.current?.resize();
        });
      });
      resizeObserver.observe(mapContainerRef.current);
    } catch (err) {
      console.error('Failed to initialize 3D Globe:', err);
    }

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      resizeObserver?.disconnect();
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  // Handle ESC key to clear AOI or cancel draw mode
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (aoiMode) {
          setAoiMode(false);
          if (mapInstanceRef.current) {
            mapInstanceRef.current.getCanvas().style.cursor = '';
          }
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

    let startCoord: [number, number] | null = null;
    let isDrawing = false;

    const onMouseDown = (e: maplibregl.MapMouseEvent) => {
      if (!aoiMode) return;
      if (e.originalEvent.button !== 0) return;
      isDrawing = true;
      startCoord = [e.lngLat.lng, e.lngLat.lat];
      map.getCanvas().style.cursor = 'crosshair';
      e.preventDefault();
    };

    const onMouseMove = (e: maplibregl.MapMouseEvent) => {
      if (!isDrawing || !startCoord) return;
      const curCoord: [number, number] = [e.lngLat.lng, e.lngLat.lat];
      const minX = Math.min(startCoord[0], curCoord[0]);
      const maxX = Math.max(startCoord[0], curCoord[0]);
      const minY = Math.min(startCoord[1], curCoord[1]);
      const maxY = Math.max(startCoord[1], curCoord[1]);

      const source = map.getSource('aoi-source') as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData({
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              properties: {},
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
            },
          ],
        });
      }
    };

    const onMouseUp = (e: maplibregl.MapMouseEvent) => {
      if (!isDrawing || !startCoord) return;
      isDrawing = false;
      const curCoord: [number, number] = [e.lngLat.lng, e.lngLat.lat];
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
        const widthKm =
          Math.abs(maxX - minX) * 111.32 * Math.cos((midLat * Math.PI) / 180);
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

    const tiffArtifacts: Array<{ taskId: string; filename: string; fullPath: string }> = [];
    Object.entries(tasks || {}).forEach(([tid, tdata]) => {
      (tdata.artifacts || []).forEach((art) => {
        const filename = typeof art === 'string' ? art : art.name || '';
        const artUrl = typeof art === 'string' ? null : art.url || art.path;
        if (
          filename.toLowerCase().endsWith('.tif') ||
          filename.toLowerCase().endsWith('.tiff')
        ) {
          tiffArtifacts.push({
            taskId: tid,
            filename: filename.replace(/\\/g, '/').split('/').pop() || filename,
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
        const data = await api.getRasterBounds(art.fullPath);
        if (!data.ok || !data.coordinates) return;

        const sourceId = `src-${layerId}`;
        if (!map.getSource(sourceId)) {
          const imgUrl = data.png_url || api.getRasterPngUrl(art.fullPath);
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
            ...prev.filter((l) => l.id !== layerId),
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
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const execute = () => {
      if (cancelled) return;
      const map = mapInstanceRef.current;
      if (!map) {
        timerId = setTimeout(execute, 100);
        return;
      }

      const art = pendingOverlay;
      const fname = typeof art === 'string' ? art : art.name || '';
      const artUrl = typeof art === 'string' ? null : art.url || art.path;
      if (!artUrl && !fname) {
        onPendingOverlayConsumed?.();
        return;
      }

      const fullPath = artUrl || fname;
      const filename = fname.replace(/\\/g, '/').split('/').pop() || fname;
      const layerId = `overlay-${filename.replace(/[^a-zA-Z0-9]/g, '_')}`;

      const loadOverlay = async () => {
        try {
          const data = await api.getRasterBounds(fullPath);
          if (!data.ok || !data.coordinates) return;

          const sourceId = `src-${layerId}`;
          const pngUrl = data.png_url || api.getRasterPngUrl(fullPath);

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
            setActiveLayers((prev) => [
              ...prev.filter((l) => l.id !== layerId),
              { id: layerId, title: filename, bbox: data.bbox, crs: data.crs },
            ]);
          }

          if (data.bbox) {
            map.fitBounds(
              [
                [data.bbox[0], data.bbox[1]],
                [data.bbox[2], data.bbox[3]],
              ],
              { padding: 80, duration: 1800 }
            );
          }
        } catch (err) {
          console.warn('Globe overlay failed:', filename, err);
        } finally {
          onPendingOverlayConsumed?.();
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
  }, [pendingOverlay, layerOpacity, onPendingOverlayConsumed]);

  const zoomToExtent = (bbox?: [number, number, number, number]) => {
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

  // Dynamic Inspector Data (Zero hardcoded values)
  const activeTask = tasks[activeTaskId];
  const stacPreview = activeTask?.stacPreview || null;
  const activeScene =
    stacPreview?.scenes && stacPreview.scenes.length > 0 ? stacPreview.scenes[0] : null;

  const currentBbox =
    selectedBbox || (activeLayers.length > 0 ? activeLayers[0].bbox : null);
  const activeCrs =
    activeLayers.length > 0 && activeLayers[0].crs
      ? activeLayers[0].crs
      : selectedBbox
      ? 'EPSG:4326 (WGS 84)'
      : null;

  const footprintStr = currentBbox
    ? `${currentBbox[0].toFixed(4)}, ${currentBbox[1].toFixed(4)} → ${currentBbox[2].toFixed(
        4
      )}, ${currentBbox[3].toFixed(4)}`
    : null;
  const centreStr = currentBbox
    ? `${((currentBbox[0] + currentBbox[2]) / 2).toFixed(4)}, ${(
        (currentBbox[1] + currentBbox[3]) /
        2
      ).toFixed(4)}`
    : null;

  return (
    <div className="relative w-full h-full overflow-hidden bg-background">
      {/* 3D Globe WebGL Container */}
      <div ref={mapContainerRef} className="w-full h-full" />

      {/* Top Floating HUD Toolbar on Far Right Corner */}
      <div className="absolute top-3.5 right-4 z-20 flex flex-wrap gap-2 items-center justify-end">
        {/* Draw AOI Button or Active Drawing Status */}
        {!aoiMode ? (
          <button
            type="button"
            onClick={() => setAoiMode(true)}
            title="Click and drag on the 3D globe to draw an Area of Interest"
            className="inline-flex items-center gap-1.5 bg-[#0F766E] hover:bg-[#0D9488] text-white px-3.5 py-1.5 rounded-none text-xs font-semibold shadow-lg transition-colors"
          >
            <SquareDashedMousePointer className="h-3.5 w-3.5" />
            <span>Draw AOI Bounding Box</span>
          </button>
        ) : (
          <div className="flex items-center gap-1.5 bg-slate-900/95 px-2.5 py-1 rounded-none border border-teal-500 shadow-lg">
            <span className="text-[11.5px] text-teal-400 font-semibold px-1">
              Click & Drag on Globe...
            </span>
            <button
              type="button"
              onClick={clearAoi}
              className="bg-rose-600 hover:bg-rose-500 text-white px-2.5 py-1 rounded-none text-[11px] font-semibold transition-colors"
            >
              Cancel Drawing
            </button>
          </div>
        )}

        {/* When AOI is active: stats + Clear / Retrieve STAC / Send to Workspace */}
        {selectedBbox && (
          <div className="flex items-center gap-1.5 bg-slate-900/95 backdrop-blur-md px-2.5 py-1 rounded-none border border-slate-700 shadow-xl">
            <span className="font-mono text-sky-400 text-[11px] font-semibold px-1">
              AOI: {aoiAreaKm2 ? `${aoiAreaKm2} km²` : 'Selected'}
            </span>

            <button
              type="button"
              onClick={clearAoi}
              title="Clear selected Area of Interest (Esc)"
              className="inline-flex items-center gap-1 bg-rose-600 hover:bg-rose-500 text-white px-2.5 py-1 rounded-none text-[11px] font-bold transition-colors"
            >
              <X className="h-3 w-3" />
              <span>Clear AOI</span>
            </button>

            {onOpenStacSearchWithAoi && (
              <button
                type="button"
                onClick={() => onOpenStacSearchWithAoi(selectedBbox)}
                title="Search Microsoft Planetary Computer satellite data for this area"
                className="inline-flex items-center gap-1 bg-sky-600 hover:bg-sky-500 text-white px-3 py-1 rounded-none text-[11px] font-semibold transition-colors"
              >
                <Satellite className="h-3 w-3" />
                <span>Retrieve Satellite Data</span>
              </button>
            )}

            {onSendAoiToTask && (
              <button
                type="button"
                onClick={() => onSendAoiToTask(selectedBbox, activeTaskId)}
                title={`Send AOI coordinates into ${activeWorkspaceName || activeTaskId}`}
                className="inline-flex items-center gap-1 bg-[#0F766E] hover:bg-[#0D9488] text-white px-3 py-1 rounded-none text-[11px] font-semibold transition-colors"
              >
                <Zap className="h-3 w-3" />
                <span>Send to Workspace</span>
              </button>
            )}
          </div>
        )}

        {/* Toggle Metadata Inspector Button */}
        <button
          type="button"
          onClick={() => setShowInspector((prev) => !prev)}
          title="Toggle Metadata Inspector Panel"
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-none text-[11.5px] font-medium backdrop-blur-md border transition-colors ${
            showInspector
              ? 'bg-teal-500/20 text-teal-400 border-teal-500'
              : 'bg-slate-900/90 text-muted-foreground border-slate-700 hover:text-foreground'
          }`}
        >
          <Info className="h-3.5 w-3.5" />
          <span>{showInspector ? 'Hide Inspector' : 'Show Inspector'}</span>
        </button>
      </div>

      {/* Right-Hand Floating Stack below Top Toolbar */}
      {(showInspector || activeLayers.length > 0) && (
        <div className="absolute top-[58px] right-4 z-[18] flex flex-col items-end gap-2.5 max-h-[calc(100%-190px)] pointer-events-none">
          {/* Floating Metadata Inspector Card */}
          {showInspector && (
            <div className="w-[280px] bg-card/95 backdrop-blur-md border border-border rounded-none p-3.5 text-[11.5px] text-muted-foreground shadow-2xl pointer-events-auto shrink-0">
              <div className="flex items-center justify-between mb-2.5 border-b border-border pb-1.5">
                <span className="font-bold text-foreground text-xs">Metadata Inspector</span>
                <button
                  type="button"
                  onClick={() => setShowInspector(false)}
                  className="text-muted-foreground hover:text-foreground px-1"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              {currentBbox ? (
                <>
                  {/* Geometry Section */}
                  <div className="mb-3">
                    <div className="font-bold text-sky-400 text-[10.5px] uppercase tracking-wider mb-1.5">
                      Geometry
                    </div>
                    <div className="flex flex-col gap-1 font-mono text-[10px]">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Footprint</span>
                        <span
                          className="text-foreground max-w-[160px] truncate"
                          title={footprintStr || ''}
                        >
                          {footprintStr}
                        </span>
                      </div>
                      {aoiAreaKm2 && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Area</span>
                          <span className="text-foreground">{aoiAreaKm2} km²</span>
                        </div>
                      )}
                      {centreStr && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Centre</span>
                          <span className="text-foreground">{centreStr}</span>
                        </div>
                      )}
                      {activeCrs && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">CRS</span>
                          <span className="text-teal-400">{activeCrs}</span>
                        </div>
                      )}
                      {Boolean(activeScene?.native_resolution_m) && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Pixel size</span>
                          <span className="text-foreground">
                            {String(activeScene?.native_resolution_m)} m
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Acquisition Section */}
                  {activeScene && (
                    <div>
                      <div className="font-bold text-sky-400 text-[10.5px] uppercase tracking-wider mb-1.5">
                        Acquisition
                      </div>
                      <div className="flex flex-col gap-1 font-mono text-[10px]">
                        {activeScene.datetime && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Captured</span>
                            <span className="text-foreground">
                              {activeScene.datetime.slice(0, 10)}
                            </span>
                          </div>
                        )}
                        {activeScene.collection && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Platform</span>
                            <span className="text-foreground">{activeScene.collection}</span>
                          </div>
                        )}
                        {activeScene.cloud_cover != null && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Cloud cover</span>
                            <span className="text-foreground">{activeScene.cloud_cover}%</span>
                          </div>
                        )}
                        {activeScene.aoi_coverage_pct != null && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">AOI Coverage</span>
                            <span className="text-foreground">
                              {activeScene.aoi_coverage_pct}%
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="py-4 px-1 text-center text-muted-foreground text-[11px]">
                  No active selection. Draw a bounding box on the globe to inspect coordinates.
                </div>
              )}
            </div>
          )}

          {/* Layers & Visualization Overlays */}
          {activeLayers.length > 0 && (
            <div className="w-[250px] bg-card/95 backdrop-blur-md border border-border rounded-none p-2.5 shadow-2xl pointer-events-auto flex flex-col min-h-0">
              <div
                onClick={() => setOverlaysCollapsed((prev) => !prev)}
                className={`flex justify-between items-center cursor-pointer select-none ${
                  overlaysCollapsed ? '' : 'mb-2'
                }`}
              >
                <span className="inline-flex items-center gap-1.5 font-semibold text-[11.5px] text-foreground">
                  <Layers className="h-3.5 w-3.5 text-teal-400" />
                  Analysis Overlays
                </span>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-sky-400 bg-sky-400/15 px-1.5 py-0.5 rounded-none">
                    {activeLayers.length}
                  </span>
                  {overlaysCollapsed ? (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                  ) : (
                    <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                </div>
              </div>

              {!overlaysCollapsed && (
                <>
                  <div className="mb-2">
                    <label className="text-[10px] text-muted-foreground flex justify-between mb-1">
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
                      className="w-full accent-teal-500 cursor-pointer"
                    />
                  </div>

                  <div className="flex flex-col gap-1 max-h-[160px] overflow-y-auto">
                    {activeLayers.map((l) => (
                      <div
                        key={l.id}
                        className="flex items-center justify-between bg-muted px-2 py-1.5 rounded-none border border-border"
                      >
                        <span
                          title={l.title}
                          className="font-mono text-[10px] text-foreground truncate max-w-[175px]"
                        >
                          {l.title}
                        </span>
                        <button
                          type="button"
                          onClick={() => zoomToExtent(l.bbox)}
                          title="Zoom to raster bounds"
                          className="text-muted-foreground hover:text-sky-400 p-0.5 transition-colors"
                        >
                          <Search className="h-3 w-3" />
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
