import { useEffect, useRef } from "react";
import AcceptPanel from "./AcceptPanel.jsx";
import AgentMessage from "./AgentMessage.jsx";
import ApprovalPendingPill from "./ApprovalPendingPill.jsx";
import CompactionDivider from "./CompactionDivider.jsx";
import { BrandMark, StreamlineLoader } from "./icons.jsx";
import Composer from "./Composer.jsx";
import NewSimulationLanding from "./NewSimulationLanding.jsx";
import ParaviewLaunchButton from "./ParaviewLaunchButton.jsx";
import PermissionPanel from "./PermissionPanel.jsx";
import PhaseDivider from "./PhaseDivider.jsx";
import QuestionPanel from "./QuestionPanel.jsx";
import ToastStack from "./ToastStack.jsx";
import UserBubble from "./UserBubble.jsx";

// Per-approval-kind copy for AcceptPanel. simulation_spec uses the
// panel defaults (its first consumer); case_builder + mesh phases
// pick a copy object via the `pendingKind` discriminator the reducer
// tracks alongside `approvalPending`.
const ACCEPT_COPY = {
  case_builder_phase_advance: {
    pickTitle: "Accept this case?",
    feedbackTitle: "Feedback on case",
    feedbackPlaceholder:
      "What would you change? The agent will revise and re-request approval.",
    acceptedLabel: "Case approved",
    yesSub: "begin meshing",
    noSub: "revise and re-request approval",
  },
  mesh_step: {
    pickTitle: "Approve this mesh sub-step?",
    feedbackTitle: "Feedback on mesh sub-step",
    feedbackPlaceholder:
      "What would you change? The agent will revise this sub-step and re-request approval.",
    acceptedLabel: "Sub-step approved · continuing",
    yesSub: "continue with the next sub-task",
    noSub: "revise and re-request approval",
  },
  mesh_phase_advance: {
    pickTitle: "Approve mesh and advance to improvement?",
    feedbackTitle: "Feedback on mesh",
    feedbackPlaceholder:
      "What would you change? The agent will revise the mesh and re-request approval.",
    acceptedLabel: "Mesh approved · advancing to improvement",
    yesSub: "advance to the improvement phase",
    noSub: "revise the mesh",
  },
  improver_experiment: {
    pickTitle: "Approve this experiment plan?",
    feedbackTitle: "Feedback on experiment plan",
    feedbackPlaceholder:
      "What would you change about the plan? The agent will revise and re-request approval.",
    acceptedLabel: "Experiment approved · running",
    yesSub: "run the experiment",
    noSub: "revise the plan and re-request approval",
  },
  improver_phase_advance: {
    pickTitle: "Approve the case and advance to post-processing?",
    feedbackTitle: "Feedback on results",
    feedbackPlaceholder:
      "What would you change? The agent will revise and re-request approval.",
    acceptedLabel: "Case approved · advancing to post-processing",
    yesSub: "advance to the post-processing phase",
    noSub: "iterate further on the case",
  },
};

// Resolve the approve handler for the current approval-pending state.
// The `pendingKind` discriminator wins when set; otherwise we fall
// back to the phase-keyed handler (spec — simulation_spec is the only
// approval flow without a pendingKind).
function pickApprove(stream) {
  if (stream.pendingKind === "mesh_step") return stream.approveMeshStep;
  if (stream.pendingKind === "improver_experiment") return stream.approveExperiment;
  // Every phase-advance gate (case_builder / mesh / improver) routes
  // through approvePhaseAdvance — one endpoint, phase read server-side.
  if (
    stream.pendingKind === "case_builder_phase_advance" ||
    stream.pendingKind === "mesh_phase_advance" ||
    stream.pendingKind === "improver_phase_advance"
  ) return stream.approvePhaseAdvance;
  return stream.approveSpec;
}

// §9.5 phase → pill color/label. Spec = accent, Meshing/Running =
// ochre, Post = sage. The terracotta color is swapped via CSS vars
// when the user picks a different accent, intentionally.
const PHASE_META = {
  simulation_spec: { label: "Simulation specification", color: "terracotta" },
  case_builder: { label: "Case building", color: "ochre" },
  mesh: { label: "Meshing", color: "ochre" },
  improver: { label: "Running", color: "ochre" },
  post_process: { label: "Post-processing", color: "sage" },
};

function phaseStyles(color) {
  if (color === "ochre") {
    return { background: "var(--ochre-tint)", color: "var(--ochre)", dot: "var(--ochre)" };
  }
  if (color === "sage") {
    return { background: "var(--sage-tint)", color: "var(--sage)", dot: "var(--sage)" };
  }
  return {
    background: "var(--terracotta-tint)",
    color: "var(--terracotta)",
    dot: "var(--terracotta)",
  };
}

function formatStartTime(iso) {
  if (!iso) return "";
  const normalised = iso.includes("T") ? iso : iso.replace(" ", "T") + "Z";
  const d = new Date(normalised);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Shared check icon for the approval badge (same stroke/color as the
// AcceptPanel "accepted" mode).
function CheckIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none">
      <path
        d="M2 7l3 3 7-7"
        stroke="var(--sage)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ApprovalBadgeRow({ label = "Approved" }) {
  // Rendered as a sage-tinted row inside an agent message so the brand
  // mark icon still appears on the left — matches the design file's
  // ViewPhase layout.
  return (
    <div className="msg agent">
      <div className="agent-mark">
        <BrandMark size={20} />
      </div>
      <div className="agent-body">
        <div className="accept accept-done">
          <CheckIcon />
          {label}
        </div>
      </div>
    </div>
  );
}

function ChatHeader({ project, inReview, onLaunchParaview }) {
  const phase = PHASE_META[project.phase] ?? PHASE_META.simulation_spec;
  const styles = phaseStyles(phase.color);

  const title = project.name;
  const subtitle = inReview
    ? "Review mode · specification on the right"
    : `Started ${formatStartTime(project.created_at)} · ${project.expertise_level}`;
  const pillText = inReview ? `${phase.label} · review` : phase.label;

  return (
    <div className="chat-top">
      <div>
        <div className="chat-title">{title}</div>
        <div className="chat-title-sub">{subtitle}</div>
      </div>
      <div className="chat-top-right">
        {onLaunchParaview && <ParaviewLaunchButton onLaunch={onLaunchParaview} />}
        <span
          className="chat-phase"
          style={{ background: styles.background, color: styles.color }}
        >
          <span className="phase-dot" style={{ background: styles.dot }} />
          {pillText}
        </span>
      </div>
    </div>
  );
}

function ChatScroll({ messages, compacting }) {
  const ref = useRef(null);
  const atBottomRef = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      atBottomRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (atBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, compacting]);

  return (
    <div className="chat-scroll" ref={ref}>
      <div className="chat-inner">
        {messages.length === 0 && (
          <div className="chat-empty">
            Describe your simulation below to get started.
          </div>
        )}
        {messages.map((m, i) => {
          if (m.type === "user") {
            return <UserBubble key={i}>{m.content}</UserBubble>;
          }
          if (m.type === "agent") {
            return (
              <AgentMessage
                key={i}
                streaming={m.streaming}
                segments={m.segments}
                interrupted={m.interrupted}
              />
            );
          }
          if (m.type === "approval_badge") {
            return <ApprovalBadgeRow key={i} label={m.label} />;
          }
          if (m.type === "phase_transition") {
            return <PhaseDivider key={i} from={m.from} to={m.to} />;
          }
          if (m.type === "compaction") {
            return (
              <CompactionDivider
                key={i}
                preTokens={m.preTokens}
                postTokens={m.postTokens}
              />
            );
          }
          if (m.type === "error") {
            return (
              <div key={i} className="msg error">
                {m.message}
              </div>
            );
          }
          return null;
        })}
        {compacting && (
          <div className="compacting-row">
            <StreamlineLoader size={14} />
            <span>Compacting context…</span>
          </div>
        )}
      </div>
    </div>
  );
}

function ChatView({
  project,
  stream,
  inReview,
  toastNotifications,
  onOpenToast,
  onLaunchParaview,
  onUploadGeometry,
}) {
  const phase = PHASE_META[project.phase] ?? PHASE_META.simulation_spec;
  const showAcceptPanel = stream.acceptMode !== null;
  // Permission gate wins over both AcceptPanel and Composer — the
  // agent is paused on the backend until we click Allow or Deny.
  const showPermissionPanel = stream.permissionRequest !== null;
  // Question gate is a hard pause too (agent parked on AskUserQuestion).
  // Takes top precedence so nothing else can co-render over it.
  const showQuestionPanel = stream.questionRequest !== null;
  // Show the pending pill above the composer when an approval is
  // pending and the user dismissed AcceptPanel via "Ask a question →".
  // Applies to case_builder + mesh (any phase that uses pendingKind).
  const showApprovalPill =
    stream.approvalPending
    && stream.pendingKind != null
    && !showAcceptPanel
    && !showPermissionPanel
    && !showQuestionPanel;
  const onApprove = pickApprove(stream);
  const acceptCopy = ACCEPT_COPY[stream.pendingKind];

  let footer;
  if (showQuestionPanel) {
    footer = (
      <QuestionPanel
        questions={stream.questionRequest.questions}
        onSubmit={(answers) => stream.submitQuestionAnswers(answers)}
      />
    );
  } else if (showPermissionPanel) {
    const req = stream.permissionRequest;
    footer = (
      <PermissionPanel
        tool={req.tool}
        input={req.input}
        agentLabel={req.agentLabel}
        onAllow={() => stream.submitPermission("allow")}
        onDeny={() => stream.submitPermission("deny")}
        onDenyWithFeedback={(msg) => stream.submitPermissionDenyFeedback(msg)}
      />
    );
  } else if (showAcceptPanel) {
    footer = (
      <AcceptPanel
        mode={stream.acceptMode}
        streaming={stream.streaming}
        onAskQuestion={stream.dismissAcceptPanel}
        onOpenFeedback={stream.openFeedback}
        onCancelFeedback={stream.cancelFeedback}
        onSubmitFeedback={stream.submitFeedback}
        onApprove={onApprove}
        copy={acceptCopy}
      />
    );
  } else {
    footer = (
      <>
        {showApprovalPill && (
          <ApprovalPendingPill
            onApprove={onApprove}
            streaming={stream.streaming}
          />
        )}
        <Composer
          onSend={stream.sendMessage}
          onInterrupt={stream.interrupt}
          onUploadGeometry={onUploadGeometry}
          streaming={stream.streaming || stream.turnActive}
          phaseLabel={phase.label}
        />
      </>
    );
  }

  return (
    <div className="chat-col">
      <ChatHeader
        project={project}
        inReview={inReview}
        onLaunchParaview={onLaunchParaview}
      />
      <ToastStack notifications={toastNotifications ?? []} onOpen={onOpenToast} />
      <ChatScroll messages={stream.messages} compacting={stream.compacting} />
      {footer}
    </div>
  );
}

export default function ChatColumn({
  project,
  stream,
  inReview,
  onCreateProject,
  projects = [],
  toastNotifications,
  onOpenToast,
  onLaunchParaview,
  onUploadGeometry,
}) {
  if (!project) {
    return (
      <div className="chat-col">
        <div className="chat-top">
          <div>
            <div className="chat-title">New simulation</div>
            <div className="chat-title-sub">Set up your project</div>
          </div>
        </div>
        <NewSimulationLanding onCreate={onCreateProject} projects={projects} />
      </div>
    );
  }
  // key=project.id so stream state resets cleanly on project switch.
  return (
    <ChatView
      key={project.id}
      project={project}
      stream={stream}
      inReview={inReview}
      toastNotifications={toastNotifications}
      onOpenToast={onOpenToast}
      onLaunchParaview={onLaunchParaview}
      onUploadGeometry={onUploadGeometry}
    />
  );
}
