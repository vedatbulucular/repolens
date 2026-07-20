const LensMark = () => (
  <span aria-hidden="true" className="relative block size-5">
    <span className="absolute left-0.5 top-0.5 size-3.5 rounded-full border-2 border-current" />
    <span className="absolute bottom-0.5 right-0.5 h-2 w-0.5 rotate-[-45deg] rounded-full bg-current" />
  </span>
);

export default function Home() {
  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-50 text-slate-950">
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 -z-0 h-96 bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.13),_transparent_62%)]"
      />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6 sm:px-8">
        <a className="flex items-center gap-3" href="#top" aria-label="RepoLens home">
          <span className="flex size-10 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm shadow-indigo-200">
            <LensMark />
          </span>
          <span className="text-lg font-semibold tracking-tight">RepoLens</span>
        </a>
        <span className="rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm backdrop-blur">
          Open-source foundation preview
        </span>
      </header>

      <main
        className="relative z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col items-center px-6 pb-20 pt-16 text-center sm:px-8 sm:pt-24"
        id="top"
      >
        <p className="mb-5 rounded-full border border-indigo-100 bg-indigo-50 px-3.5 py-1.5 text-sm font-medium text-indigo-700">
          Repository onboarding, clarified
        </p>
        <h1 className="max-w-4xl text-balance text-4xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-6xl sm:leading-[1.08]">
          Understand a repository before your first commit.
        </h1>
        <p className="mt-6 max-w-2xl text-pretty text-base leading-7 text-slate-600 sm:text-lg">
          RepoLens turns public GitHub repositories into clear, evidence-backed insights so developers can onboard with confidence.
        </p>

        <section
          aria-labelledby="repository-form-title"
          className="mt-12 w-full max-w-3xl rounded-3xl border border-slate-200 bg-white p-5 text-left shadow-[0_24px_70px_-36px_rgba(15,23,42,0.35)] sm:p-7"
        >
          <div className="mb-5">
            <h2 className="text-base font-semibold text-slate-900" id="repository-form-title">
              Analyze a GitHub repository
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              Enter the URL of a public repository to begin.
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <label className="sr-only" htmlFor="repository-url">
                GitHub repository URL
              </label>
              <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-slate-400">
                <span aria-hidden="true" className="text-xs font-bold tracking-tight">
                  GH
                </span>
              </span>
              <input
                aria-describedby="repository-status"
                autoComplete="url"
                className="h-12 w-full rounded-xl border border-slate-300 bg-white pl-12 pr-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
                id="repository-url"
                name="repositoryUrl"
                placeholder="https://github.com/owner/repository"
                type="url"
              />
            </div>
            <button
              className="h-12 shrink-0 cursor-not-allowed rounded-xl bg-slate-200 px-6 text-sm font-semibold text-slate-500"
              disabled
              type="button"
            >
              Analyze Repository
            </button>
          </div>

          <div
            className="mt-4 flex items-start gap-2.5 rounded-xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600"
            id="repository-status"
          >
            <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-amber-400" />
            <p>
              Repository analysis will be enabled in a later development phase. This preview establishes the product interface and project foundation.
            </p>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-slate-200/80 px-6 py-5 text-center text-xs text-slate-500">
        RepoLens &middot; Built openly for faster developer onboarding.
      </footer>
    </div>
  );
}
