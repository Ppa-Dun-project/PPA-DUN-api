function Endpoints() {
  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full">

        <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">
          Endpoints
        </h1>
        <p className="text-white/50 text-sm mb-10">
          All endpoints except /health and /demo require an API Key.
        </p>

        {/* Endpoint Card */}
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">
          {/* Title */}
          <div className="flex items-center gap-3">
            <span className="rounded-lg bg-white/10 px-3 py-1 text-xs font-bold text-white">
              POST
            </span>
            <span className="text-white font-bold">/player</span>
          </div>
          <p className="text-sm text-white/50">
            Returns a recommended bid and player value for a given player name.
          </p>

          {/* Request */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Request</p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80">
              {JSON.stringify({ player_name: "Shohei Ohtani" }, null, 2)}
            </pre>
          </div>

          {/* Response */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Response</p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80">
              {JSON.stringify(
                {
                  player_name: "Shohei Ohtani",
                  recommended_bid: 42,
                  player_value: 87,
                },
                null,
                2
              )}
            </pre>
          </div>

          {/* Header */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Required Header</p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80">
              X-API-Key: your_api_key_here
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Endpoints;