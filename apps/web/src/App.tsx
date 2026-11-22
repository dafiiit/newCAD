import { lazy, Suspense, useEffect, useState } from 'react';
import { useApp } from './state/store';
import { TopChrome } from './components/chrome/TopChrome';
import { BotStatus, ChatBar } from './components/chrome/BotChat';
import { WhatScreen } from './screens/what/WhatScreen';
import { HomeScreen } from './screens/pages/HomeScreen';
import { TeamScreen } from './screens/pages/TeamScreen';
import { SettingsScreen } from './screens/pages/SettingsScreen';
import { AssemblyPicker, FeedbackDialog, PartLibrary, VersionHistory } from './screens/overlays/Overlays';

// three.js and react-three-fiber load only when the 3D view opens
const HowScreen = lazy(() => import('./screens/how/HowScreen').then((m) => ({ default: m.HowScreen })));

function useDarkTheme() {
  const theme = useApp((s) => s.settings.theme);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return;
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return theme === 'Dark' || (theme === 'System' && systemDark);
}

export function App() {
  const layer = useApp((s) => s.layer);
  const review = useApp((s) => s.review);
  const libOpen = useApp((s) => s.libOpen);
  const asmPick = useApp((s) => s.asmPick);
  const feedbackOpen = useApp((s) => s.feedbackOpen);
  const dark = useDarkTheme();

  // Escape closes the topmost overlay or menu
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const s = useApp.getState();
      if (s.feedbackOpen) s.set({ feedbackOpen: false });
      else if (s.libOpen) s.set({ libOpen: false });
      else if (s.asmPick) s.set({ asmPick: false });
      else if (s.review) s.set({ review: false });
      else if (s.menu) s.set({ menu: null });
      else if (s.openPin !== null) s.set({ openPin: null });
      else if (s.tool) s.set({ tool: null });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className={`app${dark ? ' dark' : ''}`}>
      {layer === 'what' && <WhatScreen />}
      {(layer === 'how' || layer === 'check') && <Suspense fallback={null}><HowScreen /></Suspense>}
      {layer === 'home' && <HomeScreen />}
      {layer === 'team' && <TeamScreen />}
      {layer === 'settings' && <SettingsScreen />}

      <TopChrome />
      {layer === 'what' ? <BotStatus /> : <ChatBar />}

      {asmPick && <AssemblyPicker />}
      {feedbackOpen && <FeedbackDialog />}
      {libOpen && <PartLibrary />}
      {review && <VersionHistory />}
    </div>
  );
}
