# Rust project guidance

- Inspect `Cargo.toml`, workspace members, `Cargo.lock`, and the README to identify the package, binaries, features, and documented commands.
- Use the repository's existing Cargo configuration. Run the documented checks, normally `cargo test` or a narrower package-specific test when the workspace structure calls for it.
- For a web app, identify the documented binary and options, bind it to `127.0.0.1` on the fresh `{port}` supplied by the workspace runner, and use the supplied loopback `probe_url`.
- Do not assume a binary name, feature flag, or server framework. If the startup path is unclear, report that and ask before inventing one.
