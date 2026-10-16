import type { PanelPresentation } from "../../ui/panel-models";
import SourceAsOf from "../ui/SourceAsOf";
import { formatValue, unitLabel } from "../../ui/format";
import type { PanelProps } from "./IndicatorPanels";

export default function PanelMetadata({ data, explorer }: { data?: PanelPresentation; explorer?: PanelProps["explorer"] }) {
  const selection = explorer?.snapshot;
  return <div className="panel-provenance">
    <SourceAsOf sources={data?.sources ?? []} asOf={data?.asOf ?? null} compact />
    {data?.seriesDetails && <details className="panel-data-details" onToggle={(event) => { if (event.currentTarget.open) void explorer?.controller.open(); }} onKeyDown={(event) => {
      if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); }
    }}>
      <summary aria-label="Series details, history tables and sources">Series details</summary>
      <div className="panel-data-popover" tabIndex={0} role="region" aria-label="Series details and history tables">
        {data.detail && <p>{data.detail}</p>}
        {explorer && selection && <div className="panel-history-controls" aria-busy={selection.loading || selection.catalogLoading || selection.refreshing}>
          <p role="status">{selection.catalogLoading ? "Loading available periods…" : selection.message}</p>
          {selection.choices && <>
            <label>History window <select aria-label="History window" value={selection.window} onChange={(event) => { void explorer.controller.select(Number(event.target.value), selection.periods); }}>
              {[5, 10, 24].map((count) => <option key={count} value={count}>Up to {count} observations</option>)}
            </select></label>
            {selection.choices.map((choice) => <label key={choice.id}>{choice.label} period <select aria-label={`${choice.label} period`} data-period-series={choice.id}
              disabled={choice.blocked || !choice.periods.length} value={selection.periods[choice.id] ?? ""} onChange={(event) => {
                const periods = { ...selection.periods };
                if (event.target.value) periods[choice.id] = event.target.value; else delete periods[choice.id];
                void explorer.controller.select(selection.window, periods);
              }}>
              <option value="">{choice.blocked ? "Unavailable" : "Latest available"}</option>
              {choice.periods.map((period) => <option key={period.id} value={period.id}>{period.label} ({period.basis})</option>)}
            </select></label>)}
            <button type="button" onClick={() => { void explorer.controller.select(5, {}); }}>Latest view</button>
          </>}
        </div>}
        {data.seriesDetails.map((series) => <section key={series.id} data-series-id={series.id} data-series-state={series.state}>
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
