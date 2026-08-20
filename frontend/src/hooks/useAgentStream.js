import { useEffect, useReducer, useRef } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";

// ── USER ACTION prefixes (§9.9) ─────────────────────────────────
// When the user interacts with the AcceptPanel, the message sent to
// the backend is prefixed so the agent knows what UI action led here.
// The prefix is stripped before rendering the user bubble.
//
// simulation_spec uses verbose [USER ACTION: …] tags for both
// question/feedback paths. case_builder uses [Feedback on case]: for
// feedback only — questions go through plain. mesh sub-step approval
// uses [Feedback on mesh]:. Phase-advance feedback uses the
// phase-agnostic [Feedback]: prefix regardless of phase, mirroring
// request_phase_advance's phase-agnostic shape.
const USER_ACTION_RE = /^\[USER ACTION:[^\]]*\]\s*\n\n/s;
// Legacy: case_builder feedback now uses the phase-agnostic [Feedback]:
// prefix; this RE still strips the old prefix from historical messages.
const CASE_FEEDBACK_RE = /^\[Feedback on case\]:\s*/s;
const MESH_FEEDBACK_PREFIX = "[Feedback on mesh]: ";
const MESH_FEEDBACK_RE = /^\[Feedback on mesh\]:\s*/s;
const EXPERIMENT_FEEDBACK_PREFIX = "[Feedback on experiment]: ";
const EXPERIMENT_FEEDBACK_RE = /^\[Feedback on experiment\]:\s*/s;
const PHASE_ADVANCE_FEEDBACK_PREFIX = "[Feedback]: ";
const PHASE_ADVANCE_FEEDBACK_RE = /^\[Feedback\]:\s*/s;
const USER_ACTION_QUESTION =
  "[USER ACTION: The user chose to ask a follow-up question before deciding on the specification.]";
const USER_ACTION_FEEDBACK =
  "[USER ACTION: The user rejected the current specification and provided feedback for revision.]";

function stripUserAction(content) {
  return content
    .replace(USER_ACTION_RE, "")
    .replace(CASE_FEEDBACK_RE, "")
    .replace(MESH_FEEDBACK_RE, "")
    .replace(EXPERIMENT_FEEDBACK_RE, "")
    .replace(PHASE_ADVANCE_FEEDBACK_RE, "");
}

function applyUserActionPrefix(content, userAction, phase, pendingKind) {
  // Approval-kind-specific prefixes take precedence over phase
  // dispatch: the same phase can host multiple approval tools (e.g.
  // improver has both `request_mesh_approval` and
  // `request_experiment_approval`), and feedback needs to land on
  // whichever the user was actually responding to.
  if (userAction === "feedback") {
    if (
      pendingKind === "case_builder_phase_advance" ||
      pendingKind === "mesh_phase_advance" ||
      pendingKind === "improver_phase_advance"
    ) {
      // request_phase_advance is the phase-agnostic completion gate for
      // every phase, so its feedback prefix is phase-agnostic too.
      return `${PHASE_ADVANCE_FEEDBACK_PREFIX}${content}`;
    }
    if (pendingKind === "improver_experiment") {
      return `${EXPERIMENT_FEEDBACK_PREFIX}${content}`;
    }
    if (pendingKind === "mesh_step") {
      // Covers both mesh-phase sub-step approval and improver-phase
      // request_mesh_approval (same wiring, same prefix).
      return `${MESH_FEEDBACK_PREFIX}${content}`;
    }
  }
  if (phase === "case_builder") {
    // case_builder's only approval gate is request_phase_advance.
    if (userAction === "feedback") return `${PHASE_ADVANCE_FEEDBACK_PREFIX}${content}`;
    // Questions during case_builder approval go plain — no prefix.
    return content;
  }
  if (phase === "mesh" || phase === "improver") {
    // Questions during sub-step / experiment / mesh / phase-advance
    // approvals go plain — agent infers question vs. continue from
    // content.
    return content;
  }
  if (userAction === "question") return `${USER_ACTION_QUESTION}\n\n${content}`;
  if (userAction === "feedback") return `${USER_ACTION_FEEDBACK}\n\n${content}`;
  return content;
}

// ── Sub-agent display names ─────────────────────────────────────
// Maps the SDK `subagent_type` (the key the backend registers in
// ClaudeAgentOptions.agents — same name used as the prefix on segment
// labels and in the permission modal) to the human-readable label the
// UI shows. Add an entry here when wiring a new sub-agent on the
// backend; falls back to the raw subagent_type when missing so a new
// sub-agent isn't silently invisible.
const SUBAGENT_DISPLAY_NAMES = {
  openfoam2412_repository_explore:
    "OpenFOAM Source Repository Exploration sub-agent",
  paraview_operator: "ParaView Operator sub-agent",
  cfd_general_purpose: "CFD General Purpose sub-agent",
  verification: "Verification sub-agent",
};

function subagentDisplayName(subagentType) {
  if (!subagentType) return null;
  return SUBAGENT_DISPLAY_NAMES[subagentType] || `${subagentType} sub-agent`;
}

// Backend chat-history entry → chat-state message.
//
// Assistant entries now carry a `segments` array — the ordered
// text / thinking / tool breakdown the live UI displayed. We rebuild
// the segment shape the renderer expects (status: "done", parsed
// tool input, derived agentLabel) so a reloaded turn is visually
// indistinguishable from one that streamed in. Older rows that
// predate the segment table fall back to a single text segment built
// from `entry.content`.
function buildMessagesFromHistory(history) {
  return history.map((entry) => {
    if (entry.type === "phase_transition") {
      return { type: "phase_transition", from: entry.from, to: entry.to };
    }
    if (entry.type === "compaction") {
      return {
        type: "compaction",
        preTokens: entry.pre_tokens ?? null,
        postTokens: entry.post_tokens ?? null,
        trigger: entry.trigger ?? null,
      };
    }
    if (entry.role === "user") {
      return { type: "user", content: stripUserAction(entry.content) };
    }
    const persisted = Array.isArray(entry.segments) ? entry.segments : [];
    let segments;
    if (persisted.length > 0) {
      segments = rehydrateSegments(persisted);
    } else if (entry.content) {
      segments = [{ kind: "text", content: entry.content }];
    } else {
      segments = [];
    }
    return { type: "agent", segments, streaming: false };
  });
}

