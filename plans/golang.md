# Go project guidance

**Precedence:** `AGENTS.md` defines shared project discovery, baseline checks,
plan mode, and approvals (sections 1.1, 1.2, and 4). This file adds Go-specific
guidance. `AGENTS.md` takes precedence if instructions conflict, unless this
file is stricter. The workspace runner supplies `{port}` and `probe_url`; use
those values as given.

## 1. Identify the environment

Before running commands, inspect `go.mod`, `go.work`, the package layout,
Makefiles, and the README to identify the module, the application entry point,
and the documented commands. Use the first applicable row below:

| Project files | Layout | Command execution |
|---|---|---|
| `go.work` with multiple `go.mod` files | Multi-module workspace | From the module the task targets; respect `go.work` |
| Single `go.mod` with `vendor/` | Vendored module | From the module root; builds use `-mod=vendor` automatically |
| Single `go.mod` | Standard module | From the module root |
| No `go.mod` | Undetermined | Stop; propose module setup in the plan and ask |

- Read the `go` and `toolchain` directives in `go.mod` for the required Go
  version and use the repository's existing Go version. If the local toolchain
  is older, report the mismatch and ask; do not let the toolchain auto-download
  a new Go version without plan approval (`GOTOOLCHAIN=auto` fetches from the
  network).
- Locate the entry point from the README, Makefile, or CI configuration
  (commonly `cmd/<name>/main.go`). Do not assume `main` is at the repository
  root, and do not infer it from file names alone (§1.2); a repository may
  contain several `package main` programs.
- Run commands from the module directory the task targets in multi-module
  repositories. Never delete or recreate `vendor/`, `go.mod`, or `go.sum`.

## 2. Commands

Go needs no virtual environment or package runner; run the `go` command
directly from the module. Prefer documented Makefile or CI targets when they
wrap the commands below.

| Goal | Command |
|---|---|
| Build everything (fast baseline) | `go build ./...` |
| Build one binary *(documented path only)* | `go build -o <name> ./cmd/<name>` |
| Run a program | `go run ./cmd/<name>` |
| Run all tests | `go test ./...` |
| Run one package's tests | `go test ./<package> -run TestName` |
| Vet | `go vet ./...` |
| Check formatting | `gofmt -l .` |
| Apply formatting *(include reformatted files in the diff)* | `go fmt ./...` |
| Lint *(only if already configured, for example `.golangci.yml`)* | The project's documented lint target |
| Add or update a dependency *(plan approval required)* | `go get <module>@<version>`, then `go mod tidy` |
| Refresh `vendor/` *(plan approval required; only if `vendor/` exists)* | `go mod vendor` |

- `go run` and `go build` need an explicit package path when the repository
  has more than one `package main`.
- `gofmt` and `go fmt` rewrite files; check first, then apply, and show the
  reformatted files in the diff.

## 3. Dependencies

- Do not fetch modules, download toolchains, or access the network unless the
  approved plan explicitly authorizes it (sections 1.2 and 4). `go get`,
  `go mod tidy`, `go mod download`, and toolchain auto-download are all
  network actions.
- Resolve versions from `go.mod` and `go.sum`. They are generated files; change
  them only through `go get` and `go mod tidy`, never by hand-editing.
- When `vendor/` exists, builds use it automatically; do not delete it or build
  around it. Refresh it only with `go mod vendor` under an approved plan.
- Respect `GOPROXY`, `GOPRIVATE`, and related environment settings as found;
  do not change them as a side effect.
- Do not run `go clean -modcache` or `go clean -cache`. Those caches live
  outside the repository and are shared with other projects.
- List every `go.mod`, `go.sum`, or `vendor/` change in the plan's file list
  and include it in the diff.

## 4. Tests and checks

- Start with the project's documented checks in the README, Makefile targets,
  or CI configuration; that is normally `go test ./...` or the narrower
  package-specific test the project uses.
- If none are documented, run the baseline ladder: `go build ./...`, then
  `go vet ./...`, then `go test ./...`.
- Use `go test ./<package>` for the package the task touches when the full
  suite is large, and `-count=1` when a fresh run is required; run the
  documented full check before reporting completion.
- Run relevant checks before and after implementation. Report baseline
  failures before proposing unrelated fixes (§1.2).
- Use lint or static-analysis tools only when the project already configures
  them. Do not add tooling without plan approval.

## 5. Web applications

- Find the documented development-server command in project documentation,
  Makefiles, or scripts, and run the entry point it names. Do not infer a
  command from the framework or from source files alone.
- Bind the server to `127.0.0.1` on the fresh `{port}` supplied by the
  workspace runner, using the app's documented flag or environment variable
  (for example `-addr 127.0.0.1:{port}` or `PORT={port}`). Do not invent
  configuration values; if the address or port is hardcoded and not
  configurable, report that and ask.
- Verify the supplied `probe_url` before reporting success. Start a fresh
  server for each run; do not rely on an existing process (§1.2).
- If no local startup path is documented or discoverable, report that and ask
  before inventing commands or configuration.
