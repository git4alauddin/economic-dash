import { useId } from "react";

export type PanelIconKind = "india" | "world" | "us" | "exports" | "imports" | "gst" | "average" | "inflation" | "target" | "total" | "capital";

// Original SVG substitutes; the reference's illustrated assets are not available.
export default function PanelIcon({ kind }: { kind: PanelIconKind }) {
  const id = useId();
  const flag = kind === "india" || kind === "us";
  return (
    <svg viewBox="0 0 64 64" className={`panel-icon icon-${kind}`} aria-hidden="true" focusable="false">
      <defs>
        <clipPath id={`${id}-circle`}><circle cx="32" cy="32" r="29" /></clipPath>
        <linearGradient id={`${id}-gold`} x2="0.8" y2="1"><stop stopColor="#ffda7b" /><stop offset="0.5" stopColor="#c98c25" /><stop offset="1" stopColor="#71501b" /></linearGradient>
        <radialGradient id={`${id}-ocean`} cx="30%" cy="25%" r="80%"><stop stopColor="#8ae6ff" /><stop offset="0.5" stopColor="#067eab" /><stop offset="1" stopColor="#062451" /></radialGradient>
      </defs>
      {flag ? <>
        <g clipPath={`url(#${id}-circle)`}>
          {kind === "india" ? <>
            <path fill="#ff9d21" d="M0 0h64v22H0z" /><path fill="#f5f7f5" d="M0 22h64v20H0z" /><path fill="#168a3d" d="M0 42h64v22H0z" />
            <circle cx="32" cy="32" r="8" fill="none" stroke="#214884" strokeWidth="1.5" />
            {Array.from({ length: 24 }, (_, index) => <path key={index} d="M32 32v-7" transform={`rotate(${index * 15} 32 32)`} stroke="#214884" strokeWidth="0.6" />)}
          </> : <>
            <rect width="64" height="64" fill="#f5f7fb" />
            {Array.from({ length: 7 }, (_, index) => <rect key={index} y={index * 64 / 6.5} width="64" height={64 / 13} fill="#c93845" />)}
            <rect width="30" height="35" fill="#18447d" />
            {Array.from({ length: 9 }, (_, row) => Array.from({ length: row % 2 ? 5 : 6 }, (_, column) => <circle key={`${row}-${column}`} cx={3 + column * 4.6 + (row % 2 ? 2.3 : 0)} cy={3 + row * 3.5} r="0.8" fill="white" />))}
          </>}
        </g>
        <circle cx="32" cy="32" r="29" fill="none" stroke="#cbe6f0" strokeWidth="2" />
        <path d="M14 15Q32 2 48 15" fill="none" stroke="white" strokeOpacity="0.7" strokeWidth="4" strokeLinecap="round" />
      </> : kind === "world" ? <>
        <circle cx="32" cy="32" r="29" fill={`url(#${id}-ocean)`} stroke="#c9e9f1" strokeWidth="2" />
        <path d="m18 12 11-4 5 7-8 6 2 8-7 8-7-9 4-8zm19 18 12-7 9 10-10 7-6 16-6-6 3-9z" fill="#7dba68" />
        <ellipse cx="32" cy="32" rx="16" ry="29" fill="none" stroke="#e5f5ee" strokeOpacity="0.25" /><path d="M5 32h54" stroke="#e5f5ee" strokeOpacity="0.25" />
      </> : <>
        <ellipse cx="33" cy="56" rx="28" ry="5" fill="#00b9d6" opacity="0.18" />
        {kind === "target" ? <>
          {[23, 15, 7].map((radius, index) => <circle key={radius} cx="30" cy="31" r={radius} fill={index % 2 ? "#135c7b" : `url(#${id}-gold)`} stroke="#ffe5ac" strokeWidth="1" />)}
          <path d="m31 30 22-20m-10 1 11-2-1 11" fill="none" stroke="#8fe4ec" strokeWidth="4" strokeLinecap="round" />
        </> : kind === "average" ? <>
          <rect x="12" y="12" width="42" height="43" rx="5" fill="#164661" stroke="#c7e1ec" strokeWidth="2" />
          <path d="M12 25h42M23 7v12M43 7v12" stroke={`url(#${id}-gold)`} strokeWidth="4" />
          <path d="m18 44 10-9 8 4 12-10" fill="none" stroke="#ffd36c" strokeWidth="3" />
        </> : kind === "gst" ? <>
          <rect x="18" y="5" width="32" height="48" rx="5" fill="#193e55" stroke="#bad8e7" strokeWidth="2" />
          <path d="M25 14h18M25 21h18M25 28h12" stroke="#ffd376" strokeWidth="2" /><text x="25" y="46" fill="#ffce64" fontSize="19">₹</text>
        </> : kind === "exports" || kind === "imports" ? <>
          <path d="M6 43h51l-8 12H16z" fill="#18556e" stroke="#d6eaf0" strokeWidth="1.5" />
          <path d="M13 42V29h13v13m1 0V23h13v19m1 0V31h12v11" fill={`url(#${id}-gold)`} stroke="#f6d68e" />
          <path d={kind === "exports" ? "m19 24 15-11 7 5 14-14m-12 1 12-1-1 12" : "m15 9 13 12 8-5 15 13m-1-12 1 12-12-1"} fill="none" stroke="#66d8c7" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        </> : <>
          <path d={kind === "capital" ? "M6 24 32 8l26 16zM10 51h44M14 27v22m12-22v22m12-22v22m12-22v22" : "M10 51V35h10v16m7 0V25h10v26m7 0V13h10v38"} fill={`url(#${id}-gold)`} stroke="#e9d4a4" strokeWidth="2" />
          <path d="m9 27 15-10 10 5L54 4m-12 1 12-1-1 12" fill="none" stroke="#67d3e2" strokeWidth="3" strokeLinejoin="round" />
        </>}
        {[0, 1, 2].map((index) => <g key={index} transform={`translate(${5 + index * 8} ${43 + index % 2 * 4})`}><rect width="10" height="12" rx="3" fill={`url(#${id}-gold)`} stroke="#ffdb7c" /><path d="M0 4h10M0 8h10" stroke="#84632a" /></g>)}
      </>}
    </svg>
  );
}
