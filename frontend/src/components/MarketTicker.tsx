// Reference labels reserve the ticker layout; no quotes or feed are supplied yet.
const referenceLabels = ["SENSEX", "NIFTY BANK", "NIFTY IT"];

export default function MarketTicker() {
  return (
    <section className="market-ticker" aria-label="Market overview">
      <span className="market-status"><span aria-hidden="true" />NO DATA</span>
      <div className="ticker-scroll" tabIndex={0} role="region" aria-label="Market quotes unavailable; scroll to view instrument labels">
        <ul className="ticker-items">
          {referenceLabels.map((label) => (
            <li key={label}>
              <span>{label}</span>
              <span className="ticker-value" aria-label="unavailable">—</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
