import { useState, useEffect, useCallback, useMemo } from "react";
import { cx } from "./panelPrimitives";

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  unit?: string;
  tooltip?: string;
  displayDecimals?: number;
  minInputWidthCh?: number;
}

export default function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled = false,
  unit,
  tooltip,
  displayDecimals,
  minInputWidthCh,
}: SliderProps) {
  // 输入框的本地文本状态，编辑时不立即同步外部 value
  const [inputText, setInputText] = useState(() => formatValue(value, step, displayDecimals));
  const [isFocused, setIsFocused] = useState(false);

  // 外部 value 变化时，如果输入框没有焦点，同步显示
  useEffect(() => {
    if (!isFocused) {
      setInputText(formatValue(value, step, displayDecimals));
    }
  }, [value, step, displayDecimals, isFocused]);

  const clampAndRound = useCallback(
    (num: number) => {
      // Clamp into [min, max] and round to the display precision. We do NOT
      // re-anchor the value to a step grid based at 0: the native
      // `<input type="range">` already anchors its step grid at `min`, which
      // yields values like 0.2, 0.28, 0.36... for min=0.2/step=0.08. Forcing
      // these onto a 0-anchored grid would bump every drag emission up by
      // half a step (e.g. 1.16 → 1.20, 1.24 → 1.28), making users feel the
      // slider "auto-adds 0.08" every time they release it.
      // 只做 [min, max] 夹紧并按显示精度取整。不再把值重新对齐到以 0 为锚点
      // 的 step 网格：原生 `<input type="range">` 自身以 `min` 为锚点（例如
      // min=0.2/step=0.08 会发出 0.2、0.28、0.36…）。若强制对齐到 0 锚点，
      // 每次拖动释放都会把值向上平移半格（1.16→1.20、1.24→1.28），用户会
      // 感觉"一放手就自动加 0.08"。
      const clamped = Math.min(max, Math.max(min, num));
      const decimals = getStepDecimals(step);
      return parseFloat(clamped.toFixed(decimals));
    },
    [min, max, step],
  );

  const commitValue = useCallback(
    (text: string) => {
      const num = parseFloat(text);
      if (isNaN(num)) {
        // 无效输入，恢复为当前值
        setInputText(formatValue(value, step, displayDecimals));
        return;
      }
      // Text input is the precise-entry path: clamp to [min, max] and round
      // to the display precision. Same treatment as range drag — see
      // `clampAndRound` above.
      // 文本框同样只做 [min, max] 夹紧与显示精度圆整，路径与滑条拖动一致。
      const clamped = Math.min(max, Math.max(min, num));
      const decimals = getDisplayDecimals(step, displayDecimals);
      const final = parseFloat(clamped.toFixed(decimals));
      onChange(final);
      setInputText(formatValue(final, step, displayDecimals));
    },
    [value, step, min, max, onChange, displayDecimals],
  );

  const handleBlur = () => {
    setIsFocused(false);
    commitValue(inputText);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      commitValue(inputText);
      (e.target as HTMLInputElement).blur();
    } else if (e.key === "Escape") {
      setInputText(formatValue(value, step, displayDecimals));
      (e.target as HTMLInputElement).blur();
    }
  };

  // 计算输入框宽度：根据 max 值的字符数 + unit
  const formattedCurrentValue = useMemo(
    () => formatValue(value, step, displayDecimals),
    [value, step, displayDecimals],
  );

  const inputChars = Math.max(
    formatValue(max, step, displayDecimals).length,
    formatValue(min, step, displayDecimals).length,
    formattedCurrentValue.length,
    inputText.length,
    minInputWidthCh ?? 6,
  );
  const inputWidth = `${inputChars + 1}ch`;

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
          <span title={tooltip}>{label}</span>
        </label>
      )}
      <div className="flex items-center gap-2 rounded-2xl border border-slate-200/80 bg-slate-100/70 px-2 py-1.5 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-900/48">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          aria-label={label}
          onChange={(e) => onChange(clampAndRound(Number(e.target.value)))}
          className={cx(
            "slider-track min-w-0 flex-1 appearance-none cursor-pointer rounded-full accent-blue-500 transition-all duration-200",
            "h-1.5 bg-slate-200 dark:bg-slate-700",
            "focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45"
          )}
        />
        <div className="flex items-center shrink-0">
          <input
            type="text"
            inputMode="decimal"
            value={inputText}
            disabled={disabled}
            onChange={(e) => setInputText(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            style={{ width: inputWidth }}
            className="rounded-lg border border-slate-200/80 bg-slate-100/90 px-1.5 py-1 text-center text-sm tabular-nums text-slate-700 shadow-[var(--shadow-control)] focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-400/20 disabled:cursor-not-allowed disabled:opacity-45 dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100"
            aria-label={`${label} value`}
          />
          {unit && (
            <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500">
              {unit}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/** 根据显示精度格式化数值 */
function formatValue(val: number, step: number, displayDecimals?: number): string {
  const decimals = getDisplayDecimals(step, displayDecimals);
  return val.toFixed(decimals);
}

/** 获取 step 的小数位数 */
function getStepDecimals(step: number): number {
  const s = step.toString();
  const dot = s.indexOf(".");
  return dot === -1 ? 0 : s.length - dot - 1;
}

/** 获取输入框显示所需的小数位数 */
function getDisplayDecimals(step: number, displayDecimals?: number): number {
  return displayDecimals ?? getStepDecimals(step);
}
