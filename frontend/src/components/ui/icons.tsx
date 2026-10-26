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

export const ActivityIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
);

export const BarChartIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <line x1="12" y1="20" x2="12" y2="10" />
    <line x1="18" y1="20" x2="18" y2="4" />
    <line x1="6" y1="20" x2="6" y2="16" />
  </svg>
);

export const StopwatchIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <circle cx="12" cy="13" r="8" />
    <path d="M12 9v4l2.5 2.5" />
    <path d="M9 2h6" />
    <path d="M12 2v3" />
    <path d="M18.4 6.6l1.4-1.4" />
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

export const InfoIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="16" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12.01" y2="8" />
  </svg>
);

export const CubeIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
    <path d="M3.3 7 12 12l8.7-5" />
    <path d="M12 22V12" />
  </svg>
);

export const EyeIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export const EyeOffIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M3 3l18 18" />
    <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
    <path d="M9.9 5.2A10.6 10.6 0 0 1 12 5c6.5 0 10 7 10 7a18.5 18.5 0 0 1-2.1 3.1" />
    <path d="M6.6 6.6C3.7 8.5 2 12 2 12s3.5 7 10 7a9.8 9.8 0 0 0 4.2-.9" />
  </svg>
);

export const MousePointerIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M4 3l7.5 17 2.1-7.1L20 10 4 3z" />
  </svg>
);

export const MenuIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <line x1="4" y1="7" x2="20" y2="7" />
    <line x1="4" y1="12" x2="20" y2="12" />
    <line x1="4" y1="17" x2="20" y2="17" />
  </svg>
);

export const MoveIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M12 2v20" />
    <path d="M2 12h20" />
    <path d="M12 2l3 3" />
    <path d="M12 2L9 5" />
    <path d="M12 22l3-3" />
    <path d="M12 22l-3-3" />
    <path d="M2 12l3 3" />
    <path d="M2 12l3-3" />
    <path d="M22 12l-3 3" />
    <path d="M22 12l-3-3" />
  </svg>
);

export const RotateCwIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M21 12a9 9 0 1 1-2.64-6.36" />
    <path d="M21 3v6h-6" />
  </svg>
);

export const ExpandIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M15 3h6v6" />
    <path d="M9 21H3v-6" />
    <path d="M21 3l-7 7" />
    <path d="M3 21l7-7" />
  </svg>
);

export const FlipVerticalIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M3 7h18" />
    <path d="M3 17h18" />
    <path d="M12 3v4" />
    <path d="M12 21v-4" />
    <path d="M8 11l4-4 4 4" />
    <path d="M8 13l4 4 4-4" />
  </svg>
);

export const HelpCircleIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <circle cx="12" cy="12" r="10" />
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

export const HistoryIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <path d="M3 12a9 9 0 1 0 2.64-6.36" />
    <path d="M3 3v6h6" />
    <path d="M12 7v5l3 2" />
  </svg>
);

export const XIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} className={sizeClass} {...props}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);
