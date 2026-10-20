// Astryx GeoTIFF & Image Standalone Preview Modal (Deep Dark Theme)
import { html, React } from '/static/js/html.js';
import { IconLayers, IconImage, IconX, IconDownload } from '/static/js/icons.js';
const { useEffect, useRef, useState } = React;

export function TiffPreviewModal({ previewTarget, onClose }) {
  const canvasRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [metadata, setMetadata] = useState(null);

  useEffect(() => {
    if (!previewTarget) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);

    if (previewTarget.type === 'tif') {
      renderGeoTiff(previewTarget.url);
    } else {
      setLoading(false);
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

      setMetadata({
        width: georaster.width,
        height: georaster.height,
        bands: georaster.numberOfRasters,
        min: georaster.mins ? georaster.mins[0] : 'N/A',
        max: georaster.maxs ? georaster.maxs[0] : 'N/A',
        projection: georaster.projection || 'EPSG:32640 / UTM'
      });

      const canvas = canvasRef.current;
      if (!canvas) return;

      canvas.width = georaster.width;
      canvas.height = georaster.height;
      const ctx = canvas.getContext('2d');
      const imgData = ctx.createImageData(canvas.width, canvas.height);

      const rasterData = georaster.values[0];
      const minVal = georaster.mins ? georaster.mins[0] : 0;
      const maxVal = georaster.maxs ? georaster.maxs[0] : 1;
      const range = (maxVal - minVal) || 1;

      for (let y = 0; y < canvas.height; y++) {
        for (let x = 0; x < canvas.width; x++) {
          const val = rasterData[y][x];
          const idx = (y * canvas.width + x) * 4;

          if (val === null || val === undefined || isNaN(val) || val === georaster.noDataValue) {
            imgData.data[idx] = 11;
            imgData.data[idx + 1] = 15;
            imgData.data[idx + 2] = 25;
            imgData.data[idx + 3] = 0;
          } else {
            const norm = Math.max(0, Math.min(1, (val - minVal) / range));
            // Technical viridis-inspired telemetry palette
            imgData.data[idx] = Math.round(56 + norm * 199);
            imgData.data[idx + 1] = Math.round(189 + norm * (240 - 189));
            imgData.data[idx + 2] = Math.round(248 - norm * 100);
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

  if (!previewTarget) return null;

  return html`
    <div className="modal-backdrop" onClick=${onClose} role="dialog" aria-modal="true">
      <div className="modal-content-card" onClick=${(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <div className="modal-icon-badge">
              ${previewTarget.type === 'tif' ? html`<${IconLayers} size=${16} />` : html`<${IconImage} size=${16} />`}
            </div>
            <div className="modal-title-text">
              <span className="modal-main-title">
                ${previewTarget.type === 'tif' ? 'GeoTIFF Raster Inspector' : 'Map Deliverable Preview'}
              </span>
              <span className="modal-sub-title">${previewTarget.name}</span>
            </div>
          </div>

          <button
            className="btn btn-secondary btn-xs btn-modal-close"
            onClick=${onClose}
            aria-label="Close modal (Esc)"
            type="button"
          >
            <${IconX} size=${14} />
          </button>
        </div>

        <div className="modal-body">
          <div className="canvas-preview-container">
            ${loading ? html`
              <div className="modal-loading-box">
                <span className="spinner-icon-md"></span>
                <span>Parsing raster bands and spatial headers...</span>
              </div>
            ` : null}

            ${error ? html`
              <div className="modal-error-box">
                <span>${error}</span>
              </div>
            ` : null}

            ${previewTarget.type === 'tif' ? html`
              <canvas
                ref=${canvasRef}
                style=${{ display: loading || error ? 'none' : 'block' }}
                className="geotiff-canvas"
              />
            ` : html`
              <img
                src=${previewTarget.url}
                alt=${previewTarget.name}
                className="modal-deliverable-image"
              />
            `}
          </div>

          ${metadata ? html`
            <div className="modal-metadata-strip">
              <div className="metadata-box">
                <span className="metadata-label">Dimensions</span>
                <span className="metadata-val">${metadata.width} × ${metadata.height} px</span>
              </div>
              <div className="metadata-box">
                <span className="metadata-label">Bands</span>
                <span className="metadata-val">${metadata.bands} band${metadata.bands > 1 ? 's' : ''}</span>
              </div>
              <div className="metadata-box">
                <span className="metadata-label">Value Dynamic Range</span>
                <span className="metadata-val">
                  ${typeof metadata.min === 'number' ? metadata.min.toFixed(2) : metadata.min} to ${typeof metadata.max === 'number' ? metadata.max.toFixed(2) : metadata.max}
                </span>
              </div>
              <div className="metadata-box">
                <span className="metadata-label">Spatial Reference</span>
                <span className="metadata-val">${metadata.projection}</span>
              </div>
            </div>
          ` : null}

          <div className="modal-footer-actions">
            <button className="btn btn-secondary btn-sm" onClick=${onClose} type="button">
              Close Inspector
            </button>
            <a
              href=${previewTarget.url}
              download=${previewTarget.name}
              className="btn btn-primary btn-sm btn-modal-download"
            >
              <${IconDownload} size=${13} />
              <span>Download Deliverable</span>
            </a>
          </div>
        </div>
      </div>
    </div>
  `;
}
