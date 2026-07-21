import { Icon } from "../Icon";

export function Coda() {
  return (
    <section className="coda">
      <div className="coda-plate" aria-hidden="true" />
      <div className="wrap">
        <div className="coda-inner">
          <h2 className="coda-title">Eleven months, already delivered.</h2>
          <p className="coda-sub">
            The demo is the full product running in your browser, seeded with a fictional household.
            Yours is three commands away.
          </p>
          <a className="btn btn-primary" href="/demo">
            <span>Try the demo</span>
            <Icon name="arrow-right" size={14} />
          </a>
        </div>
      </div>
    </section>
  );
}
