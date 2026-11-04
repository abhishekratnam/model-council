# Rust project guidance

**Precedence:** `AGENTS.md` defines shared project discovery, baseline checks,
plan mode, and approvals (sections 1.1, 1.2, and 4). This file adds
Rust-specific guidance. `AGENTS.md` takes precedence if instructions conflict,
unless this file is stricter. The workspace runner supplies `{port}` and
`probe_url`; use those values as given.

## 1. Identify the environment

Before running commands, inspect `Cargo.toml`, workspace members, `Cargo.lock`,
and the README to identify the package, binaries, features, and documented
commands. Use the first applicable row below:

| Project files | Layout | Command execution |
|---|---|---|
| `Cargo.toml` with a `[workspace]` section | Workspace with member crates | From the workspace root; use `-p <package>` for the crate the task targets |
| `Cargo.toml` with a `[package]` section | Single crate | From the crate root |
| No `Cargo.toml` | Undetermined | Stop; propose cargo initialization in the plan and ask |

- Read the `edition` and `rust-version` fields, the `[[bin]]` sections, and the
  `[features]` table. Binary names come from `[[bin]]` entries or `src/bin/`;
  a crate can produce several. Do not assume a binary name, feature flag, or
  server framework from source files alone (§1.2).
- Honor the repository's existing Cargo configuration, including
  `.cargo/config.toml` and any `rust-toolchain.toml`. If a pinned toolchain is
  missing locally, rustup fetches it from the network on first use — that is a
  network action and needs plan approval. If the local toolchain is older than
  the `rust-version` (MSRV), report the mismatch and ask.
- Never delete or recreate `target/` or `Cargo.lock`.

## 2. Commands

Prefer documented Makefile, justfile, or xtask targets when they wrap the
commands below.

| Goal | Command |
|---|---|
| Fast baseline check (no codegen) | `cargo check` |
| Build everything | `cargo build` |
| Build one package | `cargo build -p <package>` |
| Run a binary *(documented name only)* | `cargo run --bin <name>` |
| Pass arguments to a binary | `cargo run --bin <name> -- <args>` |
| Run all tests | `cargo test` |
| Run one package's tests | `cargo test -p <package>` |
| Run a single test | `cargo test <test_name>` |
| Check formatting | `cargo fmt --all -- --check` |
| Apply formatting *(include reformatted files in the diff)* | `cargo fmt --all` |
| Lint *(when the project uses it, for example in CI)* | `cargo clippy` |
| Enable a feature *(documented flags only)* | `--features <name>`, `--no-default-features` |

- With more than one binary, `cargo run` without `--bin` is a guess; always
  pass the documented `--bin <name>`.
- `cargo fmt` rewrites files; check first, then apply, and show the reformatted
  files in the diff.

## 3. Dependencies

- Do not fetch crates or access the network unless the approved plan explicitly
  authorizes it (sections 1.2 and 4). `cargo add`, `cargo update`, and the
  first build's crate downloads from crates.io are all network actions.
- Resolve versions from `Cargo.toml` and `Cargo.lock`. `Cargo.lock` is
  generated; change it only through `cargo add` and `cargo update`, never by
  hand-editing (§3.2 of AGENTS.md).
- Enable only documented feature flags; do not turn features on to make a
  build pass without an approved plan.
- `cargo clean` deletes `target/`; treat it as a rebuild and get plan approval
  first. Never delete or recreate `target/` as a fix.
- Respect `.cargo/config.toml` (registries, mirrors, target settings) as
  found; do not change it as a side effect.
- List every `Cargo.toml`, `Cargo.lock`, or `target/`-affecting change in the
  plan's file list and include it in the diff.

## 4. Tests and checks

- Start with the project's documented checks in the README, Makefile or
  justfile targets, or CI configuration; that is normally `cargo test` or a
  narrower package-specific test when the workspace structure calls for it.
- If none are documented, run the baseline ladder: `cargo check`, then
  `cargo fmt --all -- --check`, then `cargo test`. Run `cargo clippy` too when
  the project uses it.
- Use `cargo test -p <package>` for the crate the task touches when the
  workspace is large; run the documented full check before reporting
  completion.
- Run relevant checks before and after implementation. Report baseline
  failures before proposing unrelated fixes (§1.2).
- Do not add new tooling or configuration (clippy lints, cargo-deny, audit
  tooling) without plan approval.

## 5. Web applications

- Identify the documented binary and its options from the README, `[[bin]]`
  sections, or Makefile/justfile targets. Do not assume a server framework or
  infer command-line flags from dependencies.
- Bind the server to `127.0.0.1` on the fresh `{port}` supplied by the
  workspace runner, using the binary's documented flag or environment variable
  (for example `--bind 127.0.0.1:{port}`, `LISTEN_ADDR=127.0.0.1:{port}`, or
  the framework's documented env vars). Do not invent configuration values;
  if the address or port is hardcoded and not configurable, report that and
  ask.
- Verify the supplied `probe_url` before reporting success. Start a fresh
  server for each run; do not rely on an existing process (§1.2).
- If no local startup path is documented or discoverable, report that and ask
  before inventing commands or configuration.
