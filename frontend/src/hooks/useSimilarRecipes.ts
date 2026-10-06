/**
 * Fetch printable recipes closest to a reference colour for the Color Workspace.
 * 为「颜色工作台」获取与参考色最接近的可打印配方。
 *
 * Requests are debounced so dragging a colour picker does not flood the
 * backend, and every superseded request is aborted so a late response can
 * never overwrite the suggestions for a newer colour.
 * 请求带防抖，拖动取色器时不会连续打满后端；旧请求会被中止，迟到的响应
 * 不会覆盖较新颜色的推荐结果。
 */

import { useEffect, useState } from "react";
import { fetchSimilarRecipes } from "../api/converter";
import type { SimilarRecipeItem } from "../api/types";

export const SIMILAR_RECIPES_LIMIT = 12;
const SIMILAR_RECIPES_DEBOUNCE_MS = 200;

export type SimilarRecipesStatus = "idle" | "loading" | "ready" | "error";

export interface SimilarRecipesState {
  status: SimilarRecipesStatus;
  /** Suggestions for the current request only; never those of an older colour. */
  items: SimilarRecipeItem[];
}

const EMPTY_ITEMS: SimilarRecipeItem[] = [];

/**
 * @param sessionId Active converter session, or ``null`` before preview.
 * @param referenceHex ``rrggbb`` / ``#rrggbb`` colour to match, or ``null``.
 * @param refreshKey Changes whenever the session's LUT content may differ
 *   (for example after a new preview), forcing a refetch for the same colour.
 */
export function useSimilarRecipes(
  sessionId: string | null,
  referenceHex: string | null,
  refreshKey: string | null,
): SimilarRecipesState {
  const normalized = normalizeReferenceHex(referenceHex);
  const requestKey = sessionId && normalized ? `${sessionId}|${normalized}|${refreshKey ?? ""}` : null;
  const [result, setResult] = useState<{ key: string; state: SimilarRecipesState } | null>(null);

  useEffect(() => {
    if (!requestKey || !sessionId || !normalized) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      fetchSimilarRecipes(
        { session_id: sessionId, target_color: normalized, limit: SIMILAR_RECIPES_LIMIT },
        controller.signal,
      )
        .then((response) => {
          if (controller.signal.aborted) return;
          setResult({ key: requestKey, state: { status: "ready", items: response.items } });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ key: requestKey, state: { status: "error", items: EMPTY_ITEMS } });
        });
    }, SIMILAR_RECIPES_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [requestKey, sessionId, normalized]);

  if (!requestKey) return { status: "idle", items: EMPTY_ITEMS };
  if (result?.key !== requestKey) return { status: "loading", items: EMPTY_ITEMS };
  return result.state;
}

/** Normalise ``rrggbb`` / ``#RRGGBB`` to ``#rrggbb``; invalid input → ``null``. */
export function normalizeReferenceHex(value: string | null): string | null {
  if (!value) return null;
  const digits = value.trim().replace(/^#/, "").toLowerCase();
  return /^[0-9a-f]{6}$/.test(digits) ? `#${digits}` : null;
}
