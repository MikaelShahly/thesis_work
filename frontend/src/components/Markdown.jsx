import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

// Agent + spec-panel markdown renderer. CommonMark + GFM (tables,
// strikethrough, task lists, autolinks) + LaTeX math (inline `$…$`
// and block `$$…$$`). Raw HTML is *not* enabled (react-markdown's
// default) so the model can't inject anchors/scripts. Class names
// map to the existing .md-* rules in styles.css so rendering stays
// visually consistent with the design file.
// Distinguish inline vs. fenced-block code. react-markdown v9+ removed
// the `inline` prop, so we detect block code two ways:
//   1. A `language-*` class (always set on fenced blocks with a language)
//   2. A newline in the content (catches fenced blocks without a language)
// Everything else is inline and gets the pill styling.
function CodeRenderer({ className, children, ...props }) {
  const isLanguageBlock = typeof className === "string" && className.startsWith("language-");
  const text = Array.isArray(children)
    ? children.map(String).join("")
    : String(children ?? "");
  const isBlock = isLanguageBlock || text.includes("\n");
  if (isBlock) {
    return <code className={className} {...props}>{children}</code>;
  }
  return <code className="md-inline-code" {...props}>{children}</code>;
}

const COMPONENTS = {
  h1: (props) => <h1 className="md-h1" {...props} />,
  h2: (props) => <h2 className="md-h2" {...props} />,
  h3: (props) => <h3 className="md-h3" {...props} />,
  p: (props) => <p className="md-p" {...props} />,
  ul: (props) => <ul className="md-ul" {...props} />,
  ol: (props) => <ol className="md-ol" {...props} />,
  li: (props) => <li className="md-li" {...props} />,
  a: (props) => <a className="md-a" target="_blank" rel="noreferrer" {...props} />,
  blockquote: (props) => <blockquote className="md-bq" {...props} />,
  hr: (props) => <hr className="md-hr" {...props} />,
  table: (props) => <table className="md-table" {...props} />,
  pre: (props) => <pre className="md-code-block" {...props} />,
  code: CodeRenderer,
};

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

export default function Markdown({ source }) {
  if (!source) return null;
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={COMPONENTS}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
