import { Routes, Route, NavLink } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Dashboard from "./pages/Dashboard.jsx";

// Active nav link styling helper.
const linkClass = ({ isActive }) =>
  isActive ? "font-semibold text-blue-600" : "text-gray-500 hover:text-gray-800";

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <nav className="flex items-center gap-6 border-b bg-white px-6 py-4">
        <span className="font-bold">Ad Click Aggregator</span>
        <NavLink to="/" className={linkClass} end>
          Ads
        </NavLink>
        <NavLink to="/dashboard" className={linkClass}>
          Dashboard
        </NavLink>
      </nav>
      <main className="mx-auto max-w-4xl p-6">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
