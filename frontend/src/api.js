// One place that knows where the backend lives. Overridable per-environment via
// a Vite env var (VITE_API_URL); defaults to the local API. In production this
// will point at the Railway URL.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Serve an ad. This ALSO records an impression on the backend, and returns the
// signed click_url we need to register a click. Shape: { ad_id, image_url, click_url }.
export async function serveAd() {
  const res = await fetch(`${API_URL}/ads/serve`);
  if (!res.ok) throw new Error(`serve failed: ${res.status}`);
  return res.json();
}

// Register a click by following the signed click_url the serve returned. The
// click_url is a relative path like "/click?ad_id=..&impression_id=..&sig=..".
export async function recordClick(clickUrl) {
  const res = await fetch(`${API_URL}${clickUrl}`);
  if (!res.ok) throw new Error(`click failed: ${res.status}`);
  return res.json();
}

// Fetch a per-minute metrics series for an ad over [from, to] (ISO strings).
// Returns { ad_id, points: [{ timestamp, clicks, impressions, ctr }, ...] }.
export async function fetchMetrics(adId, from, to) {
  const qs = new URLSearchParams({ from, to });
  const res = await fetch(`${API_URL}/ads/${adId}/metrics?${qs}`);
  if (!res.ok) throw new Error(`metrics failed: ${res.status}`);
  return res.json();
}
