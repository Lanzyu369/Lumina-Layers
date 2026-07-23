import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from "react";

export type SpacePanDeactivateReason = "keyup" | "blur" | "disabled" | "unmount";

interface UseSpacePanModifierOptions {
  enabled?: boolean;
  onDeactivate?: (reason: SpacePanDeactivateReason) => void;
}

interface SpacePanModifierState {
  isActive: boolean;
  isActiveRef: MutableRefObject<boolean>;
  handlePointerEnter: () => void;
  handlePointerLeave: () => void;
}

function isSpaceKey(event: KeyboardEvent): boolean {
  return event.code === "Space" || event.key === " ";
}

function isInteractiveKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  return ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName);
}

/**
 * Track a hold-Space pan modifier while the pointer is inside one viewport.
 * 仅在指针位于指定预览区域时跟踪按住空格的平移修饰状态。
 */
export function useSpacePanModifier({
  enabled = true,
  onDeactivate,
}: UseSpacePanModifierOptions = {}): SpacePanModifierState {
  const [isActive, setIsActive] = useState(false);
  const isActiveRef = useRef(false);
  const pointerInsideRef = useRef(false);
  const onDeactivateRef = useRef(onDeactivate);
  onDeactivateRef.current = onDeactivate;

  const deactivate = useCallback((reason: SpacePanDeactivateReason) => {
    if (!isActiveRef.current) {
      return;
    }
    isActiveRef.current = false;
    setIsActive(false);
    onDeactivateRef.current?.(reason);
  }, []);

  useEffect(() => {
    if (enabled) {
      return;
    }
    pointerInsideRef.current = false;
    deactivate("disabled");
  }, [deactivate, enabled]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        !isSpaceKey(event)
        || !pointerInsideRef.current
        || isInteractiveKeyboardTarget(event.target)
      ) {
        return;
      }
      event.preventDefault();
      if (isActiveRef.current) {
        return;
      }
      isActiveRef.current = true;
      setIsActive(true);
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (!isSpaceKey(event) || !isActiveRef.current) {
        return;
      }
      event.preventDefault();
      deactivate("keyup");
    };
    const handleBlur = () => deactivate("blur");

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("blur", handleBlur);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);
    };
  }, [deactivate, enabled]);

  useEffect(() => () => {
    pointerInsideRef.current = false;
    if (!isActiveRef.current) {
      return;
    }
    isActiveRef.current = false;
    onDeactivateRef.current?.("unmount");
  }, []);

  const handlePointerEnter = useCallback(() => {
    pointerInsideRef.current = true;
  }, []);
  const handlePointerLeave = useCallback(() => {
    pointerInsideRef.current = false;
  }, []);

  return {
    isActive,
    isActiveRef,
    handlePointerEnter,
    handlePointerLeave,
  };
}
