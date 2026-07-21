import { renderToStaticMarkup } from "react-dom/server";
import { MarketingApp } from "./marketing/MarketingApp";

export function render(): string {
  return renderToStaticMarkup(<MarketingApp />);
}
