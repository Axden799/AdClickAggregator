import { useEffect, useState } from "react";
import { fetchMetrics } from "../api.js";
import ClicksChart from "../components/ClicksChart.jsx";

// The ads we show. (Ids match the seeded ads / the serve list.)
const AD_IDS = [1, 2, 3, 4];

// Build the chart series: total clicks per minute across all ads. Every ad's
// response covers the same window, so points line up by index i.
function toClicksSeries(results) {
  // TODO (you): return an array of { time, clicks }, one per minute.
  //   results[0].points gives the timestamps; for each index i, sum the clicks
  //   from all four ads at that same index.
  //
  //   return results[0].points.map((p, i) => {
  //     let clicks = 0;
  //     for (const r of results) clicks += r.points[i].clicks;
  //     return { time: p.timestamp, clicks };
  //   });
  return results[0].points.map((p, i) => {
    let clicks = 0;
    for (const r of results) clicks += r.points[i].clicks;
    return { time: p.timestamp, clicks };
  })
}

// Collapse one ad's per-minute metrics response into a single totals row.
// A response looks like { ad_id, points: [{ timestamp, clicks, impressions, ctr }, ...] }.
function summarize(metrics) {
  let clicks = 0;
  let impressions = 0;
  for (const p of metrics.points) {
    clicks += p.clicks;
    impressions += p.impressions;
  }
  const ctr = impressions > 0 ? clicks / impressions : 0;

  return { clicks, impressions, ctr}; // replace this
}

export default function Dashboard() {
  const [rows, setRows] = useState([]);
  const [series, setSeries] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      // Fixed window: the last hour. toISOString() gives the format the API wants.
      const now = new Date();
      const to = now.toISOString();
      const from = new Date(now.getTime() - 60 * 60 * 1000).toISOString();

      // Fetch all four ads in parallel, then summarize each into a row.
      const results = await Promise.all(
        AD_IDS.map((id) => fetchMetrics(id, from, to)),
      );
      setRows(results.map((m) => ({ adId: m.ad_id, ...summarize(m) })));
      setSeries(toClicksSeries(results));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  // Load once on mount.
  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-gray-500">Totals over the last hour.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <p className="mb-4 text-red-600">Error: {error}</p>}

      <table className="w-full overflow-hidden rounded-xl border bg-white text-left text-sm">
        <thead className="bg-gray-100 text-gray-600">
          <tr>
            <th className="px-4 py-3">Ad</th>
            <th className="px-4 py-3">Clicks</th>
            <th className="px-4 py-3">Impressions</th>
            <th className="px-4 py-3">CTR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.adId} className="border-t">
              <td className="px-4 py-3 font-medium">#{row.adId}</td>
              <td className="px-4 py-3">{row.clicks}</td>
              <td className="px-4 py-3">{row.impressions}</td>
              <td className="px-4 py-3">{(row.ctr * 100).toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>

      {series.length > 0 && <ClicksChart data={series} />}
    </div>
  );
}
