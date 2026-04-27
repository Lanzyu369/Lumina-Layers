import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface AccordionProps {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export default function Accordion({
  title,
  defaultOpen = false,
  children,
}: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-slate-200 dark:border-slate-700">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between py-3 text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
      >
        <span>{title}</span>
        <motion.svg
          animate={{ rotate: open ? 90 : 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
          className="h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="9 18 15 12 9 6" />
        </motion.svg>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", bounce: 0, duration: 0.4 }}
            className="overflow-hidden"
          >
            <div className="pb-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
