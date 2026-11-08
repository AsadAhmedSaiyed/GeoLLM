import React, { useEffect, useRef, useState } from 'react';
import { api } from '@/services/api';
import { Layers, Image as ImageIcon, X, Download, ZoomIn, ZoomOut, Loader2, Globe } from 'lucide-react';

export interface PreviewTarget {
  name: string;
  url: string;
  path?: string;
  type?: 'tif' | 'img' | 'doc';
}

export interface TiffPreviewModalProps {
  previewTarget: PreviewTarget | null;
  onClose: () => void;
  onOverlayOnGlobe?: (target: PreviewTarget) => void;
}

interface RasterMeta {
  width: number | string;
  height: number | string;
  bands: number | string;
  bbox?: [number, number, number, number];
  projection: string;
  format: string;
}

type ColormapId = 'default' | 'viridis' | 'ndvi' | 'terrain' | 'inferno' | 'grayscale';

function sampleColormap(cmap: ColormapId, t: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, t));
  if (cmap === 'grayscale') {
    const v = Math.round(x * 255);
    return [v, v, v];
  }
  if (cmap === 'ndvi') {
    // Brown -> Yellow -> Deep Green
    if (x < 0.5) {
      const u = x * 2;
      return [
        Math.round(165 + u * 80),
        Math.round(80 + u * 155),
        Math.round(42 + u * 50),
      ];
    }
    const u = (x - 0.5) * 2;
    return [
      Math.round(245 - u * 230),
      Math.round(235 - u * 115),
      Math.round(92 - u * 50),
    ];
  }
  if (cmap === 'terrain') {
    if (x < 0.35) {
      const u = x / 0.35;
      return [Math.round(30 + u * 90), Math.round(110 + u * 85), Math.round(60 + u * 30)];
    }
    if (x < 0.75) {
      const u = (x - 0.35) / 0.4;
      return [Math.round(120 + u * 95), Math.round(195 - u * 45), Math.round(90 - u * 30)];
    }
    const u = (x - 0.75) / 0.25;
    return [Math.round(215 + u * 35), Math.round(150 + u * 100), Math.round(60 + u * 190)];
  }
  if (cmap === 'inferno') {
    return [
      Math.round(Math.min(255, x * 320)),
      Math.round(Math.pow(x, 1.8) * 230),
      Math.round(Math.sin(x * Math.PI) * 140 + x * 60),
    ];
  }
  // viridis
  return [
    Math.round(68 + x * 185 * x),
    Math.round(1 + x * 225),
    Math.round(84 + Math.sin(x * Math.PI) * 90 - x * 45),
  ];
}

