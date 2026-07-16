import { useState } from "react";
import SearchTab from "./components/SearchTab.jsx";
import SimilarityTab from "./components/SimilarityTab.jsx";

export default function App() {
  const [tab, setTab] = useState("search");

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Cosmetic Intelligence Engine</h1>
        <p>Recherche et exploration des ingrédients cosmétiques</p>
      </header>

      <nav className="tab-bar">
        <button
          className={tab === "search" ? "tab-btn active" : "tab-btn"}
          onClick={() => setTab("search")}
        >
          Recherche
        </button>
        <button
          className={tab === "similarity" ? "tab-btn active" : "tab-btn"}
          onClick={() => setTab("similarity")}
        >
          Similarité moléculaire
        </button>
      </nav>

      <main>{tab === "search" ? <SearchTab /> : <SimilarityTab />}</main>
    </div>
  );
}
