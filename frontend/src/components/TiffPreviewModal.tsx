import React, { useMemo } from 'react';
import { FilePreviewModal, FilePreviewTarget } from './FilePreviewModal';

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

export const TiffPreviewModal: React.FC<TiffPreviewModalProps> = ({
  previewTarget,
  onClose,
  onOverlayOnGlobe,
}) => {
  const target: FilePreviewTarget | null = useMemo(() => {
    if (!previewTarget) return null;
    return {
      name: previewTarget.name,
      url: previewTarget.url,
      path: previewTarget.path || previewTarget.url || previewTarget.name,
    };
  }, [previewTarget?.path, previewTarget?.url, previewTarget?.name]);

  if (!target) return null;

  return (
    <FilePreviewModal
      target={target}
      onClose={onClose}
      onOverlayOnGlobe={
        onOverlayOnGlobe
          ? (t) => onOverlayOnGlobe({ name: t.name, url: t.url, path: t.path })
          : undefined
      }
    />
  );
};
