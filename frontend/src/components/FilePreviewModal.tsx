import React, { useEffect, useState, useRef, useMemo } from 'react';
import { api } from '@/services/api';
import { FileInspectResponse, RasterStatsResponse } from '@/types/geospatial';
import {
  FileImage,
  Box,
  FileCode,
  X,
  Globe,
  Loader2,
  Palette,
} from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface FilePreviewTarget {
  name: string;
  url?: string;
  path: string;
}

export interface FilePreviewModalProps {
  target: FilePreviewTarget | null;
  onClose: () => void;
  onOverlayOnGlobe?: (target: { name: string; path: string; url: string }) => void;
}

// Memory cache to prevent re-fetching and blinking when re-opening or re-rendering
const FILE_META_CACHE: Record<string, FileInspectResponse> = {};
const RASTER_STATS_CACHE: Record<string, RasterStatsResponse> = {};

export const FilePreviewModal: React.FC<FilePreviewModalProps> = ({
  target,
  onClose,
  onOverlayOnGlobe,
}) => {
  const targetPath = target?.path || '';
  const [meta, setMeta] = useState<FileInspectResponse | null>(FILE_META_CACHE[targetPath] || null);
  const [rasterStats, setRasterStats] = useState<RasterStatsResponse | null>(RASTER_STATS_CACHE[targetPath] || null);
  const [loading, setLoading] = useState<boolean>(!FILE_META_CACHE[targetPath]);
  const [selectedCmap, setSelectedCmap] = useState<string>('viridis');
  const [displayPngUrl, setDisplayPngUrl] = useState<string>('');
  const [isImageLoading, setIsImageLoading] = useState<boolean>(false);
  const userChangedCmapRef = useRef<boolean>(false);

  // Fetch metadata only when targetPath changes
  useEffect(() => {
    if (!targetPath) return;

    let isMounted = true;
    userChangedCmapRef.current = false;

    // Use cached if available to prevent any blink
    if (FILE_META_CACHE[targetPath]) {
      setMeta(FILE_META_CACHE[targetPath]);
      setLoading(false);
      if (RASTER_STATS_CACHE[targetPath]) {
        setRasterStats(RASTER_STATS_CACHE[targetPath]);
        const s = RASTER_STATS_CACHE[targetPath];
        if (s.recommended_cmap) setSelectedCmap(s.recommended_cmap);
      }
      return;
    }

    setLoading(true);

    api.inspectFile(targetPath)
      .then((res) => {
        if (!isMounted) return;
        FILE_META_CACHE[targetPath] = res;
        setMeta(res);

        if (res.category === 'raster') {
          api.getRasterStats(targetPath).then((s) => {
            if (isMounted) {
              RASTER_STATS_CACHE[targetPath] = s;
              setRasterStats(s);
              if (s.recommended_cmap && !userChangedCmapRef.current) {
                setSelectedCmap(s.recommended_cmap);
              }
            }
          });
        }
      })
      .catch((err) => {
        console.error('Failed to inspect file:', err);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [targetPath]);

  const fileName = target?.name || targetPath.split(/[/\\\\]/).pop() || 'File Preview';
  const ext = fileName.split('.').pop()?.toLowerCase() || '';
  const isRaster = ['tif', 'tiff', 'img', 'jp2'].includes(ext);
  const isLidar = ['laz', 'las'].includes(ext);
  const isImage = ['png', 'jpg', 'jpeg', 'webp'].includes(ext);
  const isVector = ['geojson', 'json', 'shp'].includes(ext);

  const targetPngUrl = useMemo(() => {
    if (!targetPath) return '';
    if (isRaster) return api.getRasterPngUrl(targetPath, { cmap: selectedCmap });
    if (isImage) return `/api/raster/png?path=${encodeURIComponent(targetPath)}`;
    return '';
  }, [targetPath, isRaster, isImage, selectedCmap]);

  // Smooth image preload: keeps old image visible and swaps seamlessly without blinking
  useEffect(() => {
    if (!targetPngUrl) return;

    let isCancelled = false;
    setIsImageLoading(true);

    const img = new Image();
    img.src = targetPngUrl;
    img.onload = () => {
      if (!isCancelled) {
        setDisplayPngUrl(targetPngUrl);
        setIsImageLoading(false);
      }
    };
    img.onerror = () => {
      if (!isCancelled) {
        setDisplayPngUrl(targetPngUrl);
        setIsImageLoading(false);
      }
    };

    return () => {
      isCancelled = true;
    };
  }, [targetPngUrl]);

  if (!target) return null;

  const handleCmapSelect = (newCmap: string) => {
    userChangedCmapRef.current = true;
    setSelectedCmap(newCmap);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-card border border-border shadow-2xl rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-hidden flex flex-col text-xs text-foreground animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between bg-muted/20">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            {isRaster && <FileImage className="h-4 w-4 text-teal-400 shrink-0" />}
            {isLidar && <Box className="h-4 w-4 text-purple-400 shrink-0" />}
            {isVector && <FileCode className="h-4 w-4 text-teal-400 shrink-0" />}
            {isImage && <FileImage className="h-4 w-4 text-emerald-400 shrink-0" />}
            <span className="font-semibold text-sm truncate font-mono text-foreground" title={fileName}>
              {fileName}
            </span>
            {meta?.size_mb !== undefined && (
              <span className="text-[10.5px] font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded-full shrink-0">
                {meta.size_mb} MB
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-4 overflow-y-auto space-y-4 flex-1">
          {loading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-2 text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin text-teal-400" />
              <span className="text-xs">Analyzing file metadata and structure...</span>
            </div>
          ) : (
            <>
              {/* Raster Preview Canvas & Colormap Toolbar */}
              {isRaster && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
                      Dynamic Raster Preview
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                        <Palette className="h-3 w-3 text-teal-400" /> Palette:
                      </span>
                      <select
                        value={selectedCmap}
                        onChange={(e) => handleCmapSelect(e.target.value)}
                        className="bg-muted border border-border rounded px-2 py-0.5 text-[11px] text-foreground focus:outline-none cursor-pointer"
                      >
                        <option value="viridis">Viridis (Default)</option>
                        <option value="terrain">Terrain (Elevation)</option>
                        <option value="Greens">Greens (Vegetation)</option>
                        <option value="Blues">Blues (Water / Flow)</option>
                        <option value="plasma">Plasma</option>
                        <option value="inferno">Inferno</option>
                        <option value="Spectral">Spectral</option>
                        <option value="grayscale">Grayscale</option>
                      </select>
                    </div>
                  </div>

                  <div className="h-64 w-full bg-black/40 rounded-xl overflow-hidden flex items-center justify-center border border-border relative">
                    {displayPngUrl ? (
                      <img
                        src={displayPngUrl}
                        alt={fileName}
                        className={`max-h-full max-w-full object-contain transition-opacity duration-150 ${
                          isImageLoading ? 'opacity-80' : 'opacity-100'
                        }`}
                      />
                    ) : (
                      <Loader2 className="h-5 w-5 animate-spin text-teal-400" />
                    )}
                    {isImageLoading && displayPngUrl && (
                      <div className="absolute top-2 right-2 bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded text-[10px] text-teal-300 flex items-center gap-1 font-mono">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        <span>Rendering palette...</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Standard Image Preview */}
              {isImage && (
                <div className="h-64 w-full bg-black/30 rounded-xl overflow-hidden flex items-center justify-center border border-border">
                  <img
                    src={`/api/raster/png?path=${encodeURIComponent(targetPath)}`}
                    alt={fileName}
                    className="max-h-full max-w-full object-contain"
                  />
                </div>
              )}

              {/* Point Cloud Metadata Card */}
              {isLidar && (
                <div className="bg-purple-500/10 border border-purple-500/30 rounded-xl p-4 space-y-2.5">
                  <div className="flex items-center gap-2 text-purple-300 font-semibold text-xs">
                    <Box className="h-4 w-4" />
                    <span>LiDAR / Point Cloud Characteristics</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11.5px] font-mono">
                    <div className="bg-background/60 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">Total Point Count</span>
                      <span className="font-bold text-foreground text-sm">
                        {meta?.point_count?.toLocaleString() || '—'}
                      </span>
                    </div>
                    <div className="bg-background/60 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">LAS Format Version</span>
                      <span className="font-bold text-foreground">{meta?.version || '1.4'}</span>
                    </div>
                  </div>
                  {meta?.crs && (
                    <div className="text-[10.5px] bg-background/40 p-2 rounded-lg border border-border/40 font-mono text-muted-foreground truncate">
                      <span className="text-foreground font-semibold">CRS: </span>
                      {meta.crs}
                    </div>
                  )}
                </div>
              )}

              {/* Vector Metadata Card */}
              {isVector && (
                <div className="bg-teal-500/10 border border-teal-500/30 rounded-xl p-4 space-y-2.5">
                  <div className="flex items-center gap-2 text-teal-300 font-semibold text-xs">
                    <FileCode className="h-4 w-4" />
                    <span>Vector Dataset Characteristics</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11.5px] font-mono">
                    <div className="bg-background/60 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">Feature Count</span>
                      <span className="font-bold text-foreground text-sm">
                        {meta?.feature_count?.toLocaleString() || '—'}
                      </span>
                    </div>
                    <div className="bg-background/60 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">Geometry Types</span>
                      <span className="font-bold text-foreground truncate">
                        {meta?.geometry_types?.join(', ') || 'Mixed'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Geospatial Properties & Coordinates */}
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
                  Dataset Specifications
                </span>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-[11px]">
                  {meta?.crs && (
                    <div className="bg-muted/40 p-2 rounded-lg border border-border/50 col-span-2 sm:col-span-3 truncate">
                      <span className="text-muted-foreground block text-[10px]">Coordinate System (CRS)</span>
                      <span className="text-foreground font-semibold">{meta.crs}</span>
                    </div>
                  )}
                  {meta?.width && meta?.height && (
                    <div className="bg-muted/40 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">Dimensions (W × H)</span>
                      <span className="text-foreground">{meta.width} × {meta.height} px</span>
                    </div>
                  )}
                  {meta?.count && (
                    <div className="bg-muted/40 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">Band Count</span>
                      <span className="text-foreground">{meta.count} band(s)</span>
                    </div>
                  )}
                  {rasterStats?.units && (
                    <div className="bg-muted/40 p-2 rounded-lg border border-border/50">
                      <span className="text-muted-foreground block text-[10px]">Physical Units</span>
                      <span className="text-teal-400 font-bold">{rasterStats.units}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Quantitative Value Distribution (if raster) */}
              {rasterStats?.stats && (
                <div className="bg-background/60 border border-border rounded-xl p-3 space-y-1.5">
                  <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
                    Computed Value Distribution
                  </div>
                  <div className="grid grid-cols-4 gap-1.5 font-mono text-[11px]">
                    <div className="bg-muted/30 p-1.5 rounded">
                      <span className="text-[10px] text-muted-foreground block">Min</span>
                      <span className="font-semibold text-foreground">{rasterStats.stats.min.toFixed(2)}</span>
                    </div>
                    <div className="bg-muted/30 p-1.5 rounded">
                      <span className="text-[10px] text-muted-foreground block">Median</span>
                      <span className="font-semibold text-foreground">{rasterStats.stats.median.toFixed(2)}</span>
                    </div>
                    <div className="bg-muted/30 p-1.5 rounded">
                      <span className="text-[10px] text-muted-foreground block">Mean</span>
                      <span className="font-semibold text-foreground">{rasterStats.stats.mean.toFixed(2)}</span>
                    </div>
                    <div className="bg-muted/30 p-1.5 rounded">
                      <span className="text-[10px] text-muted-foreground block">Max</span>
                      <span className="font-semibold text-foreground">{rasterStats.stats.max.toFixed(2)}</span>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-3 border-t border-border bg-muted/20 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={onClose}
            className="text-xs h-8 px-3"
          >
            Close
          </Button>

          <div className="flex items-center gap-2">
            {isRaster && onOverlayOnGlobe && (
              <Button
                onClick={() => {
                  onOverlayOnGlobe({
                    name: fileName,
                    path: targetPath,
                    url: api.getRasterPngUrl(targetPath, { cmap: selectedCmap }),
                  });
                  onClose();
                }}
                className="text-xs h-8 px-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold flex items-center gap-1.5 cursor-pointer"
              >
                <Globe className="h-3.5 w-3.5" />
                <span>Project on 3D Globe</span>
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
