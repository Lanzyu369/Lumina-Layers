/**
 * AlignedNavStrip - Places one navigation strip inside its row.
 * 在所在行内摆放一条导航标签条。
 *
 * Centered alignment puts a flex spacer on each side so the strip sits on
 * the row's axis moved by `centerShift`; when one side runs out of room only
 * that spacer shrinks, so the strip stops at the row edge instead of
 * overflowing it. Left alignment hides the spacers and leaves placement to
 * the row. The spacers always render so that switching alignment keeps the
 * same strip mounted, with its scroll position and focus.
 * 居中时在两侧各放一个弹性占位，使标签条位于所在行中线并按 centerShift 偏移；某侧
 * 空间不足时只收缩该侧占位，标签条停在行边缘而不会越界。居左时隐藏占位，由所在行
 * 从起点排布。占位始终渲染，切换对齐时标签条不会重新挂载，滚动位置和焦点得以保留。
 */
import type { CSSProperties, ReactNode } from "react";
import type { HeaderNavAlignment } from "../../stores/settingsStore";

const HIDDEN_SPACER_STYLE: CSSProperties = { display: "none" };

function spacerStyle(
  alignment: HeaderNavAlignment,
  side: "start" | "end",
  centerShift: string,
): CSSProperties {
  if (alignment === "left") {
    return HIDDEN_SPACER_STYLE;
  }
  const factor = side === "start" ? 2 : -2;
  return {
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: `max(0px, calc(${factor} * (${centerShift})))`,
  };
}

interface AlignedNavStripProps {
  alignment: HeaderNavAlignment;
  /** CSS length; positive values move the strip towards the row end. */
  centerShift: string;
  children: ReactNode;
}

export default function AlignedNavStrip({
  alignment,
  centerShift,
  children,
}: AlignedNavStripProps) {
  return (
    <>
      <span aria-hidden="true" style={spacerStyle(alignment, "start", centerShift)} />
      {children}
      <span aria-hidden="true" style={spacerStyle(alignment, "end", centerShift)} />
    </>
  );
}
