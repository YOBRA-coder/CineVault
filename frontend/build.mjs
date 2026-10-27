// Bundles the React app into ./dist (served by the Flask backend).
import { build, context } from 'esbuild';
import { cpSync, mkdirSync, rmSync, readFileSync, writeFileSync } from 'node:fs';

const watch = process.argv.includes('--watch');
if (!watch) rmSync('dist', { recursive: true, force: true });
mkdirSync('dist', { recursive: true });
cpSync('index.html', 'dist/index.html');
cpSync('public', 'dist', { recursive: true });

const opts = {
  entryPoints: ['src/main.jsx', 'src/styles.css'],
  bundle: true,
  minify: !watch,
  sourcemap: watch,
  outdir: 'dist/assets',
  entryNames: 'app',
  jsx: 'automatic',
  target: ['es2020'],
  loader: { '.jsx': 'jsx' },
  define: { 'process.env.NODE_ENV': watch ? '"development"' : '"production"' },
  logLevel: 'info',
};
if (watch) { (await context(opts)).watch(); } else { await build(opts); }

// stamp the service worker with a build id so every release gets fresh caches
const sw = readFileSync('dist/sw.js', 'utf8').replaceAll('__BUILD__', Date.now().toString(36));
writeFileSync('dist/sw.js', sw);