export const TiffPreviewModal: React.FC<TiffPreviewModalProps> = ({
  previewTarget,
  onClose,
  onOverlayOnGlobe,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sourceImageRef = useRef<HTMLImageElement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<RasterMeta | null>(null);
  const [zoom, setZoom] = useState(1);
  const [colormap, setColormap] = useState<ColormapId>('default');

  const isTif = Boolean(
    previewTarget &&
      (previewTarget.type === 'tif' ||
        previewTarget.name?.toLowerCase().endsWith('.tif') ||
        previewTarget.name?.toLowerCase().endsWith('.tiff') ||
        previewTarget.path?.toLowerCase().endsWith('.tif') ||
        previewTarget.path?.toLowerCase().endsWith('.tiff'))
  );

  const isImage = Boolean(
    previewTarget &&
      !isTif &&
      /\.(png|jpg|jpeg|gif|webp|svg)(\?.*)?$/i.test(previewTarget.name || previewTarget.url)
  );

  useEffect(() => {
    if (!previewTarget) return;

    setZoom(1);
    setColormap('default');
    setError(null);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);

    if (isTif) {
      const targetPath = previewTarget.path || previewTarget.url;
      loadGeoTiffViaBackend(targetPath);
    } else {
      setLoading(false);
      setMetadata(null);
    }

    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewTarget, isTif, onClose]);

  const drawCanvasWithColormap = (img: HTMLImageElement, cmap: ColormapId) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = img.naturalWidth || img.width;
    canvas.height = img.naturalHeight || img.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);

    if (cmap === 'default') return;

    const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imgData.data;
    for (let i = 0; i < data.length; i += 4) {
      const alpha = data[i + 3];
      if (alpha === 0) continue;
      // Compute luminance from rendered raster pixel
      const lum = (0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]) / 255;
      const [r, g, b] = sampleColormap(cmap, lum);
      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
    }
    ctx.putImageData(imgData, 0, 0);
  };

  useEffect(() => {
    if (isTif && sourceImageRef.current) {
      drawCanvasWithColormap(sourceImageRef.current, colormap);
    }
  }, [colormap, isTif]);

  const loadGeoTiffViaBackend = async (rawPath: string) => {
    setLoading(true);
    setError(null);
    try {
      const boundsRes = await api.getRasterBounds(rawPath);
      if (!boundsRes.ok) {
        throw new Error(boundsRes.error || 'Could not inspect GeoTIFF bounds');
      }

      setMetadata({
        width: boundsRes.width ?? 'N/A',
        height: boundsRes.height ?? 'N/A',
        bands: boundsRes.count ?? 1,
        bbox: boundsRes.bbox,
        projection: boundsRes.crs || 'EPSG:4326',
        format: 'GeoTIFF (2–98% Stretch)',
      });

      const pngUrl = boundsRes.png_url || api.getRasterPngUrl(rawPath);
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        sourceImageRef.current = img;
        drawCanvasWithColormap(img, 'default');
        setLoading(false);
      };
      img.onerror = () => {
        setError('Failed to render GeoTIFF preview image from backend');
        setLoading(false);
      };
      img.src = pngUrl;
    } catch (err) {
      setError(`Failed to inspect GeoTIFF raster: ${err instanceof Error ? err.message : String(err)}`);
      setLoading(false);
    }
  };

  const handleImageLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    setMetadata({
      width: img.naturalWidth,
      height: img.naturalHeight,
      bands: 'RGB / RGBA',
      projection: 'Visual Map Render (Original Resolution)',
      format: '24-bit PNG',
    });
  };

  if (!previewTarget) return null;

  return (
    <div
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Deliverable Inspector"
      className="fixed inset-0 z-[1200] bg-black/85 backdrop-blur-md flex items-center justify-center p-6"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-5xl max-h-[90vh] bg-[#0B0F17] border border-[#1E293B] rounded-xl shadow-2xl flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-[#0F172A] border-b border-[#1E293B] gap-4 flex-wrap">
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider ${
                isTif
                  ? 'bg-teal-500/15 text-teal-400 border border-teal-500/30'
                  : 'bg-sky-500/15 text-sky-400 border border-sky-500/30'
              }`}
            >
              {isTif ? <Layers className="h-3.5 w-3.5" /> : <ImageIcon className="h-3.5 w-3.5" />}
              {isTif ? 'GeoTIFF Inspector' : 'Deliverable Preview'}
            </span>
            <span
              className="font-mono text-xs font-semibold text-slate-100 truncate"
              title={previewTarget.name}
            >
              {previewTarget.name}
            </span>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Colormap Selector for GeoTIFFs */}
            {isTif && (
              <div className="flex items-center gap-1.5 mr-1">
                <span className="text-[11px] text-slate-400">LUT:</span>
                <select
                  value={colormap}
                  onChange={(e) => setColormap(e.target.value as ColormapId)}
                  className="bg-[#070A0F] border border-[#1E293B] rounded px-2 py-1 text-[11px] text-slate-200 outline-none cursor-pointer"
                >
                  <option value="default">Native / Viridis</option>
                  <option value="ndvi">NDVI (Brown–Green)</option>
                  <option value="terrain">Terrain Hypsometric</option>
                  <option value="inferno">Thermal Inferno</option>
                  <option value="grayscale">Panchromatic Gray</option>
                </select>
              </div>
            )}

            {/* Zoom Controls */}
            <div className="flex items-center bg-[#070A0F] border border-[#1E293B] rounded-md p-0.5">
              <button
                type="button"
                onClick={() => setZoom((prev) => Math.max(0.5, prev - 0.25))}
                title="Zoom out"
                className="px-2 py-1 text-xs text-slate-300 hover:text-white"
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setZoom(1)}
                title="Reset zoom (100%)"
                className="px-2 py-0.5 text-[11px] font-mono text-slate-300 hover:text-white min-w-[46px]"
              >
                {Math.round(zoom * 100)}%
              </button>
              <button
                type="button"
                onClick={() => setZoom((prev) => Math.min(3, prev + 0.25))}
                title="Zoom in"
                className="px-2 py-1 text-xs text-slate-300 hover:text-white"
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Overlay on 3D Globe Button for GeoTIFFs */}
            {isTif && onOverlayOnGlobe && (
              <button
                type="button"
                onClick={() => {
                  onOverlayOnGlobe(previewTarget);
                  onClose();
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold transition-colors"
                title="Project this georeferenced raster onto the 3D Globe"
              >
                <Globe className="h-3.5 w-3.5" />
                <span>Overlay on 3D Globe</span>
              </button>
            )}

            <a
              href={previewTarget.url}
              download={previewTarget.name}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#0F766E] hover:bg-[#0D9488] text-white text-xs font-semibold transition-colors"
              title="Download file"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Download</span>
            </a>

            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              title="Close (Esc)"
              className="p-1.5 rounded-md bg-slate-800/80 border border-[#1E293B] text-slate-400 hover:text-white transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Main Viewport */}
        <div className="flex-1 min-h-[380px] max-h-[70vh] overflow-auto bg-[#070A0F] flex items-center justify-center p-6 relative">
          {loading && (
            <div className="flex flex-col items-center gap-2.5 text-sky-400 font-mono text-xs">
              <Loader2 className="h-6 w-6 animate-spin" />
              <span>Parsing raster bands & spatial metadata...</span>
            </div>
          )}

          {error && (
            <div className="bg-rose-950/30 border border-rose-500/40 text-rose-300 px-4 py-3 rounded-lg text-xs font-mono">
              {error}
            </div>
          )}

          <div
            style={{
              transform: `scale(${zoom})`,
              transformOrigin: 'center center',
              transition: 'transform 0.15s ease',
            }}
            className="flex items-center justify-center"
          >
            {isTif ? (
              <canvas
                ref={canvasRef}
                style={{ display: loading || error ? 'none' : 'block' }}
                className="max-w-full max-h-[62vh] object-contain rounded shadow-lg border border-[#1E293B]"
              />
            ) : isImage ? (
              <img
                src={previewTarget.url}
                alt={previewTarget.name}
                onLoad={handleImageLoad}
                style={{ display: loading || error ? 'none' : 'block' }}
                className="max-w-full max-h-[62vh] object-contain rounded shadow-lg"
              />
            ) : (
              <iframe
                src={previewTarget.url}
                title={previewTarget.name}
                className="w-[75vw] h-[60vh] border border-[#1E293B] rounded-lg bg-[#070A0F] text-slate-100"
              />
            )}
          </div>
        </div>

        {/* Metadata Strip Footer */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-4 py-2.5 bg-[#0F172A] border-t border-[#1E293B] text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              Dimensions
            </div>
            <div className="font-mono text-slate-200 text-[11px]">
              {metadata ? `${metadata.width} × ${metadata.height} px` : 'Detecting...'}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              Spatial Reference
            </div>
            <div
              className="font-mono text-teal-400 text-[11px] truncate"
              title={metadata?.projection}
            >
              {metadata ? metadata.projection : isTif ? 'Detecting CRS...' : 'Visual Map Render'}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              Bands
            </div>
            <div className="font-mono text-slate-200 text-[11px]">
              {metadata ? metadata.bands : isTif ? '1 band' : 'RGB'}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {metadata?.bbox ? 'WGS84 BBOX' : 'Rendering'}
            </div>
            <div className="font-mono text-slate-200 text-[11px] truncate">
              {metadata?.bbox
                ? `${metadata.bbox[0].toFixed(3)}, ${metadata.bbox[1].toFixed(3)} → ${metadata.bbox[2].toFixed(3)}, ${metadata.bbox[3].toFixed(3)}`
                : metadata?.format || 'Standard'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

