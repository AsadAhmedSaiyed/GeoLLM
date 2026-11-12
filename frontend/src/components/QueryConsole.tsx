import React, { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Play, X, Satellite, Loader2, AlertCircle, ChevronUp, ChevronDown, Upload } from 'lucide-react';

interface QueryConsoleProps {
  selectedFiles: string[];
  onRemoveFile: (fileName: string) => void;
  onClearAllFiles?: () => void;
  onUploadFiles?: (files: FileList) => Promise<void> | void;
  onSubmit: (question: string) => void;
  isSubmitting: boolean;
  isRunning?: boolean;
  hasActiveWorkspace: boolean;
  injectedPrompt?: string | null;
  onInjectedPromptConsumed?: () => void;
  isFolded?: boolean;
  onToggleFold?: () => void;
}

export const QueryConsole: React.FC<QueryConsoleProps> = ({
  selectedFiles,
  onRemoveFile,
  onClearAllFiles,
  onUploadFiles,
  onSubmit,
  isSubmitting,
  isRunning = false,
  hasActiveWorkspace,
  injectedPrompt,
  onInjectedPromptConsumed,
  isFolded = false,
  onToggleFold,
}) => {
  const [question, setQuestion] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !onUploadFiles) return;
    setIsUploading(true);
    try {
      await onUploadFiles(files);
    } finally {
      setIsUploading(false);
      e.target.value = '';
    }
  };

  useEffect(() => {
    if (injectedPrompt) {
      setQuestion((prev) =>
        prev.trim() ? `${prev.trim()} ${injectedPrompt}` : injectedPrompt
      );
      onInjectedPromptConsumed?.();
    }
  }, [injectedPrompt, onInjectedPromptConsumed]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!hasActiveWorkspace || !question.trim() || isSubmitting || isRunning) return;
    const q = question.trim();
    setQuestion('');
    onSubmit(q);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="h-full w-full bg-card border-b border-border p-3 flex flex-col gap-2 overflow-hidden">
      {/* Top Header: Attached Datasets / Mode Notice + Fold Button */}
      <div className="shrink-0 flex items-center justify-between gap-1.5 min-h-[26px]">
        <div className="flex flex-wrap items-center gap-1.5 flex-1 min-w-0">
          {!hasActiveWorkspace ? (
            <div className="flex items-center gap-1.5 text-xs text-amber-500 bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 rounded-none font-mono truncate">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">Workspace required — click "+ New" above</span>
            </div>
          ) : selectedFiles.length === 0 ? (
            <div className="flex items-center gap-1.5 text-xs text-primary bg-primary/10 border border-primary/30 px-2 py-0.5 rounded-none font-mono">
              <Satellite className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">Autonomous STAC Mode</span>
            </div>
          ) : (
            <>
              {selectedFiles.map((fname) => (
                <div
                  key={fname}
                  className="flex items-center gap-1 bg-[#0F766E]/20 border border-[#14B8A6]/40 text-[#2DD4BF] px-2 py-0.5 rounded-none text-xs font-mono"
                >
                  <span className="truncate max-w-[140px]">{fname}</span>
                  <button
                    type="button"
                    onClick={() => onRemoveFile(fname)}
                    className="hover:text-foreground cursor-pointer ml-1"
                    title="Remove attachment"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
              {selectedFiles.length > 1 && onClearAllFiles && (
                <button
                  type="button"
                  onClick={onClearAllFiles}
                  className="text-[11px] text-destructive hover:underline px-1.5 py-0.5 cursor-pointer font-mono"
                  title="Clear all attached files"
                >
                  Clear all
                </button>
              )}
            </>
          )}
        </div>

        {onToggleFold && (
          <button
            type="button"
            onClick={onToggleFold}
            className="p-1 rounded-none text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer shrink-0"
            title={isFolded ? "Slide down to expand query input" : "Slide up to fold query box (maximize output)"}
          >
            {isFolded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
        )}
      </div>

      {/* Query Prompt Textarea - Expands/shrinks with vertical slider */}
      {!isFolded && (
        <>
          <div className="flex-1 min-h-[48px] relative flex flex-col">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                hasActiveWorkspace
                  ? "Ask a geospatial query (e.g., 'Compare 2016 and 2024 Landsat images and map changes with high-res visualization')…"
                  : "Create or select a workspace first (+ New) to start an analysis..."
              }
              disabled={!hasActiveWorkspace || isSubmitting}
              className="w-full h-full min-h-[48px] bg-background border border-border rounded-none p-2.5 text-[13px] leading-relaxed text-foreground placeholder:text-muted-foreground font-mono resize-none focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50 overflow-y-auto"
            />
          </div>

          {/* Submit Action Bar */}
          <div className="shrink-0 flex items-center justify-between gap-2 pt-0.5">
            <div className="flex items-center gap-2 min-w-0">
              {onUploadFiles && (
                <>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={handleFileChange}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={!hasActiveWorkspace || isUploading || isSubmitting}
                    onClick={() => fileInputRef.current?.click()}
                    className="h-8 px-2.5 text-xs gap-1.5"
                    title="Upload GeoTIFF, LAZ/LAS, PNG, or any input file"
                  >
                    {isUploading ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        <span>Uploading…</span>
                      </>
                    ) : (
                      <>
                        <Upload className="h-3.5 w-3.5" />
                        <span>Upload</span>
                      </>
                    )}
                  </Button>
                </>
              )}
              <span className="text-[11px] text-muted-foreground font-mono truncate">
                {question.length > 0 ? `${question.length} chars` : 'Ready to analyze'}
              </span>
            </div>

            <Button
              onClick={() => handleSubmit()}
              disabled={!hasActiveWorkspace || !question.trim() || isSubmitting || isRunning}
              size="sm"
              variant="default"
              className="gap-1.5 h-8 px-4 text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Dispatching…</span>
                </>
              ) : isRunning ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Analysis Running…</span>
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 fill-current" />
                  <span>Run Analysis</span>
                </>
              )}
            </Button>
          </div>
        </>
      )}
    </div>
  );
};
