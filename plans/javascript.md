# JavaScript and TypeScript project guidance

- Inspect `package.json`, the package-manager lockfile, workspace configuration, and the README to identify the package manager, scripts, application entry point, and supported Node version.
- Use the lockfile's package manager and existing scripts. Run the documented tests or checks; do not install dependencies unless the user-approved plan authorizes it.
- For a web app, use the project's documented development or start script, bind to `127.0.0.1` on the fresh `{port}` supplied by the workspace runner, and use the supplied loopback `probe_url`. Pass host and port using the framework's documented flags or environment variables.
- Do not assume a framework, script name, or package manager from source extensions alone. If the startup path is unclear, report that and ask before inventing one.
