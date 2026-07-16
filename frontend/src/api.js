const API_BASE = "http://localhost:8000";

async function getJSON(path, params = {}) {
  const url = new URL(API_BASE + path);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Erreur API (${res.status}) sur ${path}`);
  }
  return res.json();
}

export function getFilters() {
  return getJSON("/api/filters");
}

export function searchIngredients({ query, category, matter, function: fn }) {
  return getJSON("/api/ingredients", { query, category, matter, function: fn });
}

export function getSimilarity({ inciName, topN }) {
  return getJSON("/api/similarity", { inci_name: inciName, top_n: topN });
}
