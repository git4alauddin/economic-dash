import { formatDate, MISSING, safeSourceUrl } from "../../ui/format";
import type { AsOfDate, SourceReference } from "../../ui/types";

export default function SourceAsOf({ sources, asOf }: { sources: readonly SourceReference[]; asOf: AsOfDate | null }) {
  const date = asOf ? formatDate(asOf.value, asOf.precision) : MISSING;
  return (
    <footer className="source-as-of">
      <span className="source-list">
        {sources.length ? sources.map((source) => {
          const url = safeSourceUrl(source.url);
          return <span className="source-item" key={source.source_id}>
            {url ? <a href={url} target="_blank" rel="noopener noreferrer">{source.name}</a> : <span>{source.name}</span>}
            {!source.is_nse && <span className="source-tag">Non-NSE</span>}
          </span>;
        }) : "Source unavailable"}
      </span>
      <span>{asOf?.kind === "period_end" ? "Period ending" : "As of"} {date !== MISSING && asOf?.precision !== "year"
        ? <time dateTime={asOf?.value ?? undefined}>{date}</time> : date}</span>
    </footer>
  );
}
