import { useState } from "react";

export type DebugAction = "modify_restart" | "restart" | "accept" | "stop";

const ACTIONS: Record<
  DebugAction,
  { label: string; hint: string; tone: "primary" | "warning" | "danger" }
> = {
  modify_restart: {
    label: "Modify prompt + config & restart",
    hint: "Worker's changes will be reset; meta-agent rewrites prompt/config from comments before restart.",
    tone: "primary",
  },
  restart: {
    label: "Restart without changes",
    hint: "Worker's changes will be reset; state re-dispatches with the same prompt.",
    tone: "warning",
  },
  accept: {
    label: "Accept & continue",
    hint: "Worker's output is accepted; run continues to the next state.",
    tone: "primary",
  },
  stop: {
    label: "Stop run",
    hint: "Run is stopped. Changes are left in the worktree for inspection.",
    tone: "danger",
  },
};

const toneClasses: Record<"primary" | "warning" | "danger", string> = {
  primary: "bg-blue-600 hover:bg-blue-700 text-white",
  warning: "bg-amber-600 hover:bg-amber-700 text-white",
  danger: "bg-red-600 hover:bg-red-700 text-white",
};

interface ActionButtonProps {
  defaultAction?: DebugAction;
  onSubmit: (action: DebugAction) => void;
  disabled?: boolean;
}

export function ActionButton({
  defaultAction = "modify_restart",
  onSubmit,
  disabled,
}: ActionButtonProps) {
  const [selected, setSelected] = useState<DebugAction>(defaultAction);
  const [open, setOpen] = useState(false);
  const meta = ACTIONS[selected];

  return (
    <div className="flex flex-col items-end gap-1 relative">
      <div className="flex">
        <button
          type="button"
          onClick={() => onSubmit(selected)}
          disabled={disabled}
          className={`px-4 py-2 rounded-l text-sm font-medium ${toneClasses[meta.tone]} disabled:opacity-50`}
        >
          {meta.label}
        </button>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          disabled={disabled}
          className={`px-2 py-2 rounded-r border-l border-white/20 text-sm ${toneClasses[meta.tone]}`}
          aria-label="More actions"
        >
          ▾
        </button>
      </div>
      {open && (
        <div className="absolute top-full mt-1 right-0 bg-white dark:bg-zinc-900 border rounded shadow-lg z-10 min-w-[280px]">
          {(Object.keys(ACTIONS) as DebugAction[]).map((a) => (
            <button
              type="button"
              key={a}
              onClick={() => {
                setSelected(a);
                setOpen(false);
              }}
              className={`block w-full text-left px-4 py-2 text-sm hover:bg-gray-50 dark:hover:bg-zinc-800 ${
                a === selected ? "font-semibold" : ""
              }`}
            >
              {ACTIONS[a].label}
            </button>
          ))}
        </div>
      )}
      <span className="text-xs opacity-60 text-right max-w-[420px]">{meta.hint}</span>
    </div>
  );
}
