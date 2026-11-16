import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { ArrowLeft, Download, Printer } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useReport } from "@/api/queries";
import { ApiError } from "@/api/client";
import { Button, Skeleton } from "@/components/ui";
import { useI18n } from "@/i18n";

const SECTIONS = ["Anomaly overview", "Anomaly metrics", "Timeline", "Key evidence", "Candidate causes", "Verification steps executed",
  "Impact of new evidence on judgment", "Suspected affected product scope", "Recommended follow-up actions", "Open questions and limitations"];

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9 -]/g, "").replace(/ /g, "-");
const schema = { ...defaultSchema, clobberPrefix: "" };

export default function ReportPage() {
  const { id = "" } = useParams();
  const r = useReport(id);
  const { t, lang } = useI18n();
  const md = r.data?.markdown ?? "";
  const present = SECTIONS.filter((s, i) => md.includes(`## ${i + 1}. ${s}`));
  const go = (anchor: string) => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth" });
  return (
    <div className="report-page min-h-screen bg-slate-950 text-slate-200 print:bg-white print:text-black">
      <header className="no-print sticky top-0 z-10 flex items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-6 py-3">
        <Link to={-1 as unknown as string} className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200"><ArrowLeft size={14} /> {t("Workspace")}</Link>
        <h1 className="text-sm font-semibold">{t("Investigation Report")} · {id}</h1>
        <span className="rounded border border-sky-500/50 px-1.5 text-[11px] text-sky-300">{t("SIMULATION")}</span>
        <div className="ml-auto flex gap-2">
          <a href={`/api/cases/${id}/report.md`} download><Button><Download size={14} /> {t("Download Markdown")}</Button></a>
          <Button onClick={() => window.print()}><Printer size={14} /> {t("Print / Save as PDF")}</Button>
        </div>
      </header>
      <div className="mx-auto flex max-w-6xl gap-6 px-6 py-6">
        <nav className="no-print sticky top-16 hidden h-fit w-56 shrink-0 lg:block" aria-label="Report sections">
          <ol className="space-y-1 text-xs">
            {present.map((s) => {
              const i = SECTIONS.indexOf(s) + 1;
              return <li key={s}><button className="text-left text-slate-400 hover:text-sky-300" onClick={() => go(slug(`${i}. ${s}`))}>{i}. {s}</button></li>;
            })}
          </ol>
          {r.data && present.length !== 10 && <p className="mt-2 text-[11px] text-slate-500">{t("Short-form report")} ({present.length} {t("sections")}).</p>}
          {lang === "zh" && <p className="mt-2 text-[11px] text-slate-500">{t("Report content is generated in English.")}</p>}
        </nav>
        <article className="report-md min-w-0 flex-1">
          {r.isLoading && <Skeleton className="h-96" />}
          {r.error && <p className="text-red-400">{(r.error as ApiError).message}</p>}
          {r.data && (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeSlug, [rehypeSanitize, schema]]}
              components={{
                a: ({ href, children }) => {
                  if (href?.startsWith("#")) return <a href={href} onClick={(e) => { e.preventDefault(); go(href.slice(1)); }} className="text-sky-400 hover:underline">{children}</a>;
                  if (href && /^https?:\/\//.test(href)) return <a href={href} target="_blank" rel="noreferrer" className="text-sky-400">{children}</a>;
                  return <span>{children}</span>;
                },
              }}
            >
              {md}
            </ReactMarkdown>
          )}
        </article>
      </div>
    </div>
  );
}
