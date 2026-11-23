# @newcad/protocol

Shared shapes between the engine and the app, as JSON Schema.

- `schemas/study.schema.json`: a simulation study (`studies/<id>.yaml` in a project repository).

The engine's Pydantic models are the source for now (`engine/scripts/export_schemas.py` writes these
files and a test fails when they drift). The app's TypeScript types in `apps/web/src/engine/types.ts`
mirror them; generating those types from the schemas is a follow-up.
