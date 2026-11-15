import * as Dialog from "@radix-ui/react-dialog";
import * as RTooltip from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
const VARIANT: Record<Variant, string> = {
  primary: "bg-sky-600 hover:bg-sky-500 text-white",
  secondary: "bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700",
  ghost: "hover:bg-slate-800 text-slate-300",
  danger: "bg-red-700/80 hover:bg-red-600 text-white",
  success: "bg-emerald-600 hover:bg-emerald-500 text-white",
};

export function Button({ variant = "secondary", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...p}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-40",
        VARIANT[variant],
        className,
      )}
    />
  );
}

export function Badge({ className, children }: { className?: string; children: ReactNode }) {
  return <span className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium", className)}>{children}</span>;
}

export function Panel({ title, right, children, className }: { title: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border border-slate-800 bg-slate-900/60", className)}>
      <header className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h2>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  if (!content) return <>{children}</>;
  return (
    <RTooltip.Root delayDuration={200}>
      <RTooltip.Trigger asChild>
        <span className="inline-flex">{children}</span>
      </RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content sideOffset={6} className="z-50 max-w-xs rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200 shadow-lg">
          {content}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

export function Drawer({ open, onOpenChange, title, children }: { open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; children: ReactNode }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content className="fixed right-0 top-0 z-50 flex h-full w-[min(640px,95vw)] flex-col border-l border-slate-700 bg-slate-950 shadow-2xl focus:outline-none">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <Dialog.Title className="text-sm font-semibold text-slate-100">{title}</Dialog.Title>
            <Dialog.Close aria-label="Close" className="rounded p-1 text-slate-400 hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-sky-400">
              <X size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Details</Dialog.Description>
          <div className="flex-1 overflow-y-auto p-4 text-sm">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Confirm({
  open, onOpenChange, title, body, confirmLabel, onConfirm, variant = "danger",
}: { open: boolean; onOpenChange: (o: boolean) => void; title: string; body: ReactNode; confirmLabel: string; onConfirm: () => void; variant?: Variant }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content className="fixed left-1/2 top-1/3 z-50 w-[420px] -translate-x-1/2 rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-2xl">
          <Dialog.Title className="mb-2 text-base font-semibold text-slate-100">{title}</Dialog.Title>
          <Dialog.Description asChild>
            <div className="mb-4 text-sm text-slate-300">{body}</div>
          </Dialog.Description>
          <div className="flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost">Cancel</Button>
            </Dialog.Close>
            <Button variant={variant} onClick={() => { onConfirm(); onOpenChange(false); }}>{confirmLabel}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-sm text-slate-500">{children}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-slate-800/70 motion-reduce:animate-none", className)} />;
}
