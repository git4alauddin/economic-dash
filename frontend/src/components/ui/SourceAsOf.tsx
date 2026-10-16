import { formatDate, MISSING, safeSourceUrl } from "../../ui/format";
import type { AsOfDate, SourceReference } from "../../ui/types";

const compactLabels: Readonly<Record<string, string>> = {
  mospi_gdp_pib: "MoSPI / PIB", mospi_cpi_pib: "MoSPI / PIB", commerce_trade_pib: "Commerce / PIB",
  finance_accounts_pib: "CGA / PIB", world_bank_gdp: "World Bank", "world_bank_gdp.metadata": "WB metadata",
};
export default function SourceAsOf({ sources, asOf, compact = false }: { sources: readonly SourceReference[]; asOf: AsOfDate | null; compact?: boolean }) {
  const date = asOf ? formatDate(asOf.value, asOf.precision) : MISSING;
  const groupedFallback = compact && sources.length > 0 && sources.every((source) => !source.is_nse);
  return (
    <footer className={`source-as-of${compact ? " source-compact" : ""}`}>
      <span className="source-list">
        {sources.length ? sources.map((source) => {
          const url = safeSourceUrl(source.url);
          return <span className="source-item" key={source.source_id}>
            {url ? <a href={url} target="_blank" rel="noopener noreferrer" {...(compact ? { title: source.name, "aria-label": source.name } : {})}>{compact ? compactLabels[source.source_id] ?? source.name : source.name}</a> : <span>{source.name}</span>}
            {!source.is_nse && !groupedFallback && <span className="source-tag">Non-NSE</span>}
          </span>;
        }) : "Source unavailable"}
        {groupedFallback && <span className="source-tag">Non-NSE</span>}
      </span>
      <span>{compact && sources.length && !asOf ? "Dates by series" : <>{asOf?.kind === "period_end" ? "Period ending" : "As of"} {date !== MISSING && asOf?.precision !== "year"
        ? <time dateTime={asOf?.value ?? undefined}>{date}</time> : date}</>}</span>
    </footer>
  );
}
