import { useRef } from 'react';
import { useApp } from '../../state/store';

const MIN = 260, MAX = 720;

/** Drag handle on the right edge of the side panel. Arrow keys nudge, double-click resets. */
export function DrawerResizer({ which, width }: { which: 'main' | 'code'; width: number }) {
  const drag = useRef<{ x0: number; w0: number } | null>(null);
  const setW = (w: number) => useApp.setState((s) => ({ drawerW: { ...s.drawerW, [which]: Math.round(Math.min(MAX, Math.max(MIN, w))) } }));
  return (
    <button
      className={`dresize${drag.current ? ' drag' : ''}`}
      style={{ left: width }}
      aria-label="Resize panel (drag, or use arrow keys)"
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x0: e.clientX, w0: width }; }}
      onPointerMove={(e) => { if (drag.current) setW(drag.current.w0 + e.clientX - drag.current.x0); }}
      onPointerUp={() => { drag.current = null; }}
      onKeyDown={(e) => { if (e.key === 'ArrowLeft') setW(width - 20); if (e.key === 'ArrowRight') setW(width + 20); }}
      onDoubleClick={() => setW(which === 'code' ? 520 : 320)}
    >
      <span />
    </button>
  );
}
