import { useState, useEffect, useRef, useCallback } from 'react';

interface UseResizableOverlayOptions {
  storageKey?: string;
  defaultWidth?: number;
  minWidth?: number;
  maxWidth?: number;
  snapThreshold?: number;
}

export function useResizableOverlay({
  storageKey = 'geollm_chat_overlay_width',
  defaultWidth = 460,
  minWidth = 320,
  maxWidth = 850,
  snapThreshold = 180,
}: UseResizableOverlayOptions = {}) {
  const [panelWidth, setPanelWidth] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = parseInt(saved, 10);
        if (parsed >= minWidth && parsed <= maxWidth) return parsed;
      }
    } catch {}
    return defaultWidth;
  });

  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem(`${storageKey}_collapsed`);
      if (saved !== null) return saved === 'true';
    } catch {}
    return false;
  });

  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(panelWidth);
  const lastExpandedWidthRef = useRef(panelWidth);

  // Sync state to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(panelWidth));
    } catch {}
  }, [panelWidth, storageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(`${storageKey}_collapsed`, String(isCollapsed));
    } catch {}
  }, [isCollapsed, storageKey]);

  const toggleCollapse = useCallback(() => {
    setIsCollapsed((prev) => {
      if (!prev) {
        // Collapsing
        lastExpandedWidthRef.current = panelWidth;
        return true;
      } else {
        // Expanding
        setPanelWidth(Math.max(minWidth, lastExpandedWidthRef.current));
        return false;
      }
    });
  }, [panelWidth, minWidth]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
      startXRef.current = e.clientX;
      startWidthRef.current = isCollapsed ? 48 : panelWidth;

      const onMouseMove = (moveEvent: MouseEvent) => {
        // Left-anchored: deltaX > 0 moves right edge rightward (expands)
        // deltaX < 0 moves right edge leftward (contracts)
        const deltaX = moveEvent.clientX - startXRef.current;
        const newWidth = startWidthRef.current + deltaX;

        if (newWidth < snapThreshold) {
          setIsCollapsed(true);
        } else {
          setIsCollapsed(false);
          const clamped = Math.min(maxWidth, Math.max(minWidth, newWidth));
          setPanelWidth(clamped);
          lastExpandedWidthRef.current = clamped;
        }
      };

      const onMouseUp = () => {
        setIsDragging(false);
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      };

      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    },
    [isCollapsed, panelWidth, snapThreshold, minWidth, maxWidth]
  );

  return {
    panelWidth,
    isCollapsed,
    isDragging,
    toggleCollapse,
    handleMouseDown,
    setIsCollapsed,
  };
}

