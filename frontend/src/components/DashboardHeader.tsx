// Decorative candle shapes have no data scale or financial meaning.
const candles = [
  [124, -18, 31, 71], [139, 4, 26, 70], [155, -12, 46, 94],
  [174, -30, 23, 87], [239, -25, 39, 77], [257, -10, 37, 88],
  [281, 5, 33, 72], [302, -15, 24, 92],
  [839, -23, 35, 79], [861, -10, 34, 73], [882, -37, 44, 85],
  [964, -10, 34, 88], [986, 26, 27, 67], [1005, -14, 25, 92],
  [1050, 1, 30, 81], [1076, -23, 43, 90],
];

export default function DashboardHeader() {
  return (
    <header className="dashboard-header">
      <svg className="header-decoration" viewBox="0 0 1214 84" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
        {candles.map(([x, y, height, wick]) => (
          <g key={x} className={x < 600 ? "candle-red" : "candle-blue"}>
            <path d={`M${x + 4} ${y - 12}v${wick}`} />
            <rect x={x} y={y} width="8" height={height} rx="2" />
          </g>
        ))}
      </svg>
      <h1 id="dashboard-title">ECONOMIC INDICATOR</h1>
    </header>
  );
}
