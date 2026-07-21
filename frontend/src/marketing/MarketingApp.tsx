import { Coda } from "./sections/Coda";
import { FAQ } from "./sections/FAQ";
import { Features } from "./sections/Features";
import { Footer } from "./sections/Footer";
import { ForAgents } from "./sections/ForAgents";
import { Hero } from "./sections/Hero";
import { HowItWorks } from "./sections/HowItWorks";
import { NavBar } from "./sections/NavBar";
import { GetStarted } from "./sections/Pricing";
import { PrivacyBand } from "./sections/PrivacyBand";
import "./marketing.css";

export function MarketingApp() {
  return (
    <div className="marketing">
      <NavBar />
      <Hero />
      <HowItWorks />
      <Features />
      <PrivacyBand />
      <GetStarted />
      <ForAgents />
      <FAQ />
      <Coda />
      <Footer />
    </div>
  );
}
