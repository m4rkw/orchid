import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Dark-styled markdown body; styles live under the `.md` class in index.css. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
