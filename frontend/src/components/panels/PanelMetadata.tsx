import type { PanelPresentation } from "../../ui/panel-models";
import SourceAsOf from "../ui/SourceAsOf";

export default function PanelMetadata({ data }: { data?: PanelPresentation }) {
  return <div className="panel-provenance">
    <SourceAsOf sources={data?.sources ?? []} asOf={data?.asOf ?? null} />
    {data?.seriesDetails && <details className="panel-data-details" onKeyDown={(event) => {
      if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); }
    }}>
      <summary>Series details</summary>
      <div className="panel-data-popover">
        {data.detail && <p>{data.detail}</p>}
        {data.seriesDetails.map((series) => <section key={series.id} data-series-state={series.state}>
          <h3>{series.label} · {series.state}</h3><p>{series.detail}</p>
          <SourceAsOf sources={series.sources} asOf={series.asOf} />
        </section>)}
      </div>
    </details>}
  </div>;
}
