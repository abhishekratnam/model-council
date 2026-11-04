# javascript.md — JavaScript / TypeScript project guidance

**Read order:** load after `AGENTS.md`. Applies whenever `AGENTS.md` §2 detects
the **javascript** category (JavaScript includes TypeScript).

**Precedence:** `AGENTS.md` owns the shared rules — project discovery (§1.1),
baseline and verification (§1.2), plan mode and approvals (§4). This file adds
JavaScript/TypeScript-specific detail only. On conflict, `AGENTS.md` wins,
except where this file is stricter. The workspace runner substitutes `{port}`
and `probe_url` at dispatch time; use the supplied values as given.

## 1. Identify the toolchain before running anything

Inspect, in this order: `package.json`, every lockfile, `deno.json`/`deno.jsonc`,
`.npmrc` / `.yarnrc.yml`, `.nvmrc` / `.node-version`, `tsconfig.json`, and the
README — to identify the package manager, the Node version, and the documented
commands. Then pick the manager from the **first matching row**:

| First match in the project directory | Manager | Run everything through |
|---|---|---|
| `deno.json` / `deno.jsonc` | Deno | `deno task …`, `deno run …` |
| `pnpm-lock.yaml` | pnpm | `pnpm …` |
| `yarn.lock` (or `.yarnrc.yml`) | yarn | `yarn …` |
| `bun.lock` / `bun.lockb` | bun | `bun …` |
| `package-lock.json` | npm | `npm …`, `npx --no-install …` |
| `package.json` with a `"packageManager"` field | that manager (Corepack) | its runner |
| `package.json` without a lockfile | undetermined | check README + scripts; if still ambiguous, ask |
| only `.js`/`.ts` files, no manifest | undetermined | stop — do not scaffold; propose a setup in the plan and ask |

The lockfile fixes the manager. Never switch or mix managers (AGENTS.md §3.4),
even when a command would be shorter in another one.

Additional checks:

- Node version: honor `engines` in `package.json` and `.nvmrc` / `.node-version`. If the local runtime does not match, report the mismatch and ask — do not install a new Node version without approval.
- Monorepo signals (`"workspaces"`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`): run commands from the package the task targets and use that manager's workspace filtering (§2). Respect the existing task runner (turbo, nx) and its documented tasks.
- Respect `.npmrc` / `.yarnrc.yml` (registry, `node-linker`, Plug'n'Play). Never edit them as a side effect; a `.pnp.cjs` workspace is valid, not broken.
- Never assume a framework or entry point from source files alone (AGENTS.md §1.2).

## 2. Command map

Use only the column for the detected manager; never mix managers.

| Goal | npm | pnpm | yarn | bun | deno |
|---|---|---|---|---|---|
| Install deps *(plan-approved)* | `npm install` | `pnpm install` | `yarn install` | `bun install` | `deno cache` (or documented `deno install`) |
| Add a dependency *(plan-approved; show in diff)* | `npm install <pkg>` | `pnpm add <pkg>` | `yarn add <pkg>` | `bun add <pkg>` | `deno add npm:<pkg>` |
| Run a script | `npm run <script>` | `pnpm <script>` | `yarn <script>` | `bun run <script>` | `deno task <script>` |
| Run tests | `npm test` | `pnpm test` | `yarn test` | `bun test` | `deno test` |
| Run a file | `node <file>` | `node <file>` | `node <file>` | `bun <file>` | `deno run <file>` |
| Local binary (tsc, eslint, vite, next…) | `npx --no-install <bin>` | `pnpm exec <bin>` | `yarn <bin>` | `bun x <bin>` | built-in subcommands |

- Prefer project-local binaries over globals: never call a global `tsc`, `eslint`, `vite`, or `next` when the project pins its own.
- A one-off download (`npx <pkg>`, `pnpm dlx`, `yarn dlx`, `bun x <pkg>`) is a network install and needs plan approval; `npx --no-install` must fail rather than fetch.
- Workspace filtering when the task targets one package: `npm run <script> -w <pkg>`, `pnpm --filter <pkg> <script>`, `yarn workspace <pkg> <script>`, `bun run --filter <pkg> <script>`.

## 3. Installs and dependencies

- Do not install dependencies or access the network unless the user-approved plan authorizes exactly that (AGENTS.md §1.2, §4).
- `node_modules/` missing or incomplete? Propose the manager's install in the plan before running anything; never delete and reinstall to "fix" an install.
- For npm, prefer `npm install`; `npm ci` deletes `node_modules/` and reinstalls from the lockfile — treat it as a rebuild and get plan approval first.
- Resolve versions from the lockfile and manifest; never hand-edit `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock*`, or `deno.lock` unless the task is exactly that.
- Every dependency added, removed, or upgraded must appear in the plan's file list and the shown diff. No blanket `npm audit fix`, `npm update`, or bulk upgrades without an approved plan.
- If a peer-dependency conflict blocks the install, report the exact conflict and ask; do not add `--force` or `--legacy-peer-deps` on your own.

## 4. TypeScript, tests, and checks

- Run the project's documented checks first: `package.json` scripts, README, `Makefile`, CI config. Typical order: type check → lint → tests → build.
- TypeScript: if `tsconfig.json` exists, run the documented type-check script; otherwise the local `tsc --noEmit` via §2. Do not change `tsconfig.json` or introduce new TS tooling without a plan approval.
- Tests: the documented script first. Do not guess a runner (jest, vitest, mocha, node:test) from source files — read `jest.config.*` / `vitest.config.*` or the `test` script.
- Lint and format only when the project already has it configured (eslint, biome, prettier), using the documented script; do not add new lint tooling or config without a plan approval.
- Establish the baseline before implementing: run the relevant checks before and after the change, and report failing documented checks before proposing unrelated fixes (AGENTS.md §1.2).

## 5. Web apps: startup and probe

- Find the documented dev-server command (`next dev`, `vite`, `webpack serve`, `ng serve`, `astro dev`, `remix vite:dev`, a `dev` script, …). Do not infer one from the framework or from source files alone.
- Start it bound to `127.0.0.1` on the fresh `{port}` supplied by the workspace runner. Prefer the documented script plus explicit flags: `next dev -H 127.0.0.1 -p {port}`, `vite --host 127.0.0.1 --port {port}`, `webpack serve --host 127.0.0.1 --port {port}`. If the tool reads `HOST`/`PORT` env vars instead, set `HOST=127.0.0.1` and `PORT={port}`.
- Then verify the supplied loopback `probe_url` before reporting success. Start a fresh server for each run; do not rely on one that is already running (AGENTS.md §1.2).
- Build and production checks only when the task or the documented checks require them: the `build` script, then the documented `start`/`preview` command.
- If no local web startup path is documented or discoverable, report that and ask before inventing commands or configuration.

## 6. Hard rules

- Never delete or recreate `node_modules/`, `.pnp.cjs` / `.pnp.loader.mjs`, or any lockfile (AGENTS.md §3.4).
- Never switch or mix package managers — not even between workspaces in one repository.
- Never install globally (`npm install -g`, `pnpm add -g`); the project's local environment is the only target.
- Never scaffold (`create-next-app`, `npm create <pkg>`, `npm init <pkg>`) inside an existing project without an approved plan.
- Never bypass script policies or lockfile guarantees (`--ignore-scripts`, `--no-package-lock`, `--frozen-lockfile=false`) on your own judgment.
