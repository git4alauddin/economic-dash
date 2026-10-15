export interface DashboardPanelDefinition {
  id: string;
  title: string;
  accentLabel?: string;
}

// Layout metadata only. Observations and available periods come from the API.
export const dashboardPanels = [
  { id: "gdp_growth", title: "GDP Growth - India vs World", accentLabel: "(YOY%)" },
  { id: "debt_to_gdp", title: "Debt to GDP Ratio", accentLabel: "(IND)" },
  { id: "trade", title: "Imports, Exports & Trade Balance" },
  { id: "gst_collection", title: "GST Tax Collection", accentLabel: "(YOY%)" },
  { id: "inflation_india", title: "Inflation", accentLabel: "(IND)" },
  { id: "government_expenditure", title: "Government Expenditure" },
] as const satisfies readonly DashboardPanelDefinition[];

export type IndicatorId = typeof dashboardPanels[number]["id"];
