import { Icon, Modal, toast } from './ui.jsx';
import { Link } from '../router.jsx';
import { absolute, downloadUrl } from '../api.js';
import { fmtSize } from '../util.js';

// Lists every available file for a movie / episode with quality, size and play / download / copy-link.
export default function DownloadModal({ title, files, heading, season, bulk, onClose }) {
  const copy = async (id) => {
    try { await navigator.clipboard.writeText(absolute(`/api/download/${id}`)); toast('Link copied'); }
    catch { toast('Copy failed — long-press the Download button instead', 'error'); }
  };
  return (
    <Modal onClose={onClose} label="Download options">
      <div className="dl">
        <h3>Download</h3>
        <p className="muted">{heading || title.name}</p>
        {files.length === 0 && bulk ? null : files.length === 0 ? (
          <div className="notice">
            No files are available for this item right now.
            {title.archive_url && <> You can try the <a href={title.archive_url} target="_blank" rel="noreferrer">Internet Archive page <Icon name="ext" size={13} /></a>.</>}
          </div>
        ) : (
          <ul className="file-list">
            {files.map((f) => (
              <li key={f.id}>
                <span className={`q q-${f.quality.replace(/\W/g, '')}`}>{f.quality}</span>
                <span className="file-info"><strong>{f.ext.toUpperCase()}</strong><small>{fmtSize(f.size)}{f.format ? ` · ${f.format}` : ''}</small></span>
                <span className="file-actions">
                  {f.playable && <Link to={`/watch/${title.slug}?f=${f.id}${f.episode_id ? `&ep=${f.episode_id}` : ''}`} className="icon-btn" title="Play this version" onClick={onClose}><Icon name="play" size={16} fill /></Link>}
                  <button className="icon-btn" onClick={() => copy(f.id)} title="Copy link for a download manager"><Icon name="link" size={16} /></button>
                  <a className="btn primary sm" href={downloadUrl(f.id)} download onClick={() => toast('Download started')}><Icon name="download" size={16} />Download</a>
                </span>
              </li>
            ))}
          </ul>
        )}
        {bulk && (
          <div className="bulk">
            <p className="muted">Get the whole {season ? `season ${season}` : 'series'} at best quality — open the list in a download manager (IDM, aria2, JDownloader) or a media player.</p>
            <a className="btn ghost sm" href={`/api/titles/${title.slug}/links.txt${season ? `?season=${season}` : ''}`}><Icon name="list" size={16} />Link list (.txt)</a>
            <a className="btn ghost sm" href={`/api/titles/${title.slug}/playlist.m3u${season ? `?season=${season}` : ''}`}><Icon name="play" size={16} />Playlist (.m3u)</a>
          </div>
        )}
        <p className="fine">Public-domain / openly licensed material hosted by the Internet Archive. Large files can take a while — downloads resume if interrupted.</p>
      </div>
    </Modal>
  );
}
