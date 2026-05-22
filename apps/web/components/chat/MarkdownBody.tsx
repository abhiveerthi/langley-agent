"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

type Size = "sm" | "xs";

interface MarkdownBodyProps {
  content: string;
  size?: Size;
  className?: string;
}

// Wrap tables in a horizontally-scrolling container. An 80–85% chat bubble
// can't fit a 5-column table at any zoom level, so let wide tables scroll
// instead of squishing every cell into a vertical strip.
const components: Components = {
  table: ({ node: _node, ...props }) => (
    <div className="not-prose my-3 w-full overflow-x-auto rounded-md border border-border">
      <table
        {...props}
        className="w-full border-collapse text-left text-xs [&_td]:border-t [&_td]:border-border [&_td]:px-3 [&_td]:py-1.5 [&_th]:border-b [&_th]:border-border [&_th]:bg-muted [&_th]:px-3 [&_th]:py-1.5 [&_th]:font-semibold"
      />
    </div>
  ),
  // Inline code: subtle pill; block code: prose-pre handles the wrap.
  code: ({ node: _node, className, children, ...props }) => {
    const isBlock = /language-/.test(className || "");
    if (isBlock) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded bg-muted px-1.5 py-0.5 text-[0.85em] font-mono before:content-none after:content-none"
        {...props}
      >
        {children}
      </code>
    );
  },
};

/**
 * Single chat markdown renderer. Backed by `prose` from
 * `@tailwindcss/typography` (registered as a `@plugin` in `globals.css`).
 * Both the full-page chat bubble and the per-agent MiniChat panel render
 * through this — keep typography tuning in one place to prevent drift.
 *
 * `size="sm"` for full-page bubbles, `size="xs"` for the cramped MiniChat
 * floating panel.
 */
export function MarkdownBody({ content, size = "sm", className }: MarkdownBodyProps) {
  return (
    <div
      className={cn(
        "prose prose-invert max-w-none",
        size === "sm" ? "prose-sm" : "prose-sm text-xs",
        "leading-relaxed",
        "prose-p:my-2.5 prose-p:leading-relaxed",
        "prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold",
        "prose-h1:text-base prose-h2:text-sm prose-h3:text-sm",
        "prose-ul:my-2.5 prose-ol:my-2.5 prose-li:my-1 prose-li:marker:text-muted-foreground",
        "prose-hr:my-4 prose-hr:border-border",
        "prose-blockquote:my-3 prose-blockquote:border-l-2 prose-blockquote:border-border prose-blockquote:pl-3 prose-blockquote:text-muted-foreground prose-blockquote:not-italic",
        "prose-pre:my-3 prose-pre:bg-muted prose-pre:border prose-pre:border-border",
        "prose-a:text-primary prose-a:underline-offset-2 hover:prose-a:text-primary-hover",
        "prose-strong:text-foreground",
        // Trim the first/last child margin so the bubble's own padding owns
        // the outer spacing — otherwise content floats away from the edges.
        "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        className
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
