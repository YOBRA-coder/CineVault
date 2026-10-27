import { useState } from 'react';
import { Icon, Modal } from './ui.jsx';
import { useInstall, useOnline, useUpdate } from '../pwa.js';

export function OfflineBar() {
  const online = useOnline();
  if (online) return null;
  return <div className="bar offline" role="status"><Icon name="info" size={16} />You’re offline — showing what you’ve already opened. Streaming and downloads need a connection.</div>;
}

export function UpdateBar() {
  const { updateReady, applyUpdate } = useUpdate();
  const [hide, setHide] = useState(false);
  if (!updateReady || hide) return null;
  return (
    <div className="bar update" role="alert">
      A new version of CineVault is ready.
      <button className="btn primary sm" onClick={applyUpdate}>Update now</button>
      <button className="btn ghost sm" onClick={() => setHide(true)}>Later</button>
    </div>
  );
}

export function InstallButton() {
  const { canInstall, iosHint, install } = useInstall();
  const [ios, setIos] = useState(false);
  if (!canInstall && !iosHint) return null;
  return (
    <>
      <button className="btn ghost sm install" onClick={() => (canInstall ? install() : setIos(true))}><Icon name="download" size={16} />Install app</button>
      {ios && (
        <Modal onClose={() => setIos(false)} label="Install CineVault">
          <div className="dl"><h3>Install CineVault</h3>
            <p className="muted">On iPhone / iPad: tap the <b>Share</b> button in Safari, then <b>Add to Home Screen</b>. CineVault will open full-screen like a native app.</p></div>
        </Modal>
      )}
    </>
  );
}
