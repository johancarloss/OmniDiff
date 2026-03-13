export function HomePage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6">
      <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
        Omni<span className="text-primary">Diff</span>
      </h1>
      <p className="max-w-lg text-center text-lg text-muted-foreground">
        Search your Git history by meaning, not by message. Find the commit that
        fixed concurrency, not &ldquo;fix: wip&rdquo;.
      </p>
      <div className="rounded-md border border-border bg-card px-4 py-2 text-sm text-muted-foreground">
        Under construction
      </div>
    </div>
  );
}
