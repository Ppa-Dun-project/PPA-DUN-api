function Authentication() {
  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full">

        <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">
          Authentication
        </h1>
        <p className="text-white/50 text-sm mb-10">
          All endpoints except /health and /demo require a valid API Key.
        </p>

        {/* How it works */}
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">

          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">How it works</p>
            <p className="text-sm text-white/60 leading-relaxed">
              Include your API Key in every request header using the{" "}
              <code className="rounded bg-white/10 px-1.5 py-0.5 text-white/80">X-API-Key</code>{" "}
              field.
            </p>
          </div>

          {/* Header example */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Header</p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
              X-API-Key: your_api_key_here
            </pre>
          </div>

          {/* curl example */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Example</p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
              {`curl -X POST http://localhost:8000/player \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: your_api_key_here" \\
  -d '{"player_name": "Shohei Ohtani"}'`}
            </pre>
          </div>

          {/* Error responses */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Error Responses</p>
            <div className="space-y-3">
              <div className="rounded-2xl border border-white/10 bg-black/40 p-4 flex items-center gap-4">
                <span className="rounded-lg bg-red-500/20 px-2.5 py-1 text-xs font-bold text-red-300">
                  401
                </span>
                <span className="text-sm text-white/60">Missing API Key</span>
              </div>
              <div className="rounded-2xl border border-white/10 bg-black/40 p-4 flex items-center gap-4">
                <span className="rounded-lg bg-red-500/20 px-2.5 py-1 text-xs font-bold text-red-300">
                  401
                </span>
                <span className="text-sm text-white/60">Invalid API Key</span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

export default Authentication;