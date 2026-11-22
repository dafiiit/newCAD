// Small controls shared by every screen. Class names come from styles/app.css.
import type { ReactNode } from 'react';

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');
export { cx };

/** Position of the sliding selection pill for a segmented control. */
export function sliderOf<T>(list: readonly T[], v: T) {
  const i = Math.max(0, list.indexOf(v));
  return { width: `${100 / list.length}%`, transform: `translateX(${i * 100}%)` };
}

export function Switch({ on, label, onToggle }: { on: boolean; label: string; onToggle: () => void }) {
  return (
    <button className={cx('switch', on && 'on')} role="switch" aria-checked={on} aria-label={label} onClick={onToggle}>
      <span />
    </button>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label, style }: {
  options: readonly T[]; value: T; onChange: (v: T) => void; label: string; style?: React.CSSProperties;
}) {
  return (
    <div className="miniseg" role="radiogroup" aria-label={label} style={style}>
      <span className="slider" aria-hidden="true" style={sliderOf(options, value)} />
      {options.map((o) => (
        <button key={o} className={cx(o === value && 'on')} role="radio" aria-checked={o === value} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

/** Square check mark used inside menus. */
export function MenuCheck({ on }: { on: boolean }) {
  return <span className={cx('check', on && 'on')} />;
}

export function QBox({ on }: { on: boolean }) {
  return (
    <span className={cx('qbox', on && 'on')}>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 12l5 5L20 6" /></svg>
    </span>
  );
}

export function Modal({ label, onClose, className, children }: { label: string; onClose: () => void; className?: string; children: ReactNode }) {
  return (
    <div className="modal" role="dialog" aria-label={label} onClick={onClose}>
      <div className={cx('modalbox', className)} onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
