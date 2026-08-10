import os from "os";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { FAQ_ITEMS } from "./src/marketing/faqItems";

const DEMO_URL = "https://gettidings.com/demo/";
const DEMO_OG_TITLE = "Tidings — live demo";
const DEMO_OG_DESCRIPTION =
  "A private finance journal from the transaction emails you already receive. Browse the real app with sample data.";
const DEMO_OG_IMAGE = "https://gettidings.com/demo-data/og-image.png";

const MARKETING_URL = "https://gettidings.com/";
const MARKETING_OG_TITLE = "Tidings — Your spending, delivered.";
const MARKETING_OG_DESCRIPTION =
  "A private finance journal from the transaction emails you already receive. Self-hosted, open source, calm by default.";
const MARKETING_OG_IMAGE = "https://gettidings.com/og-image.png";

// One minimal schema object for the one-page site (locked decision L8).
const MARKETING_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Tidings",
  url: MARKETING_URL,
  description: MARKETING_OG_DESCRIPTION,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Docker (Linux, macOS, Windows)",
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  license: "https://github.com/tvhahn/tidings/blob/main/LICENSE",
  sameAs: ["https://github.com/tvhahn/tidings"],
  screenshot: MARKETING_OG_IMAGE,
};

// FAQPage structured data (locked decision L6 / contract C6). One Question per
// faqItems.ts entry, in order — machine-readability for LLM crawlers. Emitted
// as a second ld+json block in the demo (deployed marketing) build only.
const MARKETING_FAQ_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: FAQ_ITEMS.map((it) => ({
    "@type": "Question",
    name: it.q,
    acceptedAnswer: { "@type": "Answer", text: it.a },
  })),
};

// Swap of the root index.html script tag. The file ships with
// `main-marketing.tsx` so the deployed marketing entry (the `--mode demo`
// build for gettidings.com) builds correctly, but everywhere else we want the
// real React SPA at `/`:
//   - dev serve — default `pnpm dev` on :5173 and `pnpm demo:dev` on :5176.
//   - plain `pnpm build` (mode is neither "demo" nor "marketing") — the
//     self-hosted app shell baked into Dockerfile.prod and served at `/` by
//     FastAPI. Without this the image would ship the marketing landing at `/`.
// The two entries that MUST keep `main-marketing.tsx` at `/`:
//   - `--mode marketing` serve (`pnpm marketing:dev`) — local marketing work.
//   - `--mode demo` build (`pnpm demo:build`) — the gettidings.com artifact,
//     whose root `dist/index.html` IS the marketing landing (the app lives at
//     `/demo/` via demo/index.html, which already points at main.tsx).
// Note demo differs by command: demo *serve* swaps to the SPA (so the demo app
// renders at `/` on :5176), demo *build* does not (marketing at `/`).
function devEntrySwap(command: "serve" | "build", mode: string): Plugin {
  return {
    name: "tidings-dev-entry-swap",
    transformIndexHtml: {
      order: "pre",
      handler(html, ctx) {
        if (ctx.path !== "/" && ctx.path !== "/index.html") return html;
        const shouldSwap = mode !== "marketing" && (command === "serve" || mode !== "demo");
        if (shouldSwap) {
          // Swap to the real SPA entry. The demo dev surface keeps a light
          // default via data-surface="demo"; the real app surface drops the
          // marker entirely so it keeps its "system" theme default.
          const swapped = html.replace("/src/main-marketing.tsx", "/src/main.tsx");
          if (mode === "demo")
            return swapped.replace(' data-surface="marketing"', ' data-surface="demo"');
          // PWA install tags for the self-hosted app shell only. The marketing
          // and demo surfaces must never be installable, so these tags can't
          // live statically in index.html (same reasoning as marketingHtmlMeta).
          const pwaTags = [
            '<link rel="manifest" href="/manifest.webmanifest" />',
            '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />',
          ].join("\n    ");
          return swapped
            .replace(' data-surface="marketing"', "")
            .replace("</head>", `    ${pwaTags}\n  </head>`);
        }
        return html;
      },
    },
  };
}

function demoHtmlMeta(): Plugin {
  return {
    name: "demo-html-meta",
    transformIndexHtml(html, ctx) {
      // Only touch the demo entry's HTML — the marketing entry keeps the
      // default favicon and its own meta.
      if (!ctx.filename.endsWith("demo/index.html")) return html;
      const tags = [
        '<meta name="robots" content="noindex,nofollow" />',
        `<meta property="og:type" content="website" />`,
        `<meta property="og:url" content="${DEMO_URL}" />`,
        `<meta property="og:title" content="${DEMO_OG_TITLE}" />`,
        `<meta property="og:description" content="${DEMO_OG_DESCRIPTION}" />`,
        `<meta property="og:image" content="${DEMO_OG_IMAGE}" />`,
        `<meta name="twitter:card" content="summary_large_image" />`,
        `<meta name="twitter:title" content="${DEMO_OG_TITLE}" />`,
        `<meta name="twitter:description" content="${DEMO_OG_DESCRIPTION}" />`,
        `<meta name="twitter:image" content="${DEMO_OG_IMAGE}" />`,
      ].join("\n    ");
      // Inject demo meta before </head>. Keep the base <link rel="icon"> — the
      // real Tidings mark at /favicon.svg — so the demo tab shows the brand
      // mark, identical to the marketing landing (not a placeholder icon).
      return html.replace("</head>", `    ${tags}\n  </head>`);
    },
  };
}

