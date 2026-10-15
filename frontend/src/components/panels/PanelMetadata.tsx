import type { PanelPresentation } from "../../ui/panel-models";
import SourceAsOf from "../ui/SourceAsOf";
import { formatValue, unitLabel } from "../../ui/format";

export default function PanelMetadata({ data }: { data?: PanelPresentation }) {
  return <div className="panel-provenance">
    <SourceAsOf sources={data?.sources ?? []} asOf={data?.asOf ?? null} />
    {data?.seriesDetails && <details className="panel-data-details" onKeyDown={(event) => {
      if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); }
    }}>
      <summary aria-label="Series details, history tables and sources">Series details</summary>
      <div className="panel-data-popover" tabIndex={0} role="region" aria-label="Series details and history tables">
        {data.detail && <p>{data.detail}</p>}
        {data.seriesDetails.map((series) => <section key={series.id} data-series-state={series.state}>
          <h3>{series.label} · {series.state}</h3><p>{series.detail}</p>
          <SourceAsOf sources={series.sources} asOf={series.asOf} />
          {!!series.history?.length && <table className="series-history-table">
            <caption>{series.label} history ({unitLabel(series.history[0].unit)})</caption>
            <thead><tr><th scope="col">Period</th><th scope="col">Value</th></tr></thead>
            <tbody>{series.history.map((point, index) => <tr key={index}><th scope="row">{point.period}</th><td>{formatValue(point.value, point.unit, series.precision ?? 2)}</td></tr>)}</tbody>
          </table>}
        </section>)}
      </div>
    </details>}
  </div>;
}
