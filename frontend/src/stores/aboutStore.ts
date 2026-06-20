import { create } from "zustand"
import { apiErrorToVisibleMessage } from "../api/client"
import { clearCache as clearCacheApi } from "../api/system"
import { tRuntime } from "../i18n/runtime"

export interface AboutState {
  loading: boolean
  notification: { type: "success" | "error"; message: string } | null
}

export interface AboutActions {
  clearCache: () => Promise<void>
  dismissNotification: () => void
}

const DEFAULT_STATE: AboutState = {
  loading: false,
  notification: null,
}

export const useAboutStore = create<AboutState & AboutActions>((set) => ({
  ...DEFAULT_STATE,

  clearCache: async () => {
    set({ loading: true, notification: null })
    try {
      const response = await clearCacheApi()
      const freed =
        response.freed_bytes >= 1024 * 1024
          ? `${(response.freed_bytes / (1024 * 1024)).toFixed(1)} MB`
          : response.freed_bytes >= 1024
            ? `${(response.freed_bytes / 1024).toFixed(1)} KB`
            : `${response.freed_bytes} B`

      set({
        loading: false,
        notification: {
          type: "success",
          message: tRuntime("about_cache_clear_success", {
            deleted_files: response.deleted_files,
            freed,
          }),
        },
      })
    } catch (err) {
      set({
        loading: false,
        notification: {
          type: "error",
          message: apiErrorToVisibleMessage(
            err,
            tRuntime("about_cache_clear_failed"),
          ),
        },
      })
    }

    setTimeout(() => {
      set({ notification: null })
    }, 3000)
  },

  dismissNotification: () => set({ notification: null }),
}))
