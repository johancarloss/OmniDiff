export function Header() {
  return (
    <header className="border-b border-border px-6 py-4">
      <div className="mx-auto flex max-w-5xl items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold tracking-tight text-foreground">
            Omni<span className="text-primary">Diff</span>
          </span>
        </div>
        <a
          href="https://github.com/johancarloss/OmniDiff"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-muted-foreground transition-colors hover:text-primary"
        >
          GitHub
        </a>
      </div>
    </header>
  );
}
