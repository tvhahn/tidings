import { useState } from "react";
import { FAQ_ITEMS } from "../faqItems";
import { Icon } from "../Icon";

export function FAQ() {
  const [open, setOpen] = useState(0);
  return (
    <section id="faq">
      <div className="wrap">
        <div className="faq">
          <div>
            <div className="section-eyebrow">Frequently asked</div>
            <h2 className="section-title">The short version.</h2>
            <p className="section-sub">
              Long version: read the README in the repo. Tidings is built in the open.
            </p>
          </div>
          <div className="faq-items">
            {FAQ_ITEMS.map((it, i) => {
              const isOpen = open === i;
              return (
                <button
                  key={it.q}
                  type="button"
                  className={"faq-item" + (isOpen ? " is-open" : "")}
                  onClick={() => setOpen(isOpen ? -1 : i)}
                  aria-expanded={isOpen}
                >
                  <div className="faq-q">
                    <span>{it.q}</span>
                    <Icon name="plus" size={18} />
                  </div>
                  <div className="faq-a">{it.a}</div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
