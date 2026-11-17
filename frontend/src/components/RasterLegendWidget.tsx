import React, { useEffect, useState, useMemo } from 'react';
import { api } from '@/services/api';
import { RasterStatsResponse, RasterPixelResponse } from '@/types/geospatial';
import {
  Crosshair,
  Sliders,
  ChevronDown,
  ChevronUp,
  X,
  Loader2,
  Layers,
} from 'lucide-react';

export interface RasterLegendWidgetProps {
  rasterPath: string;
  activeCmap?: string;
  onColormapChange?: (cmap: string) => void;
  onStretchChange?: (vmin: number, vmax: number) => void;
  hoverPixel?: RasterPixelResponse | null;
  isInspectMode?: boolean;
  onToggleInspectMode?: () => void;
  onClose?: () => void;
  embedded?: boolean;
}

const COLORMAP_OPTIONS = [
  { id: 'viridis', label: 'Viridis (Default)', gradient: 'from-[#440154] via-[#21918c] to-[#fde725]' },
  { id: 'plasma', label: 'Plasma', gradient: 'from-[#0d0887] via-[#cc4778] to-[#f0f921]' },
  { id: 'terrain', label: 'Terrain (Elevation)', gradient: 'from-[#336633] via-[#ffff99] to-[#ffffff]' },
  { id: 'Greens', label: 'Greens (Vegetation)', gradient: 'from-[#e5f5e0] via-[#74c476] to-[#00441b]' },
  { id: 'Blues', label: 'Blues (Water / Flow)', gradient: 'from-[#eff3ff] via-[#6baed6] to-[#08519c]' },
  { id: 'inferno', label: 'Inferno (Heat / Thermal)', gradient: 'from-[#000004] via-[#bb3754] to-[#fcffa4]' },
  { id: 'Spectral', label: 'Spectral (Diverging)', gradient: 'from-[#d7191c] via-[#ffffbf] to-[#2b83ba]' },
  { id: 'grayscale', label: 'Grayscale (Raw)', gradient: 'from-black to-white' },
];

const RASTER_LEGEND_CACHE: Record<string, RasterStatsResponse> = {};

