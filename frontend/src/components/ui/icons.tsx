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

export const XIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export const ActivityIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
);

export const MaximizeIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M8 3H5a2 2 0 0 0-2 2v3" />
    <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
    <path d="M3 16v3a2 2 0 0 0 2 2h3" />
    <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
  </svg>
);

export const MinimizeIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M8 3v3a2 2 0 0 1-2 2H3" />
    <path d="M21 8h-3a2 2 0 0 1-2-2V3" />
    <path d="M3 16h3a2 2 0 0 1 2 2v3" />
    <path d="M16 21v-3a2 2 0 0 1 2-2h3" />
  </svg>
);

export const CameraIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
    <circle cx="12" cy="13" r="3" />
  </svg>
);

export const HelpCircleIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <circle cx="12" cy="12" r="10" />
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);
