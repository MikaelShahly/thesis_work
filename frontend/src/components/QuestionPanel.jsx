import { useState } from "react";

// Replaces the Composer when the agent calls AskUserQuestion. The agent
// is paused on the backend awaiting answers; submitting POSTs them to
// /api/projects/{pid}/question/{tool_use_id}/answer, which resolves the
// SDK Future with the selections.
//
// Tabbed wizard: one tab per question (1-4), one question visible at a
// time, free navigation between tabs. Each per-question selection and
// "Other" text lives here in the parent's state and only the active
// question is rendered, so switching tabs and returning preserves
// everything the user typed. Submit enables only once every question is
// answered (and any selected "Other" has non-empty text).
//
// Answer mapping (question text → value):
//   single-select          → the chosen label
//   single-select + Other   → the typed text (not the word "Other")
//   multiSelect            → array of chosen labels, with Other replaced
//                            by its typed text

const OTHER = "__other__";

function blankAnswer() {
  return { selected: [], otherSelected: false, otherText: "" };
}

// A question is answered iff it has at least one selection, and any
// selected "Other" carries non-empty text.
function isAnswered(a) {
  const hasPick = a.selected.length > 0 || a.otherSelected;
  const otherOk = !a.otherSelected || a.otherText.trim().length > 0;
  return hasPick && otherOk;
}

// Build the value for one question from its local answer state.
function answerValue(question, a) {
  if (question.multiSelect) {
    const vals = [...a.selected];
    if (a.otherSelected) vals.push(a.otherText.trim());
    return vals;
  }
  if (a.otherSelected) return a.otherText.trim();
  return a.selected[0];
}

export default function QuestionPanel({ questions = [], pending = false, onSubmit }) {
  const [activeIdx, setActiveIdx] = useState(0);
  const [answers, setAnswers] = useState(() => questions.map(blankAnswer));

  if (questions.length === 0) return null;

  const q = questions[activeIdx] ?? questions[0];
  const a = answers[activeIdx] ?? blankAnswer();
  const multi = !!q.multiSelect;

  const answeredCount = answers.filter(isAnswered).length;
  const allAnswered = answeredCount === questions.length;
  const canSubmit = allAnswered && !pending;

  function patchActive(patch) {
    setAnswers((prev) => {
      const next = prev.slice();
      next[activeIdx] = { ...next[activeIdx], ...patch };
      return next;
    });
  }

  function chooseOption(label) {
    if (multi) {
      const has = a.selected.includes(label);
      patchActive({
        selected: has
          ? a.selected.filter((l) => l !== label)
          : [...a.selected, label],
      });
    } else {
      // Single-select: picking a labelled option clears Other.
      patchActive({ selected: [label], otherSelected: false });
    }
  }

  function chooseOther() {
    if (multi) {
      patchActive({ otherSelected: !a.otherSelected });
    } else {
      patchActive({ selected: [], otherSelected: true });
    }
  }

  function isSelected(label) {
    return a.selected.includes(label);
  }

  function submit() {
    if (!canSubmit) return;
    const out = {};
    questions.forEach((question, i) => {
      out[question.question] = answerValue(question, answers[i]);
    });
    onSubmit?.(out);
  }

  const Control = multi ? CheckBox : RadioDot;

  return (
    <div className="composer-wrap">
      <div className="question-panel">
        {questions.length > 1 && (
          <div className="question-tabs" role="tablist">
            {questions.map((qq, i) => (
              <button
                key={i}
                type="button"
                role="tab"
                aria-selected={i === activeIdx}
                className={
                  "question-tab" + (i === activeIdx ? " active" : "")
                }
                onClick={() => setActiveIdx(i)}
              >
                {qq.header || `Q${i + 1}`}
              </button>
            ))}
          </div>
        )}

        <div className="question-body">
          <div className="question-text">
            {q.question}
            {multi ? <span className="question-hint"> (select any)</span> : null}
          </div>

          <div className="question-options">
            {(q.options ?? []).map((opt, i) => (
              <button
                key={i}
                type="button"
                className={
                  "question-option" + (isSelected(opt.label) ? " selected" : "")
                }
                onClick={() => chooseOption(opt.label)}
              >
                <Control on={isSelected(opt.label)} />
                <span className="question-option-text">
                  <span className="question-option-label">{opt.label}</span>
                  {opt.description ? (
                    <span className="question-option-desc">
                      {opt.description}
                    </span>
                  ) : null}
                </span>
              </button>
            ))}

            <div className="question-other">
              <button
                type="button"
                className={
                  "question-option" + (a.otherSelected ? " selected" : "")
                }
                onClick={chooseOther}
              >
                <Control on={a.otherSelected} />
                <span className="question-option-text">
                  <span className="question-option-label">Other…</span>
                </span>
              </button>
              {a.otherSelected && (
                <input
                  type="text"
                  className="question-other-input"
                  value={a.otherText}
                  onChange={(e) => patchActive({ otherText: e.target.value })}
                  placeholder="Type your answer…"
                  autoFocus
                />
              )}
            </div>
          </div>
        </div>

        <div className="question-footer">
          <span className="question-count">
            {answeredCount} of {questions.length} answered
          </span>
          <button
            type="button"
            className="sp-btn primary"
            disabled={!canSubmit}
            onClick={submit}
          >
            Submit answers
          </button>
        </div>
      </div>
    </div>
  );
}

function RadioDot({ on }) {
  return <span className={"question-radio" + (on ? " on" : "")} aria-hidden />;
}

function CheckBox({ on }) {
  return <span className={"question-check" + (on ? " on" : "")} aria-hidden />;
}
