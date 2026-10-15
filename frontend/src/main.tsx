import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./tokens.css";
import "./styles.css";
import "./primitives.css";
import "./panels.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("The application root element is missing.");
}

const root = createRoot(rootElement);
// Vite removes this development-only branch and its fixture import in production.
if (import.meta.env.DEV && window.location.pathname === "/__ui-preview") {
  void import("./preview/PrimitivesPreview").then(({ default: Preview }) => {
    root.render(<StrictMode><Preview /></StrictMode>);
  });
} else if (import.meta.env.DEV && window.location.pathname === "/__panel-preview") {
  void import("./preview/PanelsPreview").then(({ default: Preview }) => {
    root.render(<StrictMode><Preview /></StrictMode>);
  });
} else {
  root.render(<StrictMode><App /></StrictMode>);
}
