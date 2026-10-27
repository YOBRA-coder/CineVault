import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { registerSW } from './pwa.js';

registerSW();
createRoot(document.getElementById('root')).render(<App />);
