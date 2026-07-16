import { useEffect, useState } from "react";
import { getFilters, getSimilarity } from "../api.js";

export default function SimilarityTab() {
  const [names, setNames] = useState([]);
  const [selected, setSelected] = useState("");
  const [topN, setTopN] = useState(5);
  const [neighbours, setNeighbours] = useState([]);
  const [rdkitAvailable, setRdkitAvailable] = useState(true);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getFilters()
      .then((data) => {
        setNames(data.inci_names);
        if (data.inci_names.length) setSelected(data.inci_names[0]);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    getSimilarity({ inciName: selected, topN })
      .then((data) => {
        setRdkitAvailable(data.rdkit_available);
        setNeighbours(data.neighbours || []);
        setError(data.error ?? null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selected, topN]);

  if (!rdkitAvailable) {
    return (
      <div className="tab-panel">
        <p className="error-msg">RDKit n'est pas installé côté serveur : la similarité est indisponible.</p>
      </div>
    );
  }

  return (
    <div className="tab-panel">
      <p className="tab-intro">
        Trouvez les ingrédients chimiquement les plus proches (empreintes de Morgan · Tanimoto).
      </p>

      <div className="filters-row">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <label className="slider-label">
          Voisins : {topN}
          <input
            type="range"
            min="1"
            max="10"
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
          />
        </label>
      </div>

      {error && <p className="error-msg">{error}</p>}
      {loading && <p className="result-count">Calcul en cours…</p>}

      <div className="neighbours-grid">
        {neighbours.map((n) => (
          <div className="neighbour-card" key={n.inci_name}>
            <div className="neighbour-header">
              <span className="neighbour-name">{n.inci_name}</span>
              <span className="badge badge-blue">{n.similarity.toFixed(3)}</span>
            </div>
            <div className="similarity-bar-track">
              <div
                className="similarity-bar-fill"
                style={{ width: `${Math.round(n.similarity * 100)}%` }}
              />
            </div>
            <div className="neighbour-smiles">{n.smiles}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
