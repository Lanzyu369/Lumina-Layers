const INTERNAL_ROUTE_RE =
  /(?:^|[\s"'(:=\[{,])\/(?:api|convert|extractor|lut|single-stage|feedback|files|materials|material-sync|vectorizer|calibration|settings|system)(?=$|[/?#\s"'.,;:)\]}])/i;

const LOCAL_PATH_RE =
  /(?:^|[\s"'(:=\[{,])(?:\/(?:users|private|tmp|var|home|volumes|opt|mnt|etc)\b|~\/|[a-z]:[\\/]|\\\\)/i;

const FILE_URL_RE = /\bfile:\/\/\S+/i;
const HTTP_URL_RE = /\bhttps?:\/\/\S+/i;
const TRANSPORT_ERROR_RE = /\b(?:axioserror|traceback|stack trace|exception|permission denied)\b/i;
const BROWSER_ERROR_CODE_RE = /\bERR_[A-Z0-9_]+\b/i;
const GENERIC_HTTP_STATUS_RE =
  /\b(?:request\s+failed\s+with\s+status\s+code|http(?:\s+error)?|status(?:\s+code)?|error)\s*[3-5]\d{2}\b/i;

export function isUnsafeVisibleErrorText(value: string): boolean {
  const text = value.trim();
  if (!text) {
    return false;
  }
  return (
    LOCAL_PATH_RE.test(text) ||
    FILE_URL_RE.test(text) ||
    HTTP_URL_RE.test(text) ||
    INTERNAL_ROUTE_RE.test(text) ||
    TRANSPORT_ERROR_RE.test(text) ||
    BROWSER_ERROR_CODE_RE.test(text) ||
    GENERIC_HTTP_STATUS_RE.test(text)
  );
}
