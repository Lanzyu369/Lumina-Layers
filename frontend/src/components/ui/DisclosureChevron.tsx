/** Shared indicator for expandable content; dropdown selectors keep their own affordance. */
export default function DisclosureChevron({ expanded = false }: { expanded?: boolean }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round"
      className={`disclosure-chevron h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 motion-reduce:transition-none dark:text-slate-400 ${expanded ? "rotate-90" : ""}`}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}
