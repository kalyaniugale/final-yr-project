import React from "react";
import {createRoot} from "react-dom/client";
import ImplementationApp from "./ImplementationApp.jsx";
import {I18nProvider} from "./i18n/react.jsx";
import "./components/RecommendationPage.css";
createRoot(document.getElementById("root")).render(<React.StrictMode><I18nProvider><ImplementationApp/></I18nProvider></React.StrictMode>);
