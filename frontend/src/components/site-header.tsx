import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container header-inner">
        <Link className="brand" href="/" aria-label="MediPredict home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
          </span>
          <span className="brand-copy">
            <strong>MediPredict</strong>
            <small>HEALTH, WITH CLARITY</small>
          </span>
        </Link>
        <nav className="main-nav" aria-label="Main navigation">
          <Link href="/#how-it-works">How it works</Link>
          <Link href="/#our-approach">Our approach</Link>
          <Link href="/login">Sign in</Link>
          <Link className="nav-cta" href="/register">Create account <span aria-hidden="true">↗</span></Link>
        </nav>
      </div>
    </header>
  );
}
