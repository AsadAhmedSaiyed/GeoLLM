// GeoLLM GeoTIFF & Image Deliverable Inspector Modal
import { html, React } from '/static/js/html.js';
import { IconLayers, IconImage, IconX, IconDownload } from '/static/js/icons.js';
const { useEffect, useRef, useState } = React;

export function TiffPreviewModal({ previewTarget, onClose }) {
  const canvasRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [metadata, setMetadata] = useState(null);
  const [zoom, setZoom] = useState(1);

  const isTif = previewTarget && (previewTarget.type === 'tif' || previewTarget.name?.toLowerCase().endsWith('.tif') || previewTarget.name?.toLowerCase().endsWith('.tiff'));

  useEffect(() => {
    if (!previewTarget) return;

    setZoom(1);
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);

    if (isTif) {
      renderGeoTiff(previewTarget.url);
    } else {
      setLoading(false);
      setError(null);
      setMetadata(null);
    }

    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewTarget]);

  const renderGeoTiff = async (url) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const arrayBuffer = await response.arrayBuffer();

      if (typeof window.parseGeoraster !== 'function') {
        throw new Error('GeoRaster parser library is not loaded');
      }

      const georaster = await window.parseGeoraster(arrayBuffer);

      const minVal = georaster.mins && georaster.mins[0] != null ? georaster.mins[0] : 'N/A';
      const maxVal = georaster.maxs && georaster.maxs[0] != null ? georaster.maxs[0] : 'N/A';

      setMetadata({
        width: georaster.width,
        height: georaster.height,
        bands: georaster.numberOfRasters || 1,
        min: minVal,
        max: maxVal,
        projection: georaster.projection ? `EPSG:${georaster.projection}` : 'EPSG:32640 / UTM',
        nodata: georaster.noDataValue != null ? georaster.noDataValue : 'None'
      });

      const canvas = canvasRef.current;
      if (!canvas) return;

      canvas.width = georaster.width;
      canvas.height = georaster.height;
      const ctx = canvas.getContext('2d');
      const imgData = ctx.createImageData(canvas.width, canvas.height);

      const rasterData = georaster.values[0];
      const numericMin = typeof minVal === 'number' ? minVal : 0;
      const numericMax = typeof maxVal === 'number' ? maxVal : 1;
      const range = (numericMax - numericMin) || 1;

      for (let y = 0; y < canvas.height; y++) {
        for (let x = 0; x < canvas.width; x++) {
          const val = rasterData[y][x];
          const idx = (y * canvas.width + x) * 4;

          if (val === null || val === undefined || isNaN(val) || val === georaster.noDataValue) {
            imgData.data[idx] = 16;
            imgData.data[idx + 1] = 23;
            imgData.data[idx + 2] = 20;
            imgData.data[idx + 3] = 0; // Transparent
          } else {
            const norm = Math.max(0, Math.min(1, (val - numericMin) / range));
            // Viridis-inspired color ramp for clear scientific contrast
            imgData.data[idx] = Math.round(15 + norm * 200);
            imgData.data[idx + 1] = Math.round(118 + norm * 90);
            imgData.data[idx + 2] = Math.round(110 + (1 - norm) * 110);
            imgData.data[idx + 3] = 255;
          }
        }
      }

      ctx.putImageData(imgData, 0, 0);
      setLoading(false);
    } catch (err) {
      setError(`Failed to parse GeoTIFF raster: ${err.message}`);
      setLoading(false);
    }
  };

  const handleImageLoad = (e) => {
    const img = e.target;
    setMetadata({
      width: img.naturalWidth,
      height: img.naturalHeight,
      bands: 'RGB / RGBA',
      min: '0',
      max: '255',
      projection: 'Visual Map Render (Original Resolution)',
      nodata: 'N/A'
    });
  };

  if (!previewTarget) return null;

  return html`
    <div className="modal-backdrop" onClick=${onClose} role="dialog" aria-modal="true" aria-label="Deliverable Inspector">
      <div className="modal-content-card" onClick=${(e) => e.stopPropagation()}>
        <!-- Header -->
        <div className="modal-header">
          <div className="modal-title-group">
            <span className="modal-type-badge ${isTif ? 'tif' : 'img'}">
              ${isTif ? html`<${IconLayers} size=${13} />` : html`<${IconImage} size=${13} />`}
              ${isTif ? 'GeoTIFF' : 'PNG Map'}
            </span>
            <span className="modal-filename mono" title=${previewTarget.name}>
              ${previewTarget.name}
            </span>
          </div>

          <div className="modal-actions-toolbar">
            <div className="modal-zoom-controls">
              <button
                type="button"
                className="btn s"
                onClick=${() => setZoom(prev => Math.max(0.5, prev - 0.25))}
                title="Zoom out"
              >
                −
              </button>
              <button
                type="button"
                className="btn s"
                onClick=${() => setZoom(1)}
                title="Reset zoom (100%)"
                style=${{ minWidth: '44px' }}
              >
                ${Math.round(zoom * 100)}%
              </button>
              <button
                type="button"
                className="btn s"
                onClick=${() => setZoom(prev => Math.min(3, prev + 0.25))}
                title="Zoom in"
              >
                +
              </button>
            </div>

            <a
              href=${previewTarget.url}
              download=${previewTarget.name}
              className="btn s p"
              style=${{ height: '30px', padding: '0 12px', textDecoration: 'none' }}
              title="Download file"
            >
              <${IconDownload} size=${12} />
              <span>Download</span>
            </a>

            <button
              className="modal-close-icon-btn"
              onClick=${onClose}
              aria-label="Close dialog"
              type="button"
              title="Close (Esc)"
            >
              <${IconX} size=${16} />
            </button>
          </div>
        </div>

        <!-- Main Viewport -->
        <div className="modal-viewport">
          ${loading ? html`
            <div className="modal-status-box">
              <span className="spinner-icon-md"></span>
              <span>Parsing raster bands & spatial metadata...</span>
            </div>
          ` : null}

          ${error ? html`
            <div className="modal-status-box error">
              <span>${error}</span>
            </div>
          ` : null}

          <div
            className="modal-canvas-wrapper"
            style=${{
              transform: `scale(${zoom})`,
              transformOrigin: 'center center',
              transition: 'transform 0.15s ease'
            }}
          >
            ${isTif ? html`
              <canvas
                ref=${canvasRef}
                style=${{ display: loading || error ? 'none' : 'block' }}
                className="geotiff-canvas"
              />
            ` : html`
              <img
                src=${previewTarget.url}
                alt=${previewTarget.name}
                onLoad=${handleImageLoad}
                className="modal-preview-image"
                style=${{ display: loading || error ? 'none' : 'block' }}
              />
            `}
          </div>
        </div>

        <!-- Metadata Strip Footer -->
        <div className="modal-meta-strip">
          <div className="meta-cell">
            <span className="meta-lbl">Dimensions</span>
            <span className="meta-val mono">
              ${metadata ? `${metadata.width} × ${metadata.height} px` : 'Detecting...'}
            </span>
          </div>

          <div className="meta-cell">
            <span className="meta-lbl">Spatial Reference</span>
            <span className="meta-val mono" title=${metadata?.projection}>
              ${metadata ? metadata.projection : 'EPSG:32640 / UTM'}
            </span>
          </div>

          <div className="meta-cell">
            <span className="meta-lbl">Bands</span>
            <span className="meta-val mono">
              ${metadata ? metadata.bands : (isTif ? '1 band' : 'RGB')}
            </span>
          </div>

          <div className="meta-cell">
            <span className="meta-lbl">${isTif ? 'Dynamic Range' : 'Format'}</span>
            <span className="meta-val mono">
              ${metadata ? (isTif ? `${metadata.min} to ${metadata.max}` : '24-bit PNG') : 'N/A'}
            </span>
          </div>
        </div>
      </div>
    </div>
  `;
}
