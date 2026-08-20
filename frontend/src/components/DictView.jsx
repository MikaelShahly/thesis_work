// DictView — generalized regex tokenizer for OpenFOAM dictionaries.
//
// Token classes (per docs/case_builder_plan.md §4.3):
//   comment    `// …` line + `/* … */` block (block may span lines)
//   number     -1, 0.10, 1e-7, 1.5E15, .5
//   string     "..." with escape support
//   bool       true|false|yes|no|on|off (word-boundary)
//   directive  #include, #calc, ${var}, $name
//   key        first identifier on a line
//   value      subsequent identifiers on the same line
//   punct      { } ( ) [ ] ;
//
// Anything else passes through as plain text (unstyled). Works on any
// OpenFOAM dict — no per-file templates and no maintained keyword list.

const PATTERNS = [
  ["comment", /\/\*[\s\S]*?\*\/|\/\/[^\n]*/y],
  ["string", /"(?:[^"\\]|\\.)*"/y],
  // Number must come before ident so 1e-7 / 2.0 / .5 don't get split.
  ["number", /-?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?/y],
  ["directive", /#\w+|\$\{[^}]*\}|\$\w+/y],
  // Bool before ident so the keywords don't get classed as identifiers.
  ["bool", /(?:true|false|yes|no|on|off)\b/y],
  ["ident", /[A-Za-z_][A-Za-z0-9_]*/y],
  ["punct", /[{}();[\]]/y],
  ["whitespace", /\s+/y],
];

function tokenize(content) {
  const tokens = [];
  let pos = 0;
  // Whether we're still at the "first identifier" position on the
  // current logical line. Resets whenever we cross a newline.
  let lineStart = true;

  while (pos < content.length) {
    let matched = false;

    for (const [type, re] of PATTERNS) {
      re.lastIndex = pos;
      const m = re.exec(content);
      if (!m || m.index !== pos) continue;

      let outType = type;
      if (type === "whitespace") {
        if (m[0].includes("\n")) lineStart = true;
      } else if (type === "ident") {
        outType = lineStart ? "key" : "value";
        lineStart = false;
      } else if (type !== "comment") {
        // Numbers, strings, bool, directive, punct all "consume" the
        // first-token-on-line slot. Comment doesn't (a leading comment
        // doesn't change what the next identifier on that line means).
        lineStart = false;
      }

      tokens.push({ type: outType, text: m[0] });
      pos += m[0].length;
      matched = true;
      break;
    }

    if (!matched) {
      // Unknown character (e.g. `.` in `name.thing`, stray punctuation).
      // Pass through as plain so we don't lose the byte.
      tokens.push({ type: "plain", text: content[pos] });
      pos++;
    }
  }

  return tokens;
}

export default function DictView({ content }) {
  const tokens = tokenize(content);
  return (
    <pre className="dict-view">
      {tokens.map((tok, i) =>
        tok.type === "whitespace" || tok.type === "plain" ? (
          <span key={i}>{tok.text}</span>
        ) : (
          <span key={i} className={`dict-tok dict-tok-${tok.type}`}>
            {tok.text}
          </span>
        ),
      )}
    </pre>
  );
}
