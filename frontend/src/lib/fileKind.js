// Image formats a browser can render directly in an <img>. Files of
// these types open in the modal lightbox instead of the side FilePanel.
// TIFF is deliberately excluded — browsers can't display it inline (it's
// a print/export format), so a .tiff falls through to the normal file
// path rather than showing a broken image in the lightbox.
export const FIGURE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg"]);

// `file` is a tree entry: { name, path, type } where `type` is the
// lowercased extension. Tolerates a missing/empty type.
export function isFigureFile(file) {
  return FIGURE_EXTS.has((file?.type || "").toLowerCase());
}

// Document deliverables the browser renders natively. Clicking one of
// these embeds it in the right FilePanel via an <iframe> pointed at the
// raw-bytes endpoint (skipping the JSON /file text roundtrip — a PDF
// won't utf-8-decode), and right-clicking offers "Open in new tab".
export const EMBED_DOC_EXTS = new Set(["html", "htm", "pdf"]);

export function isEmbeddableDoc(file) {
  return EMBED_DOC_EXTS.has((file?.type || "").toLowerCase());
}
