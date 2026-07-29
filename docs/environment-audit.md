# Environment audit

Audit date: 2026-07-30 (Asia/Saigon)

| Tool | Status | Version / result |
|---|---|---|
| Git | Available | 2.54.0.windows.1 |
| GitHub CLI | Available | 2.96.0 |
| GitHub authentication | Connected | Account `KanaxNguyen`, repository and workflow scopes available |
| Node.js | Available | v23.11.1 |
| npm | Available | 10.9.2 |
| pnpm | Available | 11.9.0 |
| Python | Available | 3.13.14 |
| Docker | Unavailable | `docker` command was not found |
| Docker Compose | Unavailable | Cannot run because Docker is not installed |
| Figma connector | Present but file access failed | Both metadata discovery and read-only Plugin API calls returned `INVALID_ARGUMENT` for file key `OdSLKDuaAwEoQePRugRIA1` |

## Practical limits

- Dockerfiles and Compose configuration can be authored and reviewed, but a real container build cannot be claimed on this computer until Docker Desktop or Docker Engine is installed.
- The supplied Figma URL has no node identifier. Automatic page discovery was attempted with both metadata and read-only Figma APIs; both were rejected. The UI therefore uses the explicitly requested “Option 02 — Minimal SaaS” characteristics as a documented fallback, and no Figma asset is claimed as downloaded.
- GitHub authentication is active. Repository creation and push status are recorded in the build log only after the corresponding command succeeds.

