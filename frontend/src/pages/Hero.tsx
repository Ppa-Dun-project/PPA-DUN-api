function Hero() {
  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6">
      {/* Background Gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      {/* Content */}
      <div className="relative z-10 max-w-2xl text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs text-white/50 mb-6">
          PPA-DUN Evaluator · Fantasy Baseball
        </div>

        <h1 className="text-5xl font-extrabold tracking-tight text-white md:text-7xl">
          PPA-DUN API
        </h1>

        <p className="mt-6 text-lg text-white/60 leading-relaxed">
          A player valuation API for fantasy baseball draft kits.
          Send a player name, get back a recommended bid and player value —
          instantly.
        </p>

        <div className="mt-4 text-sm text-white/30">
          Designed to be licensed and integrated into any fantasy baseball platform.
        </div>
      </div>
    </div>
  );
}

export default Hero;