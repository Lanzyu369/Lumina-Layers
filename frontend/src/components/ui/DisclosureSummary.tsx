import type { ComponentPropsWithoutRef } from "react";
import DisclosureChevron from "./DisclosureChevron";

export default function DisclosureSummary({ children, className = "", ...props }: ComponentPropsWithoutRef<"summary">) {
  return (
    <summary {...props} className={`disclosure-summary flex cursor-pointer list-none items-center justify-between gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${className}`}>
      <span>{children}</span>
      <DisclosureChevron />
    </summary>
  );
}
