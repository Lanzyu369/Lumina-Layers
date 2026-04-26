import type { SVGProps } from "react";

const baseProps: SVGProps<SVGSVGElement> = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: false,
};

const sizeClass = "h-4 w-4";

export const ChevronUp = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <polyline points="18 15 12 9 6 15" />
  </svg>
);

export const ChevronDown = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

export const ChevronLeft = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <polyline points="15 18 9 12 15 6" />
  </svg>
);

export const ChevronRight = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <polyline points="9 18 15 12 9 6" />
  </svg>
);
