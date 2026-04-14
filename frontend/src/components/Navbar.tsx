import { Link } from "react-router-dom";

// Navbar is a fixed top navigation bar rendered on every page via App.tsx.
// Uses absolute positioning so page content can flow beneath it — pages that
// need to account for the navbar height should add top padding accordingly.
// All links use React Router's <Link> for client-side navigation (no full reload).

function Navbar() {
  return (
    <nav className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-8 py-5">
      {/* Brand name — clicking navigates to "/" via the Home link below */}
      <span className="text-white font-extrabold text-lg tracking-tight">
        PPA-DUN
      </span>

      <div className="flex items-center gap-8">
        {/* text-white/60 = 60% opacity white for inactive state; hover:text-white = full white on hover */}
        <Link to="/" className="text-sm text-white/60 hover:text-white transition">
          Home
        </Link>
        <Link to="/endpoints" className="text-sm text-white/60 hover:text-white transition">
          Endpoints
        </Link>
        <Link to="/demo" className="text-sm text-white/60 hover:text-white transition">
          Demo
        </Link>
        <Link to="/auth" className="text-sm text-white/60 hover:text-white transition">
          Authentication
        </Link>
      </div>
    </nav>
  );
}

export default Navbar;