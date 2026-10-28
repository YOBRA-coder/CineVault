import { Modal } from './ui.jsx';

export default function TrailerModal({ ytKey, title, onClose }) {
  return (
    <Modal onClose={onClose} wide label={`${title} trailer`}>
      <div className="trailer"><iframe src={`https://www.youtube-nocookie.com/embed/${ytKey}?autoplay=1&rel=0`} title={`${title} trailer`} allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen /></div>
    </Modal>
  );
}
