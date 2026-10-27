import { useEffect, useRef, useState } from 'react';
import { Icon, Modal } from './ui.jsx';
import { Link } from '../router.jsx';
import { streamUrl } from '../api.js';

const LENGTH = 30;

// Plays a 30-second clip from partway into the title, muted by default.
export default function PreviewModal({ title, file, start, onClose }) {
  const v = useRef(null);
  const [muted, setMuted] = useState(true);
  const [t, setT] = useState(0);
  const [ended, setEnded] = useState(false);
  const [err, setErr] = useState(false);
  const begin = useRef(start);

  useEffect(() => { v.current && (v.current.muted = muted); }, [muted]);
  const replay = () => { setEnded(false); v.current.currentTime = begin.current; v.current.play(); };

  return (
    <Modal onClose={onClose} wide label={`Preview of ${title.name}`}>
      <div className="preview">
        {err ? (
          <div className="preview-err">Preview isn’t available right now — the archive may be busy.</div>
        ) : (
          <video ref={v} src={streamUrl(file.id)} autoPlay muted playsInline preload="auto"
            onLoadedMetadata={(e) => {
              const el = e.currentTarget; const d = el.duration;
              // never start so late that fewer than 30s remain (short files / wrong runtime)
              begin.current = Number.isFinite(d) && start > d - LENGTH - 2 ? Math.max(0, d * 0.15) : start;
              el.currentTime = begin.current;
            }}
            onTimeUpdate={(e) => {
              const el = e.currentTarget; const p = Math.max(0, el.currentTime - begin.current);
              setT(Math.min(p, LENGTH));
              if (p >= LENGTH) { el.pause(); setEnded(true); }
            }}
            onError={() => setErr(true)} />
        )}
        <div className="preview-bar"><i style={{ width: `${(t / LENGTH) * 100}%` }} /></div>
        <div className="preview-ctl">
          <button className="icon-btn" onClick={() => setMuted(!muted)} aria-label={muted ? 'Unmute' : 'Mute'}><Icon name={muted ? 'mute' : 'volume'} size={18} /></button>
          {ended && <button className="btn ghost sm" onClick={replay}>Replay</button>}
          <Link to={`/watch/${title.slug}`} className="btn primary sm" onClick={onClose}><Icon name="play" fill size={16} />Watch full {title.kind === 'series' ? 'episode' : 'film'}</Link>
        </div>
      </div>
      <div className="preview-info"><h3>{title.name}</h3><p>{LENGTH}-second preview</p></div>
    </Modal>
  );
}
