import DashboardLayout from "../components/DashboardLayout";
import { indicatorPanelComponents } from "../components/panels/IndicatorPanels";
import { panelFixtures } from "./panel-fixtures";

export default function PanelsPreview() {
  return <DashboardLayout apiState="preview" announcement="Synthetic panel examples. Not financial observations." preview>
    {indicatorPanelComponents.map((Panel, index) => <Panel key={index} data={panelFixtures[index]} />)}
  </DashboardLayout>;
}
