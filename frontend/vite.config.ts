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
  "A private finance journal from the transaction emails you already receive. Self-hosted, open source, runs on your machine.";
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

// Dev-only swap of the root index.html script tag. The file ships with
// `main-marketing.tsx` so the production marketing entry builds correctly,
// but in dev (default `pnpm dev` on :5173 and `pnpm demo:dev` on :5176)
// we want the real React SPA at `/`. `--mode marketing` opts back into the
// marketing entry for local marketing iteration (`pnpm marketing:dev`).
function devEntrySwap(command: "serve" | "build", mode: string): Plugin {
  return {
    name: "tidings-dev-entry-swap",
    transformIndexHtml: {
      order: "pre",
      handler(html, ctx) {
        if (ctx.path !== "/" && ctx.path !== "/index.html") return html;
        if (command === "serve" && mode !== "marketing") {
          // Swap to the real SPA entry. The demo dev surface keeps a light
          // default via data-surface="demo"; the real app surface drops the
          // marker entirely so it keeps its "system" theme default.
          const swapped = html.replace("/src/main-marketing.tsx", "/src/main.tsx");
          return mode === "demo"
            ? swapped.replace(' data-surface="marketing"', ' data-surface="demo"')
            : swapped.replace(' data-surface="marketing"', "");
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

// Deployed-marketing-only meta (SEO + unfurl cards + JSON-LD). The same
// frontend/index.html is ALSO the self-hosted app shell — plain `pnpm build`
// emits it as dist/index.html, Dockerfile.prod bakes that into the image, and
// FastAPI serves it at `/` (src/api/main.py:347). A self-hosted install must
// never ship a gettidings.com canonical, so none of this may live statically
// in the source file. Only the `--mode demo` bundle (the artifact deployed to
// gettidings.com) gets these tags; `apply: "build"` keeps dev pages clean.
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
