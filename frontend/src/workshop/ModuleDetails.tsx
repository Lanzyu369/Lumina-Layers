import {
  Fragment,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type {
  WorkshopManagerApi,
  WorkshopModuleDetails as WorkshopModuleDetailsData,
} from "../api/workshop";
import Button from "../components/ui/Button";
import { StatusBanner } from "../components/ui/panelPrimitives";
import { useI18n } from "../i18n/context";

interface ModuleDetailsProps {
  detailsUrl: string;
  api: WorkshopManagerApi;
  onClose(): void;
}

function safeLink(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

function inlineMarkdown(value: string): ReactNode[] {
  const tokens =
    /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^\s)]+\))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(tokens)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      nodes.push(value.slice(cursor, index));
    }
    const token = match[0];
    const key = `${index}-${token.length}`;
    if (token.startsWith("**")) {
      nodes.push(
        <strong key={key} className="font-semibold text-slate-900 dark:text-slate-50">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`")) {
      nodes.push(
        <code
          key={key}
          className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[0.92em] dark:bg-slate-800"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      const href = parts ? safeLink(parts[2]) : null;
      nodes.push(
        href === null ? (
          <Fragment key={key}>{token}</Fragment>
        ) : (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-blue-600 underline decoration-blue-300 underline-offset-2 dark:text-blue-300"
          >
            {parts?.[1]}
          </a>
        ),
      );
    }
    cursor = index + token.length;
  }
  if (cursor < value.length) {
    nodes.push(value.slice(cursor));
  }
  return nodes;
}

function MarkdownDocument({ source }: { source: string }) {
  const blocks = useMemo(() => {
    const result: ReactNode[] = [];
    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    let inCodeFence = false;
    let codeLines: string[] = [];
    let paragraph: string[] = [];

    const flushParagraph = () => {
      if (paragraph.length === 0) {
        return;
      }
      const text = paragraph.join(" ");
      result.push(
        <p
          key={`p-${result.length}`}
          className="text-sm leading-6 text-slate-700 dark:text-slate-200"
        >
          {inlineMarkdown(text)}
        </p>,
      );
      paragraph = [];
    };

    const flushCode = () => {
      result.push(
        <pre
          key={`code-${result.length}`}
          className="overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-5 text-slate-100"
        >
          <code>{codeLines.join("\n")}</code>
        </pre>,
      );
      codeLines = [];
    };

    for (const line of lines) {
      if (line.startsWith("```")) {
        flushParagraph();
        if (inCodeFence) {
          flushCode();
        }
        inCodeFence = !inCodeFence;
        continue;
      }
      if (inCodeFence) {
        codeLines.push(line);
        continue;
      }
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if (heading) {
        flushParagraph();
        const level = heading[1].length;
        const content = inlineMarkdown(heading[2]);
        const className =
          level <= 2
            ? "text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50"
            : "text-base font-semibold text-slate-900 dark:text-slate-50";
        result.push(
          level === 1 ? (
            <h1 key={`h-${result.length}`} className={className}>
              {content}
            </h1>
          ) : level === 2 ? (
            <h2 key={`h-${result.length}`} className={className}>
              {content}
            </h2>
          ) : (
            <h3 key={`h-${result.length}`} className={className}>
              {content}
            </h3>
          ),
        );
        continue;
      }
      const listItem = /^\s*[-*]\s+(.+)$/.exec(line);
      if (listItem) {
        flushParagraph();
        result.push(
          <ul
            key={`list-${result.length}`}
            className="list-disc pl-5 text-sm leading-6 text-slate-700 dark:text-slate-200"
          >
            <li>{inlineMarkdown(listItem[1])}</li>
          </ul>,
        );
        continue;
      }
      if (line.trim() === "") {
        flushParagraph();
      } else {
        paragraph.push(line);
      }
    }
    flushParagraph();
    if (inCodeFence || codeLines.length > 0) {
      flushCode();
    }
    return result;
  }, [source]);

  return <div className="flex flex-col gap-3">{blocks}</div>;
}

export function ModuleDetails({
  detailsUrl,
  api,
  onClose,
}: ModuleDetailsProps) {
  const { t } = useI18n();
  const [details, setDetails] =
    useState<WorkshopModuleDetailsData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDetails(null);
    setFailed(false);
    void api
      .fetchDetails(detailsUrl)
      .then((result) => {
        if (!cancelled) {
          setDetails(result);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, detailsUrl]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("workshop.manager.details")}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section className="panel-section flex max-h-[88vh] w-full max-w-3xl flex-col gap-4 overflow-hidden rounded-[28px] p-5 shadow-2xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            {t("workshop.manager.details")}
          </h2>
          <Button
            label={t("workshop.manager.close")}
            variant="secondary"
            size="sm"
            onClick={onClose}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-auto pr-1">
          {failed ? (
            <StatusBanner tone="error">
              {t("workshop.manager.detailsError")}
            </StatusBanner>
          ) : details === null ? (
            <p role="status" className="text-sm text-slate-500 dark:text-slate-400">
              {t("workshop.manager.loading")}
            </p>
          ) : (
            <div className="flex flex-col gap-6">
              <MarkdownDocument source={details.readme_markdown} />
              {details.gallery_urls.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {details.gallery_urls.map((url) => (
                    <img
                      key={url}
                      src={url}
                      alt=""
                      loading="lazy"
                      className="w-full rounded-2xl border border-[color:var(--surface-outline)]"
                    />
                  ))}
                </div>
              ) : null}
              <details className="rounded-2xl border border-[color:var(--surface-outline)] p-4">
                <summary className="cursor-pointer text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {t("workshop.manager.license")}
                </summary>
                <pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-600 dark:text-slate-300">
                  {details.license_text}
                </pre>
              </details>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default ModuleDetails;
