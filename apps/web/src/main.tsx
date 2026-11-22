import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles/app.css';
import { startEngineSync } from './engine/sync';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Use the engine when one is running; otherwise the app keeps its mock data.
void startEngineSync();
