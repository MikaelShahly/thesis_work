import { useEffect } from "react";

// Full-screen modal for viewing a figure. Dims the background and
// centers the image; click the backdrop, the close button, or press
// Escape to dismiss. The image is loaded straight from the file/raw
// endpoint — figures aren't text, so they can't ride the JSON /file
// endpoint that the side FilePanel uses.
//
// `file` shape: { name, path }.
export default function Lightbox({ projectId, file, onClose }) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const src = `/api/projects/${projectId}/file/raw?path=${encodeURIComponent(
    file.path,
  )}`;

  return (
    <div className="lightbox-backdrop" onMouseDown={onClose}>
      <figure className="lightbox" onMouseDown={(e) => e.stopPropagation()}>
        <button
          className="lightbox-close"
          onClick={onClose}
          title="Close"
          aria-label="Close figure"
        >
          <svg width="14" height="14" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M3 3l6 6M9 3l-6 6" />
          </svg>
        </button>
        <img className="lightbox-img" src={src} alt={file.name} />
        <figcaption className="lightbox-caption">{file.name}</figcaption>
      </figure>
    </div>
  );
}
