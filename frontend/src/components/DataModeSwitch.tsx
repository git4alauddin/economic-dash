import { useId } from "react";
import type { DataMode } from "../data/data-mode";

export default function DataModeSwitch({ mode, onChange }: { mode: DataMode; onChange: (mode: DataMode) => void }) {
  const id = useId();
  return <fieldset className="data-mode-switch" data-mode={mode}>
    <legend className="sr-only">Dashboard data mode</legend>
    {(["seed", "live"] as const).map((value) => <label key={value}>
      <input type="radio" name={`${id}-data-mode`} value={value} aria-label={`${value === "seed" ? "Seed" : "Live"} data`}
        checked={mode === value} onChange={() => onChange(value)} />
      <span>{value === "seed" ? "Seed" : "Live"}</span>
    </label>)}
  </fieldset>;
}
