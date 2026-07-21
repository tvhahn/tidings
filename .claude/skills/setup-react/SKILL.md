---
name: setup-react
description: Scaffold a React + Vite + pnpm frontend inside an existing project
argument-hint: [frontend-directory-name]
disable-model-invocation: true
allowed-tools: Bash(mkdir:*), Bash(pnpm:*), Bash(ls:*), Bash(test:*), Write, Read, Glob, AskUserQuestion
---

# Setup React Frontend

Scaffold a modern React + Vite + Tailwind CSS frontend as a subdirectory of an existing project. Designed for projects with a Python/FastAPI backend.

## Stack (hardcoded)

- React 19 + TypeScript (strict)
- Vite 7 with `@tailwindcss/vite` plugin
- Tailwind CSS 4 (CSS-first config, no PostCSS)
- ESLint 10 (flat config)
- pnpm package manager
- `@/` path alias → `src/`
- Vite proxy to backend API
- Dev server on `0.0.0.0` (devcontainer-friendly)

## Phase 1: Directory & Project Name

1. Determine the frontend directory name:
   - If `$ARGUMENTS` is provided, use it
   - Otherwise default to `frontend`
   - Confirm with the user

2. Determine the project display name:
   - Default to the **parent directory name** (the overall project)
   - Sanitize: lowercase, spaces→hyphens, alphanumeric and hyphens only

3. Check if the directory already exists:
   - If it exists and contains files, warn the user and ask to proceed or abort
   - If it doesn't exist, proceed

## Phase 2: Feature Selection

Use AskUserQuestion to gather all feature selections. Batch questions where possible.

### Question 1: shadcn/ui
Ask: "Include shadcn/ui component library?"
Options:
- **Yes** (Recommended): Adds class-variance-authority, clsx, tailwind-merge, lucide-react, cn() utility, and components.json. You can add components later with `pnpm dlx shadcn@latest add <component>`.
- **No**: Skip component library setup

### Question 2: React Router
Ask: "Include React Router v7 for client-side routing?"
Options:
- **No** (Recommended): Most Python+React projects handle routing server-side
- **Yes**: Adds react-router v7

### Question 3: TanStack Query
Ask: "Include TanStack Query for API data fetching/caching?"
Options:
- **No** (Recommended): Use plain fetch for simple API calls
- **Yes**: Adds @tanstack/react-query v5

### Question 4: Zustand
Ask: "Include Zustand for global state management?"
Options:
- **No** (Recommended): React 19 built-in state is sufficient for most cases
- **Yes**: Adds zustand v5

### Question 5: Font
Ask: "Which font setup?"
Options:
- **Inter via Google Fonts** (Recommended): Clean, modern sans-serif. Added via CDN link in index.html.
- **System fonts**: Uses the OS default font stack. No external requests.
- **None**: No font configuration

### Question 6: Backend API Port
Ask: "Backend API port for Vite dev proxy? (proxy /api → localhost:<port>)"
Options:
- **8000** (Recommended): FastAPI/uvicorn default
- **8001**: Offset +1
- **8080**: Alternative common port
- Custom: Let user specify

Store all selections for template processing.

## Phase 3: Directory Creation

Create the frontend directory structure:

```bash
mkdir -p <DIR>/public
mkdir -p <DIR>/src/assets
mkdir -p <DIR>/src/components
mkdir -p <DIR>/src/lib
```

If shadcn/ui selected:
```bash
mkdir -p <DIR>/src/components/ui
```

## Phase 4: Template Processing

Read each template file from the skill's `templates/` directory and process placeholders. The template directory is located at the same path as this SKILL.md file, under `templates/`.

### Placeholder Reference

| Placeholder | Source |
|-------------|--------|
| `{{PROJECT_NAME}}` | Sanitized project name |
| `{{FRONTEND_DIR}}` | Frontend directory name |
| `{{API_PORT}}` | Backend API port |
| `{{SHADCN_DEPS}}` | shadcn dependency block or empty |
| `{{ROUTER_DEP}}` | React Router dependency line or empty |
| `{{TANSTACK_DEP}}` | TanStack Query dependency line or empty |
| `{{ZUSTAND_DEP}}` | Zustand dependency line or empty |
| `{{FONT_LINKS}}` | Google Fonts link tags or empty |
| `{{FONT_THEME}}` | Font @theme CSS or empty |
| `{{SHADCN_UTILS_IMPORT}}` | Import for cn() or empty |

### Files to generate

Process these templates and write to the frontend directory:

1. **package.json** ← `templates/package.json.template`
   - Replace `{{PROJECT_NAME}}`, conditional dependency blocks
   - `{{SHADCN_DEPS}}`: If shadcn selected:
     ```
         "class-variance-authority": "^0.7",
         "clsx": "^2",
         "lucide-react": "^0.564",
         "tailwind-merge": "^3",
     ```
   - `{{ROUTER_DEP}}`: If React Router: `    "react-router": "^7",\n`
   - `{{TANSTACK_DEP}}`: If TanStack Query: `    "@tanstack/react-query": "^5",\n`
   - `{{ZUSTAND_DEP}}`: If Zustand: `    "zustand": "^5",\n`

2. **vite.config.ts** ← `templates/vite.config.ts.template`
   - Replace `{{API_PORT}}`

3. **tsconfig.json** ← `templates/tsconfig.json.template` (no placeholders)

4. **tsconfig.app.json** ← `templates/tsconfig.app.json.template` (no placeholders)

5. **tsconfig.node.json** ← `templates/tsconfig.node.json.template` (no placeholders)

6. **eslint.config.js** ← `templates/eslint.config.js.template` (no placeholders)

7. **index.html** ← `templates/index.html.template`
   - Replace `{{PROJECT_NAME}}`, `{{FONT_LINKS}}`
   - `{{FONT_LINKS}}`: If Inter font selected:
     ```html
         <link rel="preconnect" href="https://fonts.googleapis.com" />
         <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
         <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
     ```

8. **src/main.tsx** ← `templates/src/main.tsx.template` (no placeholders)

9. **src/App.tsx** ← `templates/src/App.tsx.template`
   - Replace `{{PROJECT_NAME}}`

10. **src/index.css** ← `templates/src/index.css.template`
    - Replace `{{FONT_THEME}}`
    - `{{FONT_THEME}}`: If Inter:
      ```css
      @theme {
        --font-sans: "Inter", sans-serif;
      }
      ```

11. If shadcn selected:
    - **src/lib/utils.ts** ← `templates/src/lib/utils.ts.template` (no placeholders)
    - **components.json** ← `templates/components.json.template`
      - Replace `{{FRONTEND_DIR}}`

## Phase 5: Post-Setup

Do NOT run `pnpm install` automatically. Just report what was created.

## Phase 6: Completion Report

Display a summary:

```
React frontend scaffolded in <DIR>/

Stack:
  - React 19 + TypeScript (strict)
  - Vite 7 + Tailwind CSS 4
  - ESLint 10 (flat config)
  [- shadcn/ui components]
  [- React Router v7]
  [- TanStack Query v5]
  [- Zustand v5]

Vite proxy: /api → http://localhost:<port>

Next steps:
  1. cd <DIR> && pnpm install
  2. pnpm dev
  [3. pnpm dlx shadcn@latest add button  (add shadcn components)]

Files created:
  <list all files>
```
