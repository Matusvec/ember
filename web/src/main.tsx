import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// StrictMode intentionally disabled — double-invoking effects breaks the
// webcam + MediaPipe lifecycle (tears down the stream mid-init).
ReactDOM.createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>
);
