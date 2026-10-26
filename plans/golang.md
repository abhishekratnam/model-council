# Go project guidance

- Inspect `go.mod`, `go.work`, package layout, Makefiles, and the README to identify the module, application entry point, and documented commands.
- Use the repository's existing Go version and scripts. Run the documented checks, normally `go test ./...` or the narrower package-specific test used by the project.
- For a web app, use its documented server command, bind to `127.0.0.1` on the fresh `{port}` supplied by the workspace runner, and use the supplied loopback `probe_url`.
- Do not assume `main` is at the repository root or invent configuration values. If the startup path is unclear, report that and ask before proceeding.
