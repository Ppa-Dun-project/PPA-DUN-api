import { useState } from "react";

interface Field {
  key: string;
  label: string;
  placeholder: string;
  enabled: boolean;
}

const fields: Field[] = [
  {
    key: "player_name",
    label: "Player Name",
    placeholder: "e.g. Shohei Ohtani",
    enabled: true,
  },
  // Add more stats here in the future
  // { key: "avg", label: "AVG", placeholder: "e.g. 0.301", enabled: false },
  // { key: "hr", label: "HR", placeholder: "e.g. 44", enabled: false },
];

function Demo() {
  const [values, setValues] = useState<Record<string, string>>({
    player_name: "",
  });
  const [result, setResult] = useState<null | {
    player_name: string;
    recommended_bid: number;
    player_value: number;
  }>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleDemo = async () => {
    if (!values.player_name) return;

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch("http://localhost:8000/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_name: values.player_name }),
      });

      if (!response.ok) {
        setError("Something went wrong. Please try again.");
        return;
      }

      const data = await response.json();
      setResult(data);
    } catch (e) {
      setError("Failed to connect to the API.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full">

        <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">
          Try it out
        </h1>
        <p className="text-white/50 text-sm mb-10">
          Enter a player name and see the API response in real time.
        </p>

        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
          {/* Input fields */}
          {fields
            .filter((f) => f.enabled)
            .map((f) => (
              <div key={f.key}>
                <p className="text-xs font-bold text-white/40 uppercase mb-2">
                  {f.label}
                </p>
                <input
                  type="text"
                  placeholder={f.placeholder}
                  value={values[f.key] || ""}
                  onChange={(e) => handleChange(f.key, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleDemo();
                  }}
                  className="w-full rounded-2xl border border-white/10 bg-black/40 px-4 py-3 text-sm text-white outline-none placeholder:text-white/30"
                />
              </div>
            ))}

          {/* Submit button */}
          <button
            onClick={handleDemo}
            disabled={loading}
            className="w-full rounded-xl bg-white py-3 text-sm font-extrabold text-black
                       transition hover:bg-white/90 active:scale-95 disabled:opacity-40"
          >
            {loading ? "Loading..." : "Submit"}
          </button>

          {/* Error */}
          {error && (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div>
              <p className="text-xs font-bold text-white/40 uppercase mb-2">
                Response
              </p>
              <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default Demo;