import DashboardLayout from "../components/DashboardLayout";
import { indicatorPanelComponents } from "../components/panels/IndicatorPanels";
import { panelFixtures } from "./panel-fixtures";
import { tickerFixture } from "./ticker-fixtures";

export default function PanelsPreview() {
  return <DashboardLayout apiState="preview" announcement="Synthetic panel examples. Not financial observations." preview ticker={tickerFixture}>
    {indicatorPanelComponents.map((Panel, index) => <Panel key={index} data={panelFixtures[index]} />)}
  </DashboardLayout>;
}
