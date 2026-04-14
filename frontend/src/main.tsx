import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import "./index.css";
import App from "./App.tsx";

// VITE_GOOGLE_CLIENT_ID is injected at build time from the .env file.
// Falls back to an empty string if not set, which will cause Google OAuth
// to silently fail — ensure this is always set in production via .env.
// NOTE: This value is intentionally public (it's the OAuth client ID, not a secret).
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

// Mount the React app into the #root div defined in index.html.
// The "!" asserts the element is non-null — safe as long as index.html is intact.
createRoot(document.getElementById("root")!).render(
  // StrictMode renders components twice in development to surface side effects.
  // Has no effect in production builds.
  <StrictMode>
    {/*
      GoogleOAuthProvider wraps the entire app so any component can access
      Google OAuth hooks (e.g., useGoogleLogin) without additional setup.
      clientId must match the OAuth 2.0 client configured in Google Cloud Console.
    */}
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      {/*
        BrowserRouter enables client-side routing via the HTML5 History API.
        All <Route> definitions live in App.tsx.
      */}
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </GoogleOAuthProvider>
  </StrictMode>
);