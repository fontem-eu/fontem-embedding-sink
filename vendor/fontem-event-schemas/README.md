# fontem-event-schemas

Pydantic models + JSON-schemas for entity events (package: fontem_event_schemas — to be renamed). One module per upsert event type (UpsertCompany, UpsertAuthority, UpsertContract, …). All event producers and consumers depend on this package for shape + version checking.

## Deploy

CI auto-deploys to the testing env on every merge to main. Promotion to staging / prod is **manual** — bump the version in `gitops/<env>/<service>.yaml` to land it in a given environment.

## Convention

See [/config/repos/CLAUDE.md](https://contribute.void42.internal/fontem/gitops) for workspace-wide rules (feature branches + CI gate, no direct push to main, full gate before declaring done, conventional commits).
