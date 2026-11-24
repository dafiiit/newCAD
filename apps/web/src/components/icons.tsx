// Stroke icons from the NewCAD design. All are decorative (aria-hidden); label the button instead.
import type { CSSProperties, ReactNode } from 'react';

interface P { size?: number; color?: string; width?: number; style?: CSSProperties; className?: string }

function Svg({ size = 16, children, fill = 'none', color = 'currentColor', width = 2, style, className, vb = '0 0 24 24', cap }: P & { children: ReactNode; fill?: string; vb?: string; cap?: boolean }) {
  return (
    <svg width={size} height={size} viewBox={vb} fill={fill} stroke={fill === 'none' ? color : undefined} strokeWidth={fill === 'none' ? width : undefined}
      strokeLinecap={cap ? 'round' : undefined} strokeLinejoin={cap ? 'round' : undefined} aria-hidden="true" style={style} className={className}>
      {children}
    </svg>
  );
}

export const CloseIcon = (p: P) => <Svg {...p}><path d="M6 6l12 12M18 6L6 18" /></Svg>;
export const PlusIcon = (p: P) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const ArrowRight = (p: P) => <Svg {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Svg>;
export const ChevronDown = (p: P) => <Svg cap {...p}><path d="M6 9l6 6 6-6" /></Svg>;
export const ChevronRight = (p: P) => <Svg cap {...p}><path d="M9 6l6 6-6 6" /></Svg>;
export const ChevronUp = (p: P) => <Svg cap {...p}><path d="M6 15l6-6 6 6" /></Svg>;
export const CheckIcon = (p: P) => <Svg cap {...p}><path d="M4 12l5 5L20 6" /></Svg>;

export const PanelIcon = ({ size = 20 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#111" strokeWidth="1.8" aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="3" /><rect x="3" y="4" width="7" height="16" rx="2" fill="#111" />
  </svg>
);

export const PencilIcon = (p: P) => (
  <Svg fill="currentColor" {...p}><path d="M4 20l1.2-4.4L16.6 4.2a2 2 0 0 1 2.8 0l.4.4a2 2 0 0 1 0 2.8L8.4 18.8z" /></Svg>
);

export const BranchIcon = (p: P) => (
  <Svg width={1.9} cap {...p}><circle cx="6" cy="5" r="2.2" /><circle cx="6" cy="19" r="2.2" /><circle cx="18" cy="8" r="2.2" /><path d="M6 7.2v9.6M18 10.2c0 4-6 3-11 7" /></Svg>
);

export const BotGlyph = ({ size = 16 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" aria-hidden="true">
    <rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 4v4M9 13h.01M15 13h.01" />
  </svg>
);

export const HomeIcon = (p: P) => (
  <Svg width={1.8} {...p}><path d="M4 11l8-7 8 7" strokeLinejoin="round" /><path d="M6 9.5V20h4.5v-6h3v6H18V9.5" strokeLinejoin="round" /></Svg>
);

export const UserIcon = (p: P) => (
  <Svg width={1.4} color="#111" {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4.5 4.5-6.5 8-6.5s6.5 2 8 6.5z" /></Svg>
);

export const DotsIcon = (p: P) => (
  <Svg fill="currentColor" {...p}><circle cx="5" cy="12" r="2.2" /><circle cx="12" cy="12" r="2.2" /><circle cx="19" cy="12" r="2.2" /></Svg>
);
export const CursorIcon = (p: P) => <Svg fill="currentColor" {...p}><path d="M6 3l13 9.6-5.7 1.1 3.3 6.4-2.5 1.3-3.3-6.4L6 19.2z" /></Svg>;
export const CommentIcon = (p: P) => (
  <Svg fill="currentColor" {...p}><path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" /></Svg>
);

export const ImageIcon = (p: P) => <Svg width={1.7} {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M21 17l-5-5-9 8" /></Svg>;
export const VideoIcon = (p: P) => <Svg width={1.7} {...p}><rect x="3" y="6" width="13" height="12" rx="2" /><path d="M16 10l5-3v10l-5-3" /></Svg>;
export const CubeIcon = (p: P) => <Svg width={1.7} {...p}><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><path d="M4 7.5l8 4.5 8-4.5M12 12v9" /></Svg>;
export const SketchIcon = (p: P) => <Svg width={1.7} {...p}><path d="M4 20l4-1L19 8l-3-3L5 16z" /></Svg>;

export const PathIcon = ({ d, ...p }: P & { d: string }) => <Svg width={1.8} cap {...p}><path d={d} /></Svg>;

export const ExpandIcon = (p: P) => <Svg cap color="#111" {...p}><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" /></Svg>;
export const CollapseIcon = (p: P) => <Svg cap color="#111" {...p}><path d="M4 10h6V4M20 14h-6v6M10 10L3 3M14 14l7 7" /></Svg>;
export const SidebarIcon = (p: P) => <Svg width={1.8} color="#111" {...p}><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></Svg>;
export const TrashIcon = (p: P) => <Svg width={1.8} color="#111" {...p}><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /></Svg>;
export const FolderIcon = (p: P) => <Svg width={1.7} {...p}><path d="M3 6.5h6l2 2h10v10H3z" strokeLinejoin="round" /></Svg>;
export const BooksIcon = (p: P) => <Svg width={1.8} {...p}><path d="M4 5h5v14H4zM10 5h4v14h-4zM15 6l4-1 2 13-4 1z" /></Svg>;
export const StopIcon = (p: P) => <Svg fill="currentColor" {...p}><rect x="6" y="6" width="12" height="12" rx="2" /></Svg>;
export const CodeIcon = (p: P) => <Svg {...p}><path d="M8 7l-5 5 5 5M16 7l5 5-5 5" /></Svg>;

export const PlaceholderCube = ({ size = 80, color = '#999', width = 1.4 }: P) => (
  <svg width={size} height={size * 0.9} viewBox="0 0 70 62" fill="none" stroke={color} strokeWidth={width} aria-hidden="true">
    <path d="M35 4L62 18v26L35 58 8 44V18z" /><path d="M8 18l27 14 27-14M35 32v26" />
  </svg>
);
