import React, { useState, useRef, useCallback } from 'react';
import {
  Upload,
  X,
  FileImage,
  FileCode,
  Box,
  File,
  Loader2,
  Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface FileUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUpload: (files: FileList) => Promise<void> | void;
}

interface StagedFile {
  file: File;
  id: string;
  name: string;
  sizeMb: number;
  category: 'raster' | 'vector' | 'lidar' | 'image' | 'other';
  previewUrl?: string;
  progress: number;
  status: 'idle' | 'uploading' | 'done' | 'error';
  error?: string;
}

export const FileUploadModal: React.FC<FileUploadModalProps> = ({
  isOpen,
  onClose,
  onUpload,
}) => {
  const [stagedFiles, setStagedFiles] = useState<StagedFile[]>([]);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const getFileCategory = (fname: string): StagedFile['category'] => {
    const ext = fname.toLowerCase().split('.').pop() || '';
    if (['tif', 'tiff', 'img', 'jp2', 'vrt'].includes(ext)) return 'raster';
    if (['laz', 'las'].includes(ext)) return 'lidar';
    if (['geojson', 'shp', 'kml', 'gpkg', 'csv'].includes(ext)) return 'vector';
    if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(ext)) return 'image';
    return 'other';
  };

  const addFiles = useCallback((files: FileList | File[]) => {
    const newItems: StagedFile[] = Array.from(files).map((f) => {
      const cat = getFileCategory(f.name);
      let previewUrl: string | undefined = undefined;
      if (cat === 'image') {
        previewUrl = URL.createObjectURL(f);
      }
      return {
        file: f,
        id: `${f.name}_${f.size}_${Date.now()}_${Math.random()}`,
        name: f.name,
        sizeMb: parseFloat((f.size / (1024 * 1024)).toFixed(2)),
        category: cat,
        previewUrl,
        progress: 0,
        status: 'idle',
      };
    });

    setStagedFiles((prev) => [...prev, ...newItems]);
  }, []);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files);
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeFile = (id: string) => {
    setStagedFiles((prev) => {
      const found = prev.find((f) => f.id === id);
      if (found?.previewUrl) URL.revokeObjectURL(found.previewUrl);
      return prev.filter((f) => f.id !== id);
    });
  };

  const handleStartUpload = async () => {
    if (stagedFiles.length === 0 || isUploading) return;
    setIsUploading(true);

    const dt = new DataTransfer();
    stagedFiles.forEach((sf) => dt.items.add(sf.file));

    try {
      await onUpload(dt.files);
      // Clean up object URLs
      stagedFiles.forEach((sf) => {
        if (sf.previewUrl) URL.revokeObjectURL(sf.previewUrl);
      });
      setStagedFiles([]);
      onClose();
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setIsUploading(false);
    }
  };

  if (!isOpen) return null;

  const totalSizeMb = stagedFiles.reduce((acc, f) => acc + f.sizeMb, 0).toFixed(2);

  const getCategoryIcon = (cat: StagedFile['category']) => {
    switch (cat) {
      case 'raster':
        return <FileImage className="h-4 w-4 text-sky-400" />;
      case 'lidar':
        return <Box className="h-4 w-4 text-purple-400" />;
      case 'vector':
        return <FileCode className="h-4 w-4 text-teal-400" />;
      case 'image':
        return <FileImage className="h-4 w-4 text-emerald-400" />;
      default:
        return <File className="h-4 w-4 text-muted-foreground" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-card border border-border shadow-2xl rounded-2xl w-full max-w-xl overflow-hidden flex flex-col text-xs text-foreground animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between bg-muted/20">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <Upload className="h-4 w-4 text-sky-400" />
            <span>Upload Input Datasets</span>
            {stagedFiles.length > 0 && (
              <span className="text-[11px] font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                {stagedFiles.length} file(s) • {totalSizeMb} MB
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            disabled={isUploading}
            className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-50 cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Dropzone Area */}
        <div className="p-4 space-y-4">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-6 flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${
              isDragging
                ? 'border-sky-400 bg-sky-500/10'
                : 'border-border/80 hover:border-sky-400/60 hover:bg-muted/30 bg-background/50'
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              multiple
              className="hidden"
            />
            <div className="p-3 rounded-full bg-sky-500/10 text-sky-400 mb-2">
              <Upload className="h-6 w-6" />
            </div>
            <div className="font-semibold text-foreground text-xs mb-1">
              Click to select or drag and drop input files here
            </div>
            <div className="text-[11px] text-muted-foreground max-w-sm">
              GeoTIFF (`.tif`), Point Cloud (`.copc.laz`, `.las`), Vector (`.geojson`, `.shp`), or Orthophoto imagery (`.png`, `.jpg`).
            </div>
          </div>

          {/* Staged File List with Previews */}
          {stagedFiles.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px] text-muted-foreground font-semibold uppercase tracking-wider px-1">
                <span>Staged for Upload ({stagedFiles.length})</span>
                <button
                  onClick={() => {
                    stagedFiles.forEach((f) => f.previewUrl && URL.revokeObjectURL(f.previewUrl));
                    setStagedFiles([]);
                  }}
                  disabled={isUploading}
                  className="text-rose-400 hover:text-rose-300 transition-colors cursor-pointer"
                >
                  Clear All
                </button>
              </div>

              <div className="max-h-56 overflow-y-auto space-y-1.5 pr-1">
                {stagedFiles.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center justify-between gap-3 p-2 rounded-xl bg-background border border-border/70 hover:border-border transition-colors"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      {f.previewUrl ? (
                        <img
                          src={f.previewUrl}
                          alt={f.name}
                          className="w-8 h-8 rounded-md object-cover border border-border shrink-0"
                        />
                      ) : (
                        <div className="p-2 rounded-md bg-muted shrink-0">
                          {getCategoryIcon(f.category)}
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-[11.5px] truncate font-medium text-foreground">
                          {f.name}
                        </div>
                        <div className="text-[10px] text-muted-foreground flex items-center gap-2">
                          <span className="uppercase">{f.category}</span>
                          <span>•</span>
                          <span>{f.sizeMb} MB</span>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => removeFile(f.id)}
                      disabled={isUploading}
                      className="p-1 rounded-md text-muted-foreground hover:text-rose-400 transition-colors shrink-0 disabled:opacity-40 cursor-pointer"
                      title="Remove from staging"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-3 border-t border-border bg-muted/20 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={isUploading}
            className="text-xs h-8 px-3"
          >
            Cancel
          </Button>

          <Button
            onClick={handleStartUpload}
            disabled={stagedFiles.length === 0 || isUploading}
            className="text-xs h-8 px-4 bg-sky-600 hover:bg-sky-500 text-white font-semibold flex items-center gap-1.5"
          >
            {isUploading ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Uploading...</span>
              </>
            ) : (
              <>
                <Upload className="h-3.5 w-3.5" />
                <span>Upload {stagedFiles.length} File(s)</span>
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
};
