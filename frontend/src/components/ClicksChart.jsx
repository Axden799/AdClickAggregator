import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

// Format an ISO timestamp -> "HH:MM" for axis ticks and the tooltip label.
function hhmm(iso) {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Single-series area chart: total clicks per minute over the last hour.
// One series -> one color (validated slot-1 blue), no legend; the dashboard
// table is the accompanying table view. Recharts supplies the hover tooltip.
export default function ClicksChart({ data }) {
  return (
    <div className="viz-root mt-6 rounded-xl border bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">
        Clicks per minute (last hour)
      </h2>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          {/* Subtle fill under the line, fading to the surface. */}
          <defs>
            <linearGradient id="clicksFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          {/* Recessive horizontal-only grid. */}
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="time"
            tickFormatter={hhmm}
            stroke="var(--muted)"
            tick={{ fontSize: 11 }}
            minTickGap={40}
          />
          <YAxis
            allowDecimals={false}
            stroke="var(--muted)"
            tick={{ fontSize: 11 }}
            width={32}
          />
          <Tooltip
            labelFormatter={hhmm}
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
          />
          {/* 2px line, no per-point dots (selective marks). */}
          <Area
            type="monotone"
            dataKey="clicks"
            stroke="var(--series-1)"
            strokeWidth={2}
            fill="url(#clicksFill)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
