// Astryx GeoTIFF & Image Standalone Preview Modal
import { html, React } from '/static/js/html.js';
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
        projection: georaster.projection || 'EPSG:32640'
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
            imgData.data[idx] = 15;
            imgData.data[idx + 1] = 23;
            imgData.data[idx + 2] = 42;
            imgData.data[idx + 3] = 0;
          } else {
            const norm = Math.max(0, Math.min(1, (val - minVal) / range));
            imgData.data[idx] = Math.round(68 + norm * 187);
            imgData.data[idx + 1] = Math.round(1 + norm * 190);
            imgData.data[idx + 2] = Math.round(84 + norm * (213 - 84));
            imgData.data[idx + 3] = 255;
          }
        }
      }

      ctx.putImageData(imgData, 0, 0);
      setLoading(false);
    } catch (err) {
      setError(`Failed to parse GeoTIFF: ${err.message}`);
      setLoading(false);
    }
  };

  if (!previewTarget) return null;

  return html`
    <div className="modal-backdrop" onClick=${onClose}>
      <div className="modal-content-card" onClick=${(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span>${previewTarget.type === 'tif' ? '🗺️ GeoTIFF Raster Inspector' : '📊 Map Deliverable Preview'}</span>
            <span style=${{ color: '#94a3b8', fontWeight: 'normal' }}>— ${previewTarget.name}</span>
          </div>
          <button
            className="btn btn-secondary btn-sm"
            onClick=${onClose}
            style=${{ padding: '2px 8px', fontSize: '12px' }}
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          <div className="canvas-preview-container">
            ${loading ? html`<div style=${{ color: '#38bdf8', padding: '40px' }}>Loading and parsing raster...</div>` : null}
            ${error ? html`<div style=${{ color: '#f87171', padding: '40px' }}>${error}</div>` : null}

            ${previewTarget.type === 'tif' ? html`
              <canvas
                ref=${canvasRef}
                style=${{ display: loading || error ? 'none' : 'block' }}
              />
            ` : html`
              <img
                src=${previewTarget.url}
                alt=${previewTarget.name}
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
                <span className="metadata-val">${metadata.bands} band(s)</span>
              </div>
              <div className="metadata-box">
                <span className="metadata-label">Value Range</span>
                <span className="metadata-val">
                  ${typeof metadata.min === 'number' ? metadata.min.toFixed(2) : metadata.min} to ${typeof metadata.max === 'number' ? metadata.max.toFixed(2) : metadata.max}
                </span>
              </div>
              <div className="metadata-box">
                <span className="metadata-label">CRS / Spatial</span>
                <span className="metadata-val">EPSG:32640 / UTM</span>
              </div>
            </div>
          ` : null}

          <div style=${{ width: '100%', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <a
              href=${previewTarget.url}
              download=${previewTarget.name}
              className="btn btn-primary btn-sm"
            >
              ⬇️ Download Deliverable
            </a>
            <button className="btn btn-secondary btn-sm" onClick=${onClose}>
              Close Inspector
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
}