// Walk persisted segments in order, mirroring the live reducer's
// `parent_tool_use_id → agentLabel` derivation: when we encounter an
// `Agent` tool call, register its `subagent_type` against its
// `tool_use_id`; subsequent segments tagged with that id as their
// `parent_tool_use_id` inherit the resolved display label.
function rehydrateSegments(rows) {
  const subagentLabels = {};
  const out = [];
  for (const row of rows) {
    const ptu = row.parent_tool_use_id || null;
    const agentLabel = ptu ? subagentLabels[ptu] || null : null;
    if (row.kind === "text") {
      out.push({
        kind: "text",
        content: row.content ?? "",
        agentLabel,
      });
      continue;
    }
    if (row.kind === "thinking") {
      out.push({
        kind: "thinking",
        status: "done",
        content: row.content ?? "",
        agentLabel,
      });
      continue;
    }
    if (row.kind === "tool") {
      const input = parseToolInput(row.tool_input);
      if (
        row.tool_name === "Agent" &&
        row.tool_use_id &&
        input &&
        typeof input === "object"
      ) {
        const display = subagentDisplayName(input.subagent_type);
        if (display) subagentLabels[row.tool_use_id] = display;
      }
      out.push({
        kind: "tool",
        id: row.tool_use_id || "",
        status: "done",
        tool: row.tool_name || "",
        input,
        output: row.content,
        isError: !!row.tool_is_error,
        agentLabel,
      });
    }
  }
  return out;
}

