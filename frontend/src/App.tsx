import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Hero from "./pages/Hero";
import Endpoints from "./pages/Endpoints";
import Authentication from "./pages/Authentication";

// App is the root component of the dashboard.
// It defines the global layout (Navbar always visible) and the client-side
// routing table. BrowserRouter is provided by main.tsx, so Routes works here.
//
// Route map:
//   /            → Hero.tsx          Landing page + algorithm explanation
//   /endpoints   → Endpoints.tsx     API spec documentation
//   /auth        → Authentication.tsx Google login + API key management

function App() {
  return (
    // min-h-screen ensures the black background covers the full viewport
    // even on pages with little content.
    <div className="min-h-screen bg-black text-white">
      {/* Navbar is rendered outside <Routes> so it persists across all pages */}
      <Navbar />
      <Routes>
        <Route path="/"          element={<Hero />} />
        <Route path="/endpoints" element={<Endpoints />} />
        <Route path="/auth"      element={<Authentication />} />
      </Routes>
    </div>
  );
}

export default App;