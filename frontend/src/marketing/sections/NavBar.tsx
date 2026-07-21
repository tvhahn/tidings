const REPO_URL = "https://github.com/tvhahn/tidings";

export function NavBar() {
  return (
    <nav className="nav">
      <div className="wrap nav-inner">
        <a className="nav-brand" href="/">
          <img src="/favicon.svg" alt="" />
          <span>Tidings</span>
        </a>
        <div className="nav-links">
          <a href="#how">How it works</a>
          <a href="#features">Features</a>
          <a href="#privacy">Privacy</a>
          <a href="#agents">For agents</a>
          <a href="#faq">FAQ</a>
          <a href="https://docs.gettidings.com/">Docs</a>
        </div>
        <div className="nav-cta">
          <a className="btn btn-ghost" href="/demo">
            Try the demo →
          </a>
          <a className="btn btn-primary nav-gh" href={REPO_URL}>
            View on GitHub
          </a>
        </div>
      </div>
    </nav>
  );
}
