import { useEffect, useState } from "react";
import { fetchAds, recordClick } from "../api.js";

export default function Landing() {
  const [ads, setAds] = useState([]);
  const [clicked, setClicked] = useState({}); // index -> true once clicked
  const [error, setError] = useState(null);

  // On mount, load the whole ad board (all distinct ads, one impression each).
  // Effects can't be async themselves, so declare an async helper and call it.
  useEffect(() => {
    async function load() {
      try {
        const board = await fetchAds();
        setAds(board);
      } catch (e) {
        setError(e.message);
      }
    }
    load();
  }, []);

  // TODO (you): register a click for the ad at position `index`.
  //   - await recordClick(ad.click_url)
  //   - mark it: setClicked((prev) => ({ ...prev, [index]: true }))
  //   - try/catch -> setError on failure
  async function handleClick(ad, index) {
    try {
      await recordClick(ad.click_url);
      setClicked((prev) => ({ ...prev, [index]: true }));
    } catch (e) {
      setError(e.message);
    }
  }

  if (error) {
    return <p className="text-red-600">Error: {error}</p>;
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Featured Ads</h1>
      <p className="mb-6 text-sm text-gray-500">
        Loading this page served {ads.length} impressions. Click an ad to register
        a click, then check the Dashboard.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {ads.map((ad, i) => (
          <button
            key={i}
            onClick={() => handleClick(ad, i)}
            disabled={clicked[i]}
            className="rounded-xl border bg-white p-3 text-left shadow-sm transition hover:shadow-md disabled:opacity-60"
          >
            <img
              src={ad.image_url}
              alt={`Ad ${ad.ad_id}`}
              className="mb-2 w-full rounded-lg"
            />
            <span className="text-sm font-medium text-gray-700">
              {clicked[i] ? "✓ Clicked" : `Click ad #${ad.ad_id}`}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