// Deployed-marketing-only meta (SEO + unfurl cards + JSON-LD). frontend/index.html
// is the shared source for two very different root shells: the `--mode demo`
// build turns it into the gettidings.com marketing landing (this meta applies),
// while plain `pnpm build` swaps its entry to main.tsx (devEntrySwap) so
// Dockerfile.prod bakes the self-hosted app shell that FastAPI serves at `/`
// (src/api/main.py). A self-hosted install must never ship a gettidings.com
// canonical, so none of this may live statically in the source file — and this
// plugin is registered for `--mode demo` only (see the isDemo gate below), with
// `apply: "build"` keeping any dev page clean regardless.
function marketingHtmlMeta(): Plugin {
  return {
    name: "marketing-html-meta",
    apply: "build",
    transformIndexHtml(html, ctx) {
      // Root entry only — demo/index.html keeps demoHtmlMeta()'s tags.
      if (ctx.filename.endsWith("demo/index.html")) return html;
      const tags = [
        `<link rel="canonical" href="${MARKETING_URL}" />`,
        `<meta property="og:type" content="website" />`,
        `<meta property="og:site_name" content="Tidings" />`,
        `<meta property="og:url" content="${MARKETING_URL}" />`,
        `<meta property="og:title" content="${MARKETING_OG_TITLE}" />`,
        `<meta property="og:description" content="${MARKETING_OG_DESCRIPTION}" />`,
        `<meta property="og:image" content="${MARKETING_OG_IMAGE}" />`,
        `<meta property="og:image:width" content="1200" />`,
        `<meta property="og:image:height" content="630" />`,
        `<meta property="og:image:alt" content="Tidings — a private finance journal built from the transaction emails you already receive" />`,
        `<meta name="twitter:card" content="summary_large_image" />`,
        `<meta name="twitter:title" content="${MARKETING_OG_TITLE}" />`,
        `<meta name="twitter:description" content="${MARKETING_OG_DESCRIPTION}" />`,
        `<meta name="twitter:image" content="${MARKETING_OG_IMAGE}" />`,
        `<script type="application/ld+json">${JSON.stringify(MARKETING_JSON_LD)}</script>`,
        `<script type="application/ld+json">${JSON.stringify(MARKETING_FAQ_JSON_LD)}</script>`,
      ].join("\n    ");
      return html.replace("</head>", `    ${tags}\n  </head>`);
    },
  };
}

export default defineConfig(({ command, mode }) => {
  const isDemo = mode === "demo";
  return {
    plugins: [
      react(),
      tailwindcss(),
      devEntrySwap(command, mode),
      ...(isDemo ? [demoHtmlMeta(), marketingHtmlMeta()] : []),
      {
        name: "tailscale-url",
        configureServer(server) {
          const _print = server.printUrls;
          server.printUrls = () => {
            _print();
            // Match the port Vite actually bound to (respects VITE_DEV_PORT
            // and any auto-increment) instead of hardcoding 5173.
            const local = server.resolvedUrls?.local[0];
            const port = local ? new URL(local).port : String(server.config.server.port ?? 5173);
            // Detect this machine's Tailscale address at runtime (CGNAT range
            // 100.64.0.0/10) rather than hardcoding a personal device IP — ships
            // nothing private and prints the right host on any developer's box.
            const tsAddr = Object.values(os.networkInterfaces())
              .flat()
              .find(
                (iface) =>
                  iface &&
                  iface.family === "IPv4" &&
                  /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(iface.address)
              )?.address;
            if (tsAddr) {
              console.log(
                `  \x1b[32m➜\x1b[0m  \x1b[1mTailscale:\x1b[0m  \x1b[36mhttp://${tsAddr}:${port}/\x1b[0m`
              );
            }
          };
        },
      },
    ],
    resolve: {
      // Alias order matters — more specific keys must come first so the
      // demo-mode override wins over the generic '@' prefix.
      alias: isDemo
        ? [
            {
              find: /^@\/lib\/api$/,
              replacement: path.resolve(__dirname, "./src/lib/demoApi"),
            },
            { find: "@", replacement: path.resolve(__dirname, "./src") },
          ]
        : {
            "@": path.resolve(__dirname, "./src"),
          },
    },
    build: {
      rollupOptions: {
        input: {
          main: path.resolve(__dirname, "index.html"),
          demo: path.resolve(__dirname, "demo/index.html"),
        },
      },
    },
    server: {
      host: "0.0.0.0",
      port: Number(process.env.VITE_DEV_PORT ?? 5173),
      proxy: {
        "/api": {
          target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