export const RasterLegendWidget: React.FC<RasterLegendWidgetProps> = ({
  rasterPath,
  activeCmap = 'viridis',
  onColormapChange,
  onStretchChange,
  hoverPixel,
  isInspectMode,
  onToggleInspectMode,
  onClose,
  embedded = false,
}) => {
  const [statsData, setStatsData] = useState<RasterStatsResponse | null>(RASTER_LEGEND_CACHE[rasterPath] || null);
  const [loading, setLoading] = useState<boolean>(!RASTER_LEGEND_CACHE[rasterPath]);
  const [showControls, setShowControls] = useState<boolean>(true);
  const [currentCmap, setCurrentCmap] = useState<string>(activeCmap);

  // Sync external colormap changes
  useEffect(() => {
    if (activeCmap && activeCmap !== currentCmap) {
      setCurrentCmap(activeCmap);
    }
  }, [activeCmap]);

  // Stretch sliders
  const [minVal, setMinVal] = useState<number>(() => RASTER_LEGEND_CACHE[rasterPath]?.stats?.p02 ?? 0);
  const [maxVal, setMaxVal] = useState<number>(() => RASTER_LEGEND_CACHE[rasterPath]?.stats?.p98 ?? 1);

  useEffect(() => {
    if (!rasterPath) return;

    if (RASTER_LEGEND_CACHE[rasterPath]) {
      const cached = RASTER_LEGEND_CACHE[rasterPath];
      setStatsData(cached);
      setLoading(false);
      if (cached.stats) {
        setMinVal(cached.stats.p02 ?? cached.stats.min ?? 0);
        setMaxVal(cached.stats.p98 ?? cached.stats.max ?? 1);
      }
      return;
    }

    let isMounted = true;
    setLoading(true);

    api.getRasterStats(rasterPath)
      .then((res) => {
        if (!isMounted) return;
        RASTER_LEGEND_CACHE[rasterPath] = res;
        setStatsData(res);
        if (res.stats) {
          setMinVal(res.stats.p02 ?? res.stats.min ?? 0);
          setMaxVal(res.stats.p98 ?? res.stats.max ?? 1);
        }
      })
      .catch((err) => {
        console.warn('Failed to load raster stats:', err);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [rasterPath]);

  const handleCmapSelect = (cmapId: string) => {
    setCurrentCmap(cmapId);
    onColormapChange?.(cmapId);
  };

  const handleMinChange = (v: number) => {
    setMinVal(v);
    if (v < maxVal) {
      onStretchChange?.(v, maxVal);
    }
  };

  const handleMaxChange = (v: number) => {
    setMaxVal(v);
    if (v > minVal) {
      onStretchChange?.(minVal, v);
    }
  };

  const formatNumber = (num?: number | null): string => {
    if (num === undefined || num === null || isNaN(num)) return '—';
    if (Math.abs(num) >= 1000) return num.toLocaleString(undefined, { maximumFractionDigits: 1 });
    if (Math.abs(num) >= 10) return num.toFixed(1);
    if (Math.abs(num) >= 0.01) return num.toFixed(2);
    if (num === 0) return '0';
    return num.toExponential(2);
  };

  const currentGradient = useMemo(() => {
    const found = COLORMAP_OPTIONS.find((c) => c.id.toLowerCase() === currentCmap.toLowerCase());
    return found ? found.gradient : 'from-[#440154] via-[#21918c] to-[#fde725]';
  }, [currentCmap]);

  const displayName = statsData?.file_name || rasterPath.split(/[/\\\\]/).pop() || 'Raster Layer';
  const displayUnit = statsData?.units || '';

  const content = (
    <div className="space-y-2 text-foreground">
      {loading ? (
        <div className="py-2.5 flex items-center justify-center gap-2 text-muted-foreground text-[10px]">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-400" />
          <span>Loading dynamic legend...</span>
        </div>
      ) : (
        <>
          {/* Container Artifact Description / Detail */}
          {(statsData?.artifact_description || statsData?.band_description) && (
            <div className="text-[10px] text-muted-foreground leading-tight bg-muted/60 p-1.5 rounded border border-border/50">
              <span className="font-semibold text-foreground">Detail: </span>
              {statsData.artifact_description || statsData.band_description}
            </div>
          )}

          {/* Categorical vs Continuous Legend */}
          {statsData?.is_classified && statsData.classes && statsData.classes.length > 0 ? (
            <div className="space-y-1">
              <div className="text-[9.5px] uppercase font-bold tracking-wider text-muted-foreground flex justify-between items-center">
                <span>Class Categories</span>
                {displayUnit && (
                  <span className="font-mono bg-teal-500/15 text-teal-400 px-1 py-0.2 rounded text-[9px]">
                    {displayUnit}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-1 gap-1 max-h-24 overflow-y-auto pr-0.5">
                {statsData.classes.map((cls) => (
                  <div
                    key={cls.value}
                    className="flex items-center justify-between gap-1.5 px-1.5 py-0.5 rounded bg-muted/40 border border-border/40 text-[10px]"
                  >
                    <div className="flex items-center gap-1.5 truncate">
                      <span
                        className="w-2.5 h-2.5 rounded-sm shrink-0 border border-black/30"
                        style={{ backgroundColor: cls.color }}
                      />
                      <span className="truncate text-foreground font-medium">{cls.label}</span>
                    </div>
                    <span className="font-mono text-[9px] text-muted-foreground shrink-0">
                      [{cls.value}]
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-[9.5px] text-muted-foreground">
                <span className="uppercase font-bold tracking-wider">Dynamic Colormap</span>
                {displayUnit && (
                  <span className="font-mono bg-teal-500/15 text-teal-400 px-1.5 py-0.2 rounded border border-teal-500/20 text-[9.5px]">
                    {displayUnit}
                  </span>
                )}
              </div>

              {/* Gradient Ramp */}
              <div
                className={`h-3.5 w-full rounded bg-gradient-to-r ${currentGradient} shadow-inner border border-black/40`}
              />

              {/* Range Ticks (Min, Median, Max) */}
              <div className="flex justify-between items-center text-[10px] font-mono text-muted-foreground px-0.5">
                <span className="text-foreground font-semibold" title="Min / 2nd percentile">
                  {formatNumber(minVal)}
                </span>
                {statsData?.stats?.median !== undefined && (
                  <span className="text-muted-foreground text-[9px]" title="Median value">
                    med: {formatNumber(statsData.stats.median)}
                  </span>
                )}
                <span className="text-foreground font-semibold" title="Max / 98th percentile">
                  {formatNumber(maxVal)}
                </span>
              </div>
            </div>
          )}

          {/* Point Inspector Toggle & Active HUD */}
          <div className="pt-1 border-t border-border/50 flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground font-medium">Value Probe</span>
              {onToggleInspectMode && (
                <button
                  type="button"
                  onClick={onToggleInspectMode}
                  title={isInspectMode ? 'Inspection active: move cursor on globe to probe values' : 'Enable Value Inspector'}
                  className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold transition-colors cursor-pointer ${
                    isInspectMode
                      ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40'
                      : 'bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80 border border-border'
                  }`}
                >
                  <Crosshair className="h-3 w-3" />
                  <span>{isInspectMode ? 'Inspecting...' : 'Probe'}</span>
                </button>
              )}
            </div>

            {isInspectMode && (
              <div className="bg-teal-500/10 border border-teal-500/30 rounded p-1.5 text-[10.5px]">
                {hoverPixel ? (
                  hoverPixel.inside ? (
                    <div className="font-mono space-y-0.5">
                      <div className="text-[11px] font-bold text-teal-300">
                        {hoverPixel.is_nodata || hoverPixel.value === null || hoverPixel.value === undefined
                          ? 'NoData / Masked'
                          : `${formatNumber(hoverPixel.value)} ${hoverPixel.units || displayUnit}`}
                      </div>
                      <div className="text-[9px] text-muted-foreground">
                        Pixel: [r: {hoverPixel.row}, c: {hoverPixel.col}]
                      </div>
                    </div>
                  ) : (
                    <div className="text-muted-foreground text-[9.5px]">
                      Cursor outside raster bounds
                    </div>
                  )
                ) : (
                  <div className="text-muted-foreground text-[9.5px]">
                    Move cursor over overlay to probe value
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Colormap & Stretch Controls */}
          <div className="pt-1 border-t border-border/50">
            <button
              type="button"
              onClick={() => setShowControls((p) => !p)}
              className="flex items-center justify-between w-full text-muted-foreground hover:text-foreground text-[10px] font-medium py-0.5 transition-colors cursor-pointer"
            >
              <span className="flex items-center gap-1">
                <Sliders className="h-3 w-3 text-teal-400" />
                <span>Colormap & Contrast Stretch</span>
              </span>
              {showControls ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>

            {showControls && (
              <div className="mt-1.5 space-y-2 bg-muted/30 p-2 rounded border border-border/40">
                {/* Palette Selector */}
                <div>
                  <label className="text-[9.5px] text-muted-foreground block mb-0.5">Color Palette</label>
                  <select
                    value={currentCmap}
                    onChange={(e) => handleCmapSelect(e.target.value)}
                    className="w-full bg-background border border-border rounded px-1.5 py-0.5 text-[10.5px] text-foreground focus:outline-none cursor-pointer"
                  >
                    {COLORMAP_OPTIONS.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Min Slider */}
                {statsData?.stats && (
                  <div className="space-y-0.5">
                    <div className="flex justify-between text-[9px] text-muted-foreground font-mono">
                      <span>Min Threshold</span>
                      <span className="text-foreground">{formatNumber(minVal)}</span>
                    </div>
                    <input
                      type="range"
                      min={statsData.stats.min}
                      max={statsData.stats.max}
                      step={(statsData.stats.max - statsData.stats.min) / 100 || 0.1}
                      value={minVal}
                      onChange={(e) => handleMinChange(parseFloat(e.target.value))}
                      className="w-full accent-teal-500 cursor-pointer h-1 bg-border rounded"
                    />
                  </div>
                )}

                {/* Max Slider */}
                {statsData?.stats && (
                  <div className="space-y-0.5">
                    <div className="flex justify-between text-[9px] text-muted-foreground font-mono">
                      <span>Max Threshold</span>
                      <span className="text-foreground">{formatNumber(maxVal)}</span>
                    </div>
                    <input
                      type="range"
                      min={statsData.stats.min}
                      max={statsData.stats.max}
                      step={(statsData.stats.max - statsData.stats.min) / 100 || 0.1}
                      value={maxVal}
                      onChange={(e) => handleMaxChange(parseFloat(e.target.value))}
                      className="w-full accent-teal-500 cursor-pointer h-1 bg-border rounded"
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );

  // If embedded directly inside the Analysis Overlays list under the selected file
  if (embedded) {
    return (
      <div className="w-full pt-1 pb-1">
        {content}
      </div>
    );
  }

  // Standalone floating fallback
  return (
    <div className="bg-card/95 backdrop-blur-md border border-border rounded-lg p-2.5 shadow-2xl w-72 text-foreground text-xs select-none">
      <div className="pb-1.5 mb-2 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <Layers className="h-3.5 w-3.5 text-teal-400 shrink-0" />
          <span className="font-semibold text-[11px] truncate text-foreground" title={displayName}>
            {displayName}
          </span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-0.5 rounded text-muted-foreground hover:text-rose-400 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {content}
    </div>
  );
};
