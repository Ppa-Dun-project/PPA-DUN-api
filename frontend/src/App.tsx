import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Hero from "./pages/Hero";
import Endpoints from "./pages/Endpoints";
import Demo from "./pages/Demo";
import Authentication from "./pages/Authentication";

function App() {
  return (
    <div className="min-h-screen bg-black text-white">
      <Navbar />
      <Routes>
        <Route path="/" element={<Hero />} />
        <Route path="/endpoints" element={<Endpoints />} />
        <Route path="/demo" element={<Demo />} />
        <Route path="/auth" element={<Authentication />} />
      </Routes>
    </div>
  );
}

export default App;