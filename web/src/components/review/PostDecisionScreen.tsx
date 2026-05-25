import type { DebugAction } from "./ActionButton";

interface PostDecisionScreenProps {
  runId: string;
  issueId: string;
  state: string;
  action: DebugAction;
}

const ACTION_PAST_TENSE: Record<DebugAction, string> = {
  modify_restart: "modify prompts & configs → restart step",
  modify_continue: "modify prompts & configs → continue",
  restart: "restart without changes",
  accept: "accept & continue",
  stop: "stop run",
};

export function PostDecisionScreen({
  runId,
  issueId,
  state,
  action,
}: PostDecisionScreenProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen text-center px-8 gap-3">
      <div className="text-3xl">&#10003;</div>
      <h1 className="text-2xl font-semibold">Decision dispatched</h1>
      <p className="opacity-70 max-w-md">
        Chose <strong>{ACTION_PAST_TENSE[action]}</strong> for{" "}
        <code className="text-sm bg-gray-100 dark:bg-zinc-800 px-1 rounded">{runId}</code>{" "}
        at state{" "}
        <code className="text-sm bg-gray-100 dark:bg-zinc-800 px-1 rounded">{state}</code>.
        Return to your terminal — the orca host will pick up from here.
      </p>
      <p className="text-sm opacity-50 mt-4">Issue: {issueId}</p>
    </div>
  );
}
