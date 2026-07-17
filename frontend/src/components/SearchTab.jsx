import { useEffect, useState } from "react";
import { getFilters, searchIngredients } from "../api.js";

export default function SearchTab() {
  const [categories, setCategories] = useState([]);
  const [matters, setMatters] = useState([]);
  const [functions, setFunctions] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [matter, setMatter] = useState("");
  const [fn, setFn] = useState("");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    getFilters()
      .then((data) => {
        setCategories(data.categories);
        setMatters(data.matters);
        setFunctions(data.functions || []);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    const timeout = setTimeout(() => {
      searchIngredients({ query, category, matter, function: fn })
        .then((data) => {
          setItems(data.items);
          setTotal(data.total);
          setError(null);
        })
        .catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(timeout);
  }, [query, category, matter, fn]);

  return (
    <div className="tab-panel">
      <div className="filters-row">
        <input
          className="text-input"
          type="text"
          placeholder="Nom ou nom scientifique contient…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Toutes catégories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={matter} onChange={(e) => setMatter(e.target.value)}>
          <option value="">Tous types de matière</option>
          {matters.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select value={fn} onChange={(e) => setFn(e.target.value)}>
          <option value="">Toutes fonctions</option>
          {functions.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="error-msg">{error}</p>}

      <p className="result-count">
        <strong>{items.length}</strong> ingrédient(s) trouvé(s) sur {total}.
      </p>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Nom INCI</th>
              <th>Nom scientifique</th>
              <th>CAS</th>
              <th>Catégorie</th>
              <th>Type de matière</th>
              <th>Fonction</th>
              <th>SMILES</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.inci_name}>
                <td>{it.inci_name}</td>
                <td className="scientific-name-cell">{it.iupac_name ?? "—"}</td>
                <td>{it.cas_no ?? "—"}</td>
                <td>
                  {it.functional_category && (
                    <span className="badge badge-green">{it.functional_category}</span>
                  )}
                </td>
                <td>
                  {it.matter_type && (
                    <span className="badge badge-purple">{it.matter_type}</span>
                  )}
                </td>
                <td>
                  {it.function && <span className="badge badge-blue">{it.function}</span>}
                </td>
                <td className="smiles-cell">{it.smiles ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
