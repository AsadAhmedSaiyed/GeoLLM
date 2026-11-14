import { useState, useEffect, useRef, useCallback } from 'react';

interface UseResizableOverlayOptions {
  storageKey?: string;
  defaultWidth?: number;
  minWidth?: number;
  maxWidth?: number;
  maxWidthRatio?: number;
  snapThreshold?: number;
}

const getDynamicMaxWidth = (maxWidth?: number, maxWidthRatio = 0.88): number => {
  if (typeof window === 'undefined') return maxWidth ?? 1200;
  const viewportCap = Math.max(420, Math.floor(window.innerWidth * maxWidthRatio));
  return maxWidth ? Math.max(maxWidth, viewportCap) : viewportCap;
};

export function useResizableOverlay({
  storageKey = 'geollm_chat_overlay_width',
  defaultWidth = 480,
  minWidth = 340,
  maxWidth,
  maxWidthRatio = 0.88,
  snapThreshold = 180,
}: UseResizableOverlayOptions = {}) {
  const [effectiveMaxWidth, setEffectiveMaxWidth] = useState<number>(() =>
    getDynamicMaxWidth(maxWidth, maxWidthRatio)
  );

  const [panelWidth, setPanelWidth] = useState<number>(() => {
    const cap = getDynamicMaxWidth(maxWidth, maxWidthRatio);
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = parseInt(saved, 10);
        if (parsed >= minWidth && parsed <= cap) return parsed;
        if (parsed > cap) return cap;
      }
    } catch {}
    return Math.min(defaultWidth, cap);
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

  useEffect(() => {
    const onResize = () => {
      const nextCap = getDynamicMaxWidth(maxWidth, maxWidthRatio);
      setEffectiveMaxWidth(nextCap);
      setPanelWidth((prev) => Math.min(nextCap, Math.max(minWidth, prev)));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [maxWidth, maxWidthRatio, minWidth]);

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
          const clamped = Math.min(effectiveMaxWidth, Math.max(minWidth, newWidth));
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
    [isCollapsed, panelWidth, snapThreshold, minWidth, effectiveMaxWidth]
  );

  const setPresetWidth = useCallback(
    (preset: 'compact' | 'wide' | 'max') => {
      setIsCollapsed(false);
      const vw = typeof window !== 'undefined' ? window.innerWidth : 1440;
      const target =
        preset === 'compact'
          ? 460
          : preset === 'wide'
            ? Math.floor(vw * 0.62)
            : effectiveMaxWidth;
      const clamped = Math.min(effectiveMaxWidth, Math.max(minWidth, target));
      setPanelWidth(clamped);
      lastExpandedWidthRef.current = clamped;
    },
    [effectiveMaxWidth, minWidth]
  );

  return {
    panelWidth,
    effectiveMaxWidth,
    isCollapsed,
    isDragging,
    toggleCollapse,
    handleMouseDown,
    setPresetWidth,
    setIsCollapsed,
  };
}

