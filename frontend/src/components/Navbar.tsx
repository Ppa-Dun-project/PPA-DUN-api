import { Link } from "react-router-dom";

function Navbar() {
  return (
    <nav className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-8 py-5">
      <span className="text-white font-extrabold text-lg tracking-tight">
        PPA-DUN
      </span>
      <div className="flex items-center gap-8">
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