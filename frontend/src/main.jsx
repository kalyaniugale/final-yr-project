import React from "react";
import {createRoot} from "react-dom/client";
import ImplementationApp from "./ImplementationApp.jsx";
import "./components/RecommendationPage.css";
createRoot(document.getElementById("root")).render(<React.StrictMode><ImplementationApp/></React.StrictMode>);