function parseToolInput(raw) {
  if (raw == null) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

// ── Reducer helpers ──────────────────────────────────────────────
//
// Agent message shape:
//   { type: "agent", streaming: bool, segments: Segment[] }
//
// where Segment is one of:
//   { kind: "text",     content: string,                    agentLabel?: string }
//   { kind: "thinking", status: "running"|"done", content,  agentLabel?: string }
//   { kind: "tool",     id: string, status, tool: string,
//                       input: object|null, output: string|null,
//                       isError?: bool,                     agentLabel?: string }
//
// `agentLabel` is the human display name of the sub-agent that
// produced the segment (populated when the backend tagged the source
// event with a `parent_tool_use_id` we recognise). Absent ⇒
// parent-agent scope. The renderer uses it to prefix labels so the
// user can tell which agent did what.
//
// Segments render in array order, so prose can interleave with
// thinking/tool blocks within a single agent turn.
function ensureStreamingAgent(messages) {
  const last = messages[messages.length - 1];
  if (last?.type === "agent" && last.streaming) return messages;
  return [
    ...messages,
    { type: "agent", segments: [], streaming: true },
  ];
}
function updateLastAgent(messages, patch) {
  const copy = [...messages];
  const last = copy[copy.length - 1];
  copy[copy.length - 1] = { ...last, ...patch(last) };
  return copy;
}
// Push a new segment onto the streaming agent row (creating one if
// the last message isn't already a streaming agent).
function pushSegment(state, segment) {
  const m = ensureStreamingAgent(state.messages);
  return {
    ...state,
    messages: updateLastAgent(m, (a) => ({ segments: [...a.segments, segment] })),
  };
}
// Locate the index of a segment satisfying `pred`, scanning from the
// end of the array. Returns -1 if not found. Used to match
// `thinking_text` to its running thinking segment and `tool_input` /
// `tool_output` to their tool segments by id.
function findLastSegmentIndex(segments, pred) {
  for (let i = segments.length - 1; i >= 0; i--) {
    if (pred(segments[i])) return i;
  }
  return -1;
}
// Update a specific segment on the streaming agent row by index.
function updateSegment(state, idx, patch) {
  const m = ensureStreamingAgent(state.messages);
  return {
    ...state,
    messages: updateLastAgent(m, (a) => {
      const next = a.segments.slice();
      if (idx >= 0 && idx < next.length) {
        next[idx] = { ...next[idx], ...patch };
      }
      return { segments: next };
    }),
  };
}

const initialState = {
  messages: [],
  streaming: false,
  // Backend-reported "a turn is running for this project" flag, refreshed
  // by the turn-active poll. Unlike `streaming` (driven by stream events),
  // this is true even when the turn is silent — a long background solver,
  // or a turn stalled on a dropped connection. Drives the composer's Stop
  // button so the user can always interrupt / isn't locked out by a 409.
  turnActive: false,
  // Phase the project is currently in. Drives prefix scheme + which
  // approval flow (spec vs case) the reducer enacts.
  phase: null,
  // Review-mode state:
  specDraft: null, // latest specification markdown, null when not in review
  acceptMode: null, // "pick" | "feedback" | "accepted" | null
  pendingUserAction: null, // "question" — applied to the NEXT sendMessage call
  // case_builder & mesh: backing flag for the approval-pending pill
  // above the composer. True when an approval-requesting tool has
  // fired and the user has dismissed the AcceptPanel via "Ask a
  // question" but hasn't yet approved or sent feedback.
  approvalPending: false,
  // Discriminator for which approval is currently pending — drives
  // AcceptPanel copy and which approve handler the pill / panel
  // invokes. Mirrors `projects.approval_kind` in the DB so a reload
  // restores the correct UI.
  //   "case_builder_phase_advance" — case_builder request_phase_advance
  //   "mesh_step"                  — mesh request_subtask_approval
  //   "mesh_phase_advance"         — mesh request_phase_advance
  //   "improver_phase_advance"     — improver request_phase_advance
  //   "improver_experiment"        — improver request_experiment_approval
  //   null                         — no approval pending
  pendingKind: null,
  // Permission-gate state. Non-null while the agent is paused on a
  // can_use_tool request and the UI is showing a Allow/Deny prompt.
  permissionRequest: null, // {tool_use_id, tool, input, agentLabel?} | null
  // AskUserQuestion state. Non-null while the agent is paused on an
  // AskUserQuestion call and the UI is showing the QuestionPanel.
  // Always parent-scope (sub-agents can't call the tool).
  questionRequest: null, // {tool_use_id, questions} | null
  // True while the SDK is compacting context (between
  // `compaction_started` and `compaction_complete`). Drives the
  // transient "Compacting context…" spinner row; on completion it's
  // replaced by a persisted compaction divider in the message list.
  compacting: false,
  // Per-stream map: parent_tool_use_id → sub-agent display name.
  // Populated when the parent agent's `Agent` tool_input arrives (its
  // input.subagent_type names the delegate). Subsequent streaming
  // events that carry the same id as `parent_tool_use_id` are tagged
  // with this label so the UI can prefix them. Cleared on each
  // turn_complete since ids are only meaningful within a turn.
  subagentLabels: {},
};

// Resolve a streamed event's `parent_tool_use_id` to the sub-agent's
// display label, using the in-flight map populated when we saw the
// parent agent invoke `Agent`. Returns null when the event came from
// the parent agent itself (no parent_tool_use_id) or from a sub-agent
// we don't yet have a mapping for.
function labelForEvent(state, data) {
  const ptu = data?.parent_tool_use_id;
  if (!ptu) return null;
  return state.subagentLabels[ptu] || null;
}

function reducer(state, action) {
  switch (action.type) {
    case "history_loaded":
      return {
        ...initialState,
        messages: action.messages,
        phase: action.phase ?? null,
        specDraft: action.specDraft ?? null,
        acceptMode: action.acceptMode ?? null,
        approvalPending: action.approvalPending ?? false,
        pendingKind: action.pendingKind ?? null,
        turnActive: action.turnActive ?? false,
      };

    // Backend turn-active poll result. Short-circuit when unchanged so the
    // 4s tick doesn't force a re-render while idle.
    case "set_turn_active":
      return state.turnActive === action.value
        ? state
        : { ...state, turnActive: action.value };

    case "user_sent":
      return {
        ...state,
        messages: [...state.messages, { type: "user", content: action.content }],
        streaming: true,
      };

    // Re-attaching to a turn that's already running (project switch-back).
    // No user message is added (it's already in the loaded history); we
    // just enter the streaming state so the red interrupt icon shows and
    // the composer gates. The replayed agent events then rebuild the turn.
    case "reattach_start":
      return { ...state, streaming: true };

    // ── Streamed agent events ───────────────────────────────────
    case "thinking_started": {
      // Push a running thinking segment; content fills in when the
      // matching `thinking_text` arrives from the assembled message.
      const agentLabel = labelForEvent(state, action.data);
      return pushSegment(state, {
        kind: "thinking",
        status: "running",
        content: "",
        agentLabel,
      });
    }

    case "thinking_delta": {
      // Streamed reasoning chunk. Append to the matching running
      // thinking segment so the user can watch it populate live when
      // they expand the row. The trailing `thinking_text` arrives
      // after the deltas and overwrites with the canonical snapshot.
      const m = ensureStreamingAgent(state.messages);
      const last = m[m.length - 1];
      const chunk = action.data.content ?? "";
      const agentLabel = labelForEvent(state, action.data);
      const idx = findLastSegmentIndex(
        last.segments,
        (s) =>
          s.kind === "thinking" &&
          s.status === "running" &&
          (s.agentLabel ?? null) === agentLabel,
      );
      if (idx === -1) {
        // Defensive — `thinking_started` was missed. Push a running
        // segment with the chunk as initial content.
        return pushSegment({ ...state, messages: m }, {
          kind: "thinking",
          status: "running",
          content: chunk,
          agentLabel,
        });
      }
      const seg = last.segments[idx];
      return updateSegment({ ...state, messages: m }, idx, {
        content: (seg.content || "") + chunk,
      });
    }

    case "thinking_text": {
      const m = ensureStreamingAgent(state.messages);
      const last = m[m.length - 1];
      const agentLabel = labelForEvent(state, action.data);
      const idx = findLastSegmentIndex(
        last.segments,
        (s) =>
          s.kind === "thinking" &&
          s.status === "running" &&
          (s.agentLabel ?? null) === agentLabel,
      );
      if (idx === -1) {
        // Defensive — `thinking_started` was missed (e.g. the stream
        // event was dropped). Push a done segment with the content so
        // it isn't lost.
        return pushSegment({ ...state, messages: m }, {
          kind: "thinking",
          status: "done",
          content: action.data.content ?? "",
          agentLabel,
        });
      }
      return updateSegment({ ...state, messages: m }, idx, {
        status: "done",
        content: action.data.content ?? "",
      });
    }

    case "tool_started": {
      const agentLabel = labelForEvent(state, action.data);
      return pushSegment(state, {
        kind: "tool",
        id: action.data.id ?? "",
        status: "running",
        tool: action.data.tool ?? "",
        input: null,
        output: null,
        agentLabel,
      });
    }

    case "tool_input": {
      const m = ensureStreamingAgent(state.messages);
      const last = m[m.length - 1];
      const id = action.data.id ?? "";
      const tool = action.data.tool ?? "";
      const input = action.data.input ?? null;
      const agentLabel = labelForEvent(state, action.data);

      // When the parent agent invokes `Agent`, capture the
      // tool_use_id → sub-agent display name mapping so subsequent
      // events that carry this id as `parent_tool_use_id` get tagged
      // with the right label. We learn the subagent_type only here —
      // the earlier `tool_started` arrives without input.
      let nextSubagentLabels = state.subagentLabels;
      if (tool === "Agent" && id && input && typeof input === "object") {
        const subType = input.subagent_type;
        const display = subagentDisplayName(subType);
        if (display && nextSubagentLabels[id] !== display) {
          nextSubagentLabels = { ...nextSubagentLabels, [id]: display };
        }
      }

      const idx = findLastSegmentIndex(
        last.segments,
        (s) => s.kind === "tool" && s.id === id,
      );
      const stateWithLabels = { ...state, messages: m, subagentLabels: nextSubagentLabels };
      if (idx === -1) {
        // No matching tool_started segment — push a fresh running
        // segment with the input attached.
        return pushSegment(stateWithLabels, {
          kind: "tool",
          id,
          status: "running",
          tool,
          input,
          output: null,
          agentLabel,
        });
      }
      return updateSegment(stateWithLabels, idx, { input });
    }

    case "tool_output": {
      const m = ensureStreamingAgent(state.messages);
      const last = m[m.length - 1];
      const id = action.data.tool_use_id ?? "";
      const agentLabel = labelForEvent(state, action.data);
      const idx = findLastSegmentIndex(
        last.segments,
        (s) => s.kind === "tool" && s.id === id,
      );
      if (idx === -1) {
        // The matching tool_started/tool_input never arrived (rare —
        // would mean the SDK skipped the assistant message for this
        // tool call). Render the orphan output as a done tool segment
        // so the result still surfaces.
        return pushSegment({ ...state, messages: m }, {
          kind: "tool",
          id,
          status: "done",
          tool: "",
          input: null,
          output: action.data.content ?? "",
          isError: !!action.data.is_error,
          agentLabel,
        });
      }
      return updateSegment({ ...state, messages: m }, idx, {
        status: "done",
        output: action.data.content ?? "",
        isError: !!action.data.is_error,
      });
    }

    case "compaction_started":
      // SDK began compacting context. Flip the flag so the UI shows a
      // transient "Compacting context…" spinner during the stall (no
      // regular events stream while compaction runs).
      return { ...state, compacting: true };

    case "compaction_complete": {
      // Compaction finished. Replace the transient spinner with a
      // persisted divider. Insert it *before* the currently-streaming
      // agent bubble (if any) so the bubble stays intact and the live
      // ordering matches the reload ordering (the backend persists the
      // compaction row before the turn's assistant row).
      const divider = {
        type: "compaction",
        preTokens: action.data.pre_tokens ?? null,
        postTokens: action.data.post_tokens ?? null,
        trigger: action.data.trigger ?? null,
      };
      const msgs = [...state.messages];
      const last = msgs[msgs.length - 1];
      if (last?.type === "agent" && last.streaming) {
        msgs.splice(msgs.length - 1, 0, divider);
      } else {
        msgs.push(divider);
      }
      return { ...state, messages: msgs, compacting: false };
    }

    case "status":
      // Informational status text — no data path emits this currently,
      // but if one does we keep it as a one-off text segment so it's
      // not silently dropped.
      return pushSegment(state, { kind: "text", content: action.data.message ?? "" });

    case "text_delta": {
      const m = ensureStreamingAgent(state.messages);
      const last = m[m.length - 1];
      const segs = last.segments;
      const tail = segs[segs.length - 1];
      const chunk = action.data.content ?? "";
      const agentLabel = labelForEvent(state, action.data);
      if (
        tail &&
        tail.kind === "text" &&
        (tail.agentLabel ?? null) === agentLabel
      ) {
        // Append to the trailing text run so prose flows naturally —
        // but only if it's the same scope (sub-agent text gets its
        // own run so it can carry the prefix).
        return updateSegment(
          { ...state, messages: m },
          segs.length - 1,
          { content: tail.content + chunk },
        );
      }
      // A thinking/tool segment intervened, the scope changed, or
      // this is the first text — start a new text segment so the
      // prose lands AFTER the inline event row.
      return pushSegment({ ...state, messages: m }, {
        kind: "text",
        content: chunk,
        agentLabel,
      });
    }

    case "specification_presented":
      // The agent called present_specification. The event fires once
      // per draft — multiple fires in one conversation overwrite.
      return {
        ...state,
        specDraft: action.data.markdown ?? "",
        acceptMode: "pick",
      };

    case "subtask_approval_requested":
      // Shared event for mesh `request_subtask_approval` AND improver
      // `request_mesh_approval` — same approval_kind, same approve
      // endpoint, same panel/pill shape.
      return {
        ...state,
        acceptMode: "pick",
        approvalPending: true,
        pendingKind: "mesh_step",
      };

    case "experiment_approval_requested":
      // improver: agent called request_experiment_approval. Surface
      // the experiment-plan approval pill / panel.
      return {
        ...state,
        acceptMode: "pick",
        approvalPending: true,
        pendingKind: "improver_experiment",
      };

    case "phase_advance_requested":
      // Phase-agnostic terminal gesture — the single phase-completion
      // gate for every phase. The discriminator is the current phase:
      // case_builder → "case_builder_phase_advance", mesh →
      // "mesh_phase_advance", improver → "improver_phase_advance".
      // `state.phase` is kept in sync by `phase_transitioned` and the
      // initial fetch.
      return {
        ...state,
        acceptMode: "pick",
        approvalPending: true,
        pendingKind: `${state.phase}_phase_advance`,
      };

    case "permission_requested":
      // Backend is awaiting our Allow/Deny on a non-allowlisted tool
      // call. Composer swaps for PermissionPanel until we POST back.
      // `agent_id` is set when the call originated from inside a
      // sub-agent — we surface it via the SUBAGENT_DISPLAY_NAMES map
      // so the modal can prefix the title (subagent ids and the
      // `subagent_type` we map from share the same string).
      return {
        ...state,
        permissionRequest: {
          tool_use_id: action.data.tool_use_id,
          tool: action.data.tool,
          input: action.data.input ?? {},
          agentLabel: subagentDisplayName(action.data.agent_id),
        },
      };

    case "question_requested":
      // Agent called AskUserQuestion. Composer swaps for the
      // QuestionPanel until the user submits. No agentLabel — the tool
      // is parent-scope only.
      return {
        ...state,
        questionRequest: {
          tool_use_id: action.data.tool_use_id,
          questions: action.data.questions ?? [],
        },
      };

    case "question_resolved": {
      // Two sources: the local optimistic dispatch when the user submits
      // (tool_use_id at top level), and the buffered stream event replayed
      // on re-attach (tool_use_id under `data`). Accept either, so a
      // re-attaching client closes an already-answered question instead of
      // re-popping it. Clear iff still showing the request we resolved
      // (guards a parallel-call race).
      const tid = action.data?.tool_use_id ?? action.tool_use_id;
      if (state.questionRequest?.tool_use_id !== tid) {
        return state;
      }
      return { ...state, questionRequest: null };
    }

    case "permission_resolved": {
      // Two sources: the local optimistic dispatch when the user clicks
      // Allow/Deny (tool_use_id at top level), and the buffered stream
      // event replayed on re-attach (tool_use_id under `data`). Accept
      // either. Clear the panel iff it's still showing the specific
      // request we resolved — the next can_use_tool callback (parallel
      // tool calls) can race the POST response and have already
      // overwritten permissionRequest with a fresh prompt; wiping it
      // unconditionally would leave the agent waiting on an answer the
      // user never sees.
      const tid = action.data?.tool_use_id ?? action.tool_use_id;
      if (state.permissionRequest?.tool_use_id !== tid) {
        return state;
      }
      return { ...state, permissionRequest: null };
    }

    case "turn_complete": {
      const last = state.messages[state.messages.length - 1];
      const wasInterrupted = action.data?.stop_reason === "interrupted";
      // When the user stops mid-turn, tag the partial agent message
      // so the row can render an "(interrupted)" chip. The text shown
      // is whatever made it via text_delta before the interrupt —
      // backend persistence mirrors that.
      const messages =
        last?.type === "agent"
          ? updateLastAgent(state.messages, () => ({
              streaming: false,
              ...(wasInterrupted ? { interrupted: true } : {}),
            }))
          : state.messages;
      // Defensive: if the turn ends with a stale permission prompt
      // showing (e.g. the backend errored after `permission_requested`),
      // clear it so the user isn't left with a frozen panel.
      // Sub-agent label map is per-turn (tool_use_ids are scoped to
      // the turn) so we drop it here too.
      return {
        ...state,
        messages,
        streaming: false,
        turnActive: false,
        compacting: false,
        permissionRequest: null,
        questionRequest: null,
        subagentLabels: {},
      };
    }

    case "error":
      return {
        ...state,
        messages: [
          ...state.messages,
          { type: "error", message: action.data?.message ?? "Something went wrong" },
        ],
        streaming: false,
        turnActive: false,
        compacting: false,
        permissionRequest: null,
        questionRequest: null,
      };

    // ── Review-panel controls ───────────────────────────────────
    case "set_accept_mode":
      return { ...state, acceptMode: action.mode };

    case "dismiss_accept":
      // "Ask a question →" — panel closes. For simulation_spec we queue
      // a prefix for the next sendMessage so the agent knows the
      // user's intent. case_builder and mesh questions go plain (the
      // agent is already in approval-mode context), and the pending
      // pill takes over above the composer (approvalPending stays
      // true).
      return {
        ...state,
        acceptMode: null,
        pendingUserAction:
          state.phase === "case_builder" || state.phase === "mesh"
            ? null
            : "question",
      };

    case "clear_pending_action":
      return { ...state, pendingUserAction: null };

    case "spec_approved":
      // Approval happened server-side and the case_builder kickoff
      // turn is now streaming on the same SSE connection. Render the
      // badge + phase-transition marker, exit review mode, and flip
      // streaming on so subsequent agent events open a fresh bubble.
      return {
        ...state,
        specDraft: null,
        acceptMode: null,
        pendingUserAction: null,
        phase: action.data.phase_to,
        streaming: true,
        messages: [
          ...state.messages,
          { type: "approval_badge", label: "Specification approved" },
          {
            type: "phase_transition",
            from: action.data.phase_from,
            to: action.data.phase_to,
          },
        ],
      };

    case "phase_approved":
      // Phase-advance approval acknowledged by the backend (any phase:
      // case_builder / mesh / improver). The handoff + spec are already
      // on disk, so the backend advances directly: clear the pill /
      // panel and mark `streaming`, then the phase pill flips on the
      // `phase_transitioned` event that follows immediately.
      return {
        ...state,
        acceptMode: null,
        approvalPending: false,
        pendingKind: null,
        pendingUserAction: null,
        streaming: true,
      };

    case "mesh_step_approved":
      // Sub-step approval came through. The backend auto-resumes the
      // agent on the same SSE connection — subsequent events flow
      // into the existing reducer cases. Clear the pill / panel and
      // mark `streaming` so the next text_delta opens a fresh agent
      // bubble.
      return {
        ...state,
        acceptMode: null,
        approvalPending: false,
        pendingKind: null,
        pendingUserAction: null,
        streaming: true,
      };

    case "experiment_approval_approved":
      // Experiment-plan approval acknowledged. Same shape as
      // mesh_step_approved — backend auto-resumes the improver on
      // the same SSE connection.
      return {
        ...state,
        acceptMode: null,
        approvalPending: false,
        pendingKind: null,
        pendingUserAction: null,
        streaming: true,
      };

    case "phase_transitioned": {
      // The actual phase flip — fired immediately after `phase_approved`
      // (the handoff + spec are already on disk, so the backend advances
      // directly). Flips the phase pill and drops the approval badge +
      // phase-transition divider into the chat. Downstream agent events
      // arriving after this point render under the new phase.
      //
      // `downstream_agent_starting` tells us whether the same SSE
      // stream is about to carry a kickoff turn for the new phase. It's
      // always true now (every advance fires a downstream kickoff), so
      // keep `streaming: true` to hold the interrupt button across the
      // divider.
      const labels = {
        case_builder: "Case approved",
        mesh: "Mesh approved",
        improver: "Case approved",
      };
      const label =
        labels[action.data.phase_from] ||
        `${action.data.phase_from} approved`;
      return {
        ...state,
        phase: action.data.phase_to,
        streaming: action.data.downstream_agent_starting === true,
        messages: [
          ...state.messages,
          { type: "approval_badge", label },
          {
            type: "phase_transition",
            from: action.data.phase_from,
            to: action.data.phase_to,
          },
        ],
      };
    }

    default:
      return state;
  }
}

// ── Hook ─────────────────────────────────────────────────────────
export function useAgentStream(
  projectId,
  { onProjectChanged, onFileWritten, onBashCompleted } = {},
) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const abortRef = useRef(null);

  // Latest pendingUserAction, accessible inside async callbacks without
  // closure staleness (reducer state might have updated after render).
  const pendingRef = useRef(null);
  useEffect(() => {
    pendingRef.current = state.pendingUserAction;
  }, [state.pendingUserAction]);

  // Latest pendingKind — same staleness concern; approve actions
  // dispatch to the right endpoint based on which kind raised the
  // pill (e.g. mesh_phase_advance vs improver_phase_advance both
  // route through `approvePhaseAdvance`).
  const pendingKindRef = useRef(null);
  useEffect(() => {
    pendingKindRef.current = state.pendingKind;
  }, [state.pendingKind]);

  // Latest streaming flag, read inside the autonomous-turn poll without
  // closure staleness. The poll skips while a stream is already live.
  const streamingRef = useRef(false);
  useEffect(() => {
    streamingRef.current = state.streaming;
  }, [state.streaming]);

  // Guards against overlapping re-attaches: a silent (no-event-yet) wake-up
  // turn leaves `streaming` false, so without this the poll would re-attach
  // every tick and abort the prior connection.
  const reattachingRef = useRef(false);

  // Latest onProjectChanged — callers don't need to memoize.
  const onProjectChangedRef = useRef(onProjectChanged);
  useEffect(() => {
    onProjectChangedRef.current = onProjectChanged;
  });

  // Latest onFileWritten — fires once per `file_written` SSE event.
  // Side-effect-shaped (toast, tree merge, is-new dot) so we route it
  // outside the reducer.
  const onFileWrittenRef = useRef(onFileWritten);
  useEffect(() => {
    onFileWrittenRef.current = onFileWritten;
  });

  // Latest onBashCompleted — fires after Bash tool calls finish, so the
  // caller can refetch the project file tree (catches mv/cp/rm/mkdir
  // and program outputs like `blockMesh` populating
  // `constant/polyMesh/`, none of which fire the Write/Edit hook).
  // Trailing-edge debounced via the timer below so a burst of parallel
  // Bash calls collapses into a single refetch.
  const onBashCompletedRef = useRef(onBashCompleted);
  useEffect(() => {
    onBashCompletedRef.current = onBashCompleted;
  });

  // Tracks tool ids whose `tool_started` was a file-producing tool —
  // Bash (mv/cp/mkdir, solver/mesher outputs) or the ParaView
  // `save_screenshot` tool (writes a PNG into the project, e.g.
  // Reports/) — so the matching `tool_output` can trigger a quiet
  // `/files` refetch and the new file appears in the sidebar. Lives in
  // a ref so the streamMessage / approveSpec onmessage handlers can
  // mutate without re-rendering.
  const bashIdsRef = useRef(new Set());
  const refreshTimerRef = useRef(null);

  function scheduleBashRefresh() {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      onBashCompletedRef.current?.();
    }, 150);
  }

  // Map an SSE event into Bash-tracking side effects. Called from the
  // onmessage handlers BEFORE the dispatch; safe to no-op on unrelated
  // events.
  function trackBash(eventName, data) {
    if (
      eventName === "tool_started" &&
      (data?.tool === "Bash" || data?.tool === "save_screenshot") &&
      data?.id
    ) {
      bashIdsRef.current.add(data.id);
      return;
    }
    if (eventName === "tool_output" && data?.tool_use_id) {
      if (bashIdsRef.current.delete(data.tool_use_id)) {
        scheduleBashRefresh();
      }
      return;
    }
    if (eventName === "turn_complete") {
      // Defensive: an in-flight Bash whose tool_output never arrived
      // shouldn't leak across turns. Tool ids are turn-scoped anyway.
      bashIdsRef.current.clear();
    }
  }

  // Per-project bookkeeping reset, plus timer cleanup on unmount.
  useEffect(() => {
    bashIdsRef.current.clear();
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [projectId]);

  // Hydrate from history whenever projectId flips. Reset immediately so
  // the UI doesn't flash the previous project's messages in the gap
  // between id change and fetch resolve.
  useEffect(() => {
    dispatch({
      type: "history_loaded",
      messages: [],
      phase: null,
      specDraft: null,
      acceptMode: null,
      approvalPending: false,
      pendingKind: null,
    });
    if (!projectId) return;
    let cancelled = false;
    fetch(`/api/projects/${projectId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((p) => {
        if (cancelled) return;
        const specInReview = p.phase === "simulation_spec" && !!p.spec_draft;
        const caseInReview = p.phase === "case_builder" && !!p.approval_pending;
        const meshInReview = p.phase === "mesh" && !!p.approval_pending;
        dispatch({
          type: "history_loaded",
          messages: buildMessagesFromHistory(p.history ?? []),
          phase: p.phase ?? null,
          specDraft: p.spec_draft || null,
          // Default to AcceptPanel-open on reload when the backend
          // says approval is pending (per plan §4.6 refresh-survival
          // rule). Applies to case_builder + mesh.
          acceptMode:
            specInReview || caseInReview || meshInReview ? "pick" : null,
          approvalPending: !!p.approval_pending,
          pendingKind: p.approval_kind ?? null,
          turnActive: !!p.turn_active,
        });
        // A turn is already running (e.g. we switched back to it): re-attach
        // to watch it live — replay what we missed, then follow. Read-only;
        // the backend drives + persists the turn independently.
        if (!cancelled && p.turn_active) {
          reattachStream(projectId);
        }
      })
      .catch((err) => console.error("history fetch failed:", err));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Abort any in-flight stream on project change or unmount.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, [projectId]);

  // Autonomous-turn pickup. While viewing a project with no live stream,
  // poll for a turn the worker started on its own — a background job /
  // Monitor wake-up re-invoked the agent. When one appears, re-attach to it
  // (same path as project switch-back). Unlike the Claude Code TUI, the
  // browser drops its SSE between turns, so without this poll the wake-up
  // turn stays invisible until the next user message.
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    const id = setInterval(async () => {
      // While we're actively tailing a turn's own SSE, `streaming` already
      // reflects it — skip the poll. (A silent re-attach keeps polling, so
      // the flag below stays fresh even when no events are arriving.)
      if (cancelled || streamingRef.current) return;
      try {
        const r = await fetch(`/api/projects/${projectId}/turn-active`);
        if (!r.ok) return;
        const { turn_active } = await r.json();
        if (cancelled || streamingRef.current) return;
        // Keep the Stop button in sync with the backend even when the turn
        // is silent (background solver) or stalled (dropped connection).
        dispatch({ type: "set_turn_active", value: turn_active });
        if (reattachingRef.current || !turn_active) return;
        reattachingRef.current = true;
        reattachStream(projectId).finally(() => {
          reattachingRef.current = false;
        });
      } catch {
        /* transient — retry next tick */
      }
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [projectId]);

  // ── Internal: POST a message and pump the SSE stream ─────────
  async function streamMessage(displayContent, wireContent) {
    dispatch({ type: "user_sent", content: displayContent });

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await fetchEventSource(`/api/projects/${projectId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: wireContent }),
        signal: ctrl.signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        },
        onmessage(ev) {
          const data = ev.data ? JSON.parse(ev.data) : {};
          trackBash(ev.event, data);
          if (ev.event === "file_written") {
            onFileWrittenRef.current?.(data);
            return;
          }
          dispatch({ type: ev.event, data });
        },
        onerror(err) {
          throw err; // stop auto-retry
        },
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      dispatch({
        type: "error",
        data: { message: err.message ?? String(err) },
      });
    }
  }

  // ── Internal: re-attach to a turn already running for this project ──
  // Used on project switch-back. Tails GET /stream (replay of what was
  // missed + live). The backend drives + persists the turn independently,
  // so this is read-only display. If no turn is active the stream closes
  // immediately and this is a no-op.
  async function reattachStream(pid) {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let started = false;
    try {
      await fetchEventSource(`/api/projects/${pid}/stream`, {
        method: "GET",
        signal: ctrl.signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        },
        onmessage(ev) {
          if (!ev.event) return;
          if (!started) {
            started = true;
            dispatch({ type: "reattach_start" });
          }
          const data = ev.data ? JSON.parse(ev.data) : {};
          trackBash(ev.event, data);
          if (ev.event === "file_written") {
            onFileWrittenRef.current?.(data);
            return;
          }
          dispatch({ type: ev.event, data });
        },
        onerror(err) {
          throw err; // stop auto-retry
        },
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      // No active turn / stream closed — non-fatal.
    }
  }

  // ── Public API ──────────────────────────────────────────────
  async function sendMessage(content) {
    const trimmed = content.trim();
    if (!trimmed || !projectId) return;
    const pa = pendingRef.current;
    const wire = applyUserActionPrefix(trimmed, pa, state.phase, state.pendingKind);
    if (pa) dispatch({ type: "clear_pending_action" });
    await streamMessage(trimmed, wire);
  }

  async function submitFeedback(content) {
    const trimmed = content.trim();
    if (!trimmed || !projectId) return;
    // Close the panel immediately; it'll re-open when the agent re-presents.
    dispatch({ type: "set_accept_mode", mode: null });
    await streamMessage(
      trimmed,
      applyUserActionPrefix(trimmed, "feedback", state.phase, state.pendingKind),
    );
  }

  function openFeedback() {
    dispatch({ type: "set_accept_mode", mode: "feedback" });
  }
  function cancelFeedback() {
    dispatch({ type: "set_accept_mode", mode: "pick" });
  }
  function dismissAcceptPanel() {
    // "Ask a question →" — composer returns, next sendMessage gets
    // the question prefix. Panel re-opens when agent re-presents.
    dispatch({ type: "dismiss_accept" });
  }

  // Stop the agent mid-turn. POSTs /interrupt and lets the backend
  // wrap the stream up itself — the SDK still emits its final
  // ResultMessage so partial text and the session id are persisted
  // normally, and the SSE closes once `turn_complete` arrives. We
  // intentionally don't abort the SSE locally; that would race the
  // backend persistence path.
  async function interrupt() {
    if (!projectId) return;
    try {
      await fetch(`/api/projects/${projectId}/interrupt`, { method: "POST" });
    } catch (err) {
      // Network blip — leave streaming state as-is; the next stream
      // event (or its absence) will resolve UI. No toast: the user
      // already sees the stream still going.
      console.error("interrupt failed:", err);
    }
  }

  // Deny a permission request but pass the user's text as the reason.
  // Agent keeps running (no interrupt); it sees the message as the
  // tool result and can adjust. Mirrors `submitPermission` shape.
  async function submitPermissionDenyFeedback(message) {
    if (!projectId) return;
    const req = state.permissionRequest;
    if (!req) return;
    const toolUseId = req.tool_use_id;
    try {
      const res = await fetch(
        `/api/projects/${projectId}/permission/${toolUseId}/deny-feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      dispatch({ type: "permission_resolved", tool_use_id: toolUseId });
    } catch (err) {
      dispatch({ type: "permission_resolved", tool_use_id: toolUseId });
      dispatch({
        type: "error",
        data: { message: `Permission decision failed: ${err.message ?? err}` },
      });
    }
  }

  async function submitPermission(decision) {
    // decision: "allow" | "deny". Resolves the backend Future and
    // clears the panel. The agent will resume streaming inside the
    // already-open SSE — we don't need to re-open anything here.
    //
    // tool_use_id is captured at click time and forwarded to the
    // reducer so a parallel-tool-call race (next permission_requested
    // overwriting permissionRequest before our POST response lands)
    // doesn't cause us to wipe the new prompt. See the
    // permission_resolved reducer branch.
    if (!projectId) return;
    const req = state.permissionRequest;
    if (!req) return;
    const toolUseId = req.tool_use_id;
    try {
      const res = await fetch(
        `/api/projects/${projectId}/permission/${toolUseId}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      dispatch({ type: "permission_resolved", tool_use_id: toolUseId });
    } catch (err) {
      // Stale id (404) or network blip. Clear the panel only if
      // we're still showing this specific request, so a follow-up
      // prompt isn't accidentally hidden.
      dispatch({ type: "permission_resolved", tool_use_id: toolUseId });
      dispatch({
        type: "error",
        data: { message: `Permission decision failed: ${err.message ?? err}` },
      });
    }
  }

  // Submit AskUserQuestion answers. POSTs the answers map (and the
  // original questions, which the SDK needs to process the tool) to the
  // question route, which resolves the paused Future with an Allow
  // carrying the selections. The agent resumes streaming inside the
  // already-open SSE. tool_use_id is captured at submit time and
  // forwarded to the reducer so a parallel-call race doesn't wipe a
  // fresh prompt. Mirrors submitPermission.
  async function submitQuestionAnswers(answers, response = null) {
    if (!projectId) return;
    const req = state.questionRequest;
    if (!req) return;
    const toolUseId = req.tool_use_id;
    try {
      const res = await fetch(
        `/api/projects/${projectId}/question/${toolUseId}/answer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            questions: req.questions,
            answers,
            response,
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      dispatch({ type: "question_resolved", tool_use_id: toolUseId });
    } catch (err) {
      dispatch({ type: "question_resolved", tool_use_id: toolUseId });
      dispatch({
        type: "error",
        data: { message: `Submitting answers failed: ${err.message ?? err}` },
      });
    }
  }

  async function approveSpec() {
    if (!projectId) return;
    dispatch({ type: "set_accept_mode", mode: "accepted" });

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    // Tracks whether the server's spec_approved event has landed. If
    // the stream errors before that, the phase transition never
    // happened — we restore the AcceptPanel so the user can retry.
    // After it lands, the transition is durable in the DB; a kickoff
    // failure surfaces as an error message but we leave the user in
    // case_builder.
    let approved = false;

    try {
      await fetchEventSource(`/api/projects/${projectId}/approve-spec`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        },
        onmessage(ev) {
          const data = ev.data ? JSON.parse(ev.data) : {};
          trackBash(ev.event, data);
          if (ev.event === "spec_approved") {
            approved = true;
            dispatch({ type: "spec_approved", data });
            // Refresh project metadata (phase pill, file tree, etc.)
            // alongside the streaming kickoff turn.
            onProjectChangedRef.current?.();
            return;
          }
          if (ev.event === "file_written") {
            onFileWrittenRef.current?.(data);
            return;
          }
          dispatch({ type: ev.event, data });
        },
        onerror(err) {
          throw err; // stop auto-retry
        },
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      if (!approved) {
        dispatch({ type: "set_accept_mode", mode: "pick" });
      }
      dispatch({
        type: "error",
        data: { message: `Approve failed: ${err.message ?? err}` },
      });
      throw err;
    }
  }

  // Mesh sub-step approve — SSE, because the backend auto-resumes the
  // mesh agent on the same connection with an injected "Proceed"
  // message. The stream then carries the agent's next turn's events.
  async function approveMeshStep() {
    if (!projectId) return;
    dispatch({ type: "set_accept_mode", mode: "accepted" });

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    // Track whether the server's mesh_step_approved event landed. If
    // the stream errors before that, the approval never registered —
    // restore the AcceptPanel so the user can retry.
    let approved = false;

    try {
      await fetchEventSource(`/api/projects/${projectId}/approve-mesh-step`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        },
        onmessage(ev) {
          const data = ev.data ? JSON.parse(ev.data) : {};
          trackBash(ev.event, data);
          if (ev.event === "mesh_step_approved") {
            approved = true;
            dispatch({ type: "mesh_step_approved", data });
            return;
          }
          if (ev.event === "file_written") {
            onFileWrittenRef.current?.(data);
            return;
          }
          dispatch({ type: ev.event, data });
        },
        onerror(err) {
          throw err;
        },
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      if (!approved) {
        dispatch({ type: "set_accept_mode", mode: "pick" });
      }
      dispatch({
        type: "error",
        data: { message: `Approve failed: ${err.message ?? err}` },
      });
      throw err;
    }
  }

  // Improver experiment approve — SSE, same shape as approveMeshStep
  // (sub-step approval semantics). The backend auto-resumes the
  // improver on the same SSE connection.
  async function approveExperiment() {
    if (!projectId) return;
    dispatch({ type: "set_accept_mode", mode: "accepted" });

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    let approved = false;

    try {
      await fetchEventSource(
        `/api/projects/${projectId}/approve-experiment`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ctrl.signal,
          openWhenHidden: true,
          async onopen(res) {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
          },
          onmessage(ev) {
            const data = ev.data ? JSON.parse(ev.data) : {};
            trackBash(ev.event, data);
            if (ev.event === "experiment_approval_approved") {
              approved = true;
              dispatch({ type: "experiment_approval_approved", data });
              return;
            }
            if (ev.event === "file_written") {
              onFileWrittenRef.current?.(data);
              return;
            }
            dispatch({ type: ev.event, data });
          },
          onerror(err) {
            throw err;
          },
        },
      );
    } catch (err) {
      if (err.name === "AbortError") return;
      if (!approved) {
        dispatch({ type: "set_accept_mode", mode: "pick" });
      }
      dispatch({
        type: "error",
        data: { message: `Approve failed: ${err.message ?? err}` },
      });
      throw err;
    }
  }

  // Phase-advance approve — SSE. The single approval gate for every
  // phase (case_builder / mesh / improver), all routed to
  // /approve-phase-advance. The handoff + spec are already on disk, so
  // the backend streams phase_approved → phase_transitioned (DB flips
  // to the next phase) → the downstream agent's kickoff turn, all on
  // the same connection.
  async function approvePhaseAdvance() {
    if (!projectId) return;
    dispatch({ type: "set_accept_mode", mode: "accepted" });

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    // If the stream errors before phase_approved lands, the approval
    // never registered server-side — restore the AcceptPanel.
    let approved = false;

    try {
      await fetchEventSource(`/api/projects/${projectId}/approve-phase-advance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        },
        onmessage(ev) {
          const data = ev.data ? JSON.parse(ev.data) : {};
          trackBash(ev.event, data);
          if (ev.event === "phase_approved") {
            approved = true;
            dispatch({ type: "phase_approved", data });
            return;
          }
          if (ev.event === "phase_transitioned") {
            dispatch({ type: "phase_transitioned", data });
            onProjectChangedRef.current?.();
            return;
          }
          if (ev.event === "file_written") {
            onFileWrittenRef.current?.(data);
            return;
          }
          dispatch({ type: ev.event, data });
        },
        onerror(err) {
          throw err;
        },
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      if (!approved) {
        dispatch({ type: "set_accept_mode", mode: "pick" });
      }
      dispatch({
        type: "error",
        data: { message: `Approve failed: ${err.message ?? err}` },
      });
      throw err;
    }
  }

  return {
    messages: state.messages,
    streaming: state.streaming,
    turnActive: state.turnActive,
    compacting: state.compacting,
    phase: state.phase,
    specDraft: state.specDraft,
    acceptMode: state.acceptMode,
    approvalPending: state.approvalPending,
    pendingKind: state.pendingKind,
    permissionRequest: state.permissionRequest,
    questionRequest: state.questionRequest,
    sendMessage,
    submitFeedback,
    openFeedback,
    cancelFeedback,
    dismissAcceptPanel,
    approveSpec,
    approveMeshStep,
    approveExperiment,
    approvePhaseAdvance,
    submitPermission,
    submitPermissionDenyFeedback,
    submitQuestionAnswers,
    interrupt,
  };
}
