import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { decimalSign, formatDecimal, MISSING } from "../ui/format";
import { quoteIsVisible, tickerStatus, unavailableTicker, type TickerPresentation } from "../ui/ticker-model";
import ComparisonChange from "./ui/ComparisonChange";
import SourceAsOf from "./ui/SourceAsOf";

export default function MarketTicker({ model = unavailableTicker, modeControl }: { model?: TickerPresentation; modeControl?: ReactNode }) {
  const id = useId();
  const region = useRef<HTMLElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const active = model.items.find((quote) => quote.instrumentId === selected) ?? null;
  const status = tickerStatus(model);
  const trigger = () => region.current?.querySelector<HTMLButtonElement>('[aria-expanded="true"]');

  useEffect(() => {
    if (!active) { setSelected(null); return; }
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !region.current?.contains(event.target)) setSelected(null);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [active]);

  return <section ref={region} className="market-ticker" aria-label="Market overview" data-ticker-state={model.state}
    onKeyDown={(event) => {
      if (event.key === "Escape" && active) { event.preventDefault(); trigger()?.focus(); setSelected(null); }
    }}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setSelected(null); }}>
    {modeControl ?? <span className="market-status" data-status={status}><span aria-hidden="true" />{status}</span>}
    {modeControl && <span className="sr-only">Market feed status: {status}</span>}
    <span id={`${id}-help`} className="sr-only">Market quotes. Scroll horizontally or use Left, Right, Home and End in this region. Activate an instrument for source, observation date and update schedule.</span>
    <div className="ticker-scroll" tabIndex={0} role="region" aria-label="Market quotes" aria-describedby={`${id}-help`}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        const scroll = event.currentTarget;
        const step = Math.max(120, scroll.clientWidth * 0.75);
        const positions: Record<string, number> = { ArrowLeft: scroll.scrollLeft - step, ArrowRight: scroll.scrollLeft + step, Home: 0, End: scroll.scrollWidth };
        if (Object.hasOwn(positions, event.key)) { event.preventDefault(); scroll.scrollTo({ left: positions[event.key], behavior: "instant" }); }
      }}>
      <ul className="ticker-items">
        {model.items.map((quote) => {
          const visible = quoteIsVisible(model, quote);
          const value = visible ? formatDecimal(quote.value, quote.precision) : MISSING;
          const change = visible ? formatDecimal(quote.changePercent, 2) : MISSING;
          const sign = visible ? decimalSign(quote.changePercent) : null;
          const direction = sign === null ? "missing" : sign > 0 ? "positive" : sign < 0 ? "negative" : "zero";
          return <li key={quote.instrumentId}>
            <button type="button" className="ticker-quote" data-instrument-id={quote.instrumentId} aria-expanded={active?.instrumentId === quote.instrumentId} aria-controls={active?.instrumentId === quote.instrumentId ? `${id}-details` : undefined}
              onClick={() => setSelected((current) => current === quote.instrumentId ? null : quote.instrumentId)}>
              <span>{quote.label}</span>
              <span className="ticker-value" aria-label={value === MISSING ? "Quote unavailable" : `${value} index points`}>{value}</span>
              <span className={`ticker-change comparison-${direction}`} aria-label={change === MISSING ? "Change unavailable" : `${sign === 1 ? "Increase" : sign === -1 ? "Decrease" : "No change"}: ${change}%`}>
                <span aria-hidden="true">{sign === 1 ? "▲ +" : sign === -1 ? "▼ " : sign === 0 ? "• " : ""}{change}{change !== MISSING ? "%" : ""}</span>
              </span>
              {visible && (model.state === "stale" || quote.state === "stale") && <span className="ticker-stale">Stale</span>}
            </button>
          </li>;
        })}
        {!model.items.length && <li className="ticker-empty">No instruments available</li>}
      </ul>
    </div>
    {active && <div className="ticker-details" id={`${id}-details`} role="region" aria-labelledby={`${id}-title`}>
      <div className="ticker-details-heading"><h2 id={`${id}-title`}>{active.label} details</h2><button type="button" className="ticker-close" onClick={() => { trigger()?.focus(); setSelected(null); }}>Close</button></div>
      <p>{quoteIsVisible(model, active) && formatDecimal(active.value, active.precision) !== MISSING ? (model.state === "stale" || active.state === "stale" ? "Stale quote · retained observation" : "Quote available") : model.state === "loading" || active.state === "loading" ? "Loading quote…" : model.state === "error" || active.state === "error" ? "Unable to load quote" : "Quote unavailable"}</p>
      <p>{model.cadenceLabel ?? "Update schedule unavailable"}{model.refreshing ? " · Refresh in progress" : ""}</p>
      {active.detail && <p>{active.detail}</p>}
      <div className="ticker-comparisons">
        <span>Points <ComparisonChange value={quoteIsVisible(model, active) ? active.changePoints : null} unit="index_points" precision={active.precision} referenceLabel={active.comparisonLabel ?? "Comparison period unavailable"} /></span>
        <span>Percent <ComparisonChange value={quoteIsVisible(model, active) ? active.changePercent : null} unit="percent" precision={2} referenceLabel={active.comparisonLabel ?? "Comparison period unavailable"} /></span>
      </div>
      <SourceAsOf sources={active.sources} asOf={active.asOf} />
    </div>}
  </section>;
}
