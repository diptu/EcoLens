# Contributing to ecoLens

Thanks for your interest in making the Australian grid more legible. 💚

This project follows a [GitHub flow](https://guides.github.com/introduction/flow/)
with a `main` branch that's always deployable and short-lived feature branches.

## Ground rules

- **Be respectful.** See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- **One change, one PR.** Big PRs are hard to review and slow to land.
- **Tests first or tests with.** A PR without a test for a non-trivial
  change will be sent back.
- **Adapters, not forks.** If you're wrapping a third-party SDK (e.g.
  OpenElectricity), put it in `src/ecolens/<provider>/` and mock it in tests
  so we can swap providers later.
- **Cite your data.** Anything derived from AEMO / OpenElectricity / BoM /
  DCCEEW must keep attribution in the code, the docs, and (if you add a
  user-facing number) the response payload.

## Local setup

```bash
# Requires Python 3.11+, Node 20+, Docker 24+, uv.
git clone https://github.com/diptu/ecoLens.git
cd ecoLens
cp .env.example .env
make bootstrap     # uv sync + pre-commit install
make up            # docker compose up -d
make dbt-build     # builds the warehouse locally
make test          # runs the full test pyramid
```

## Workflow

1. **Open or claim an issue.** Use the appropriate template
   (`.github/ISSUE_TEMPLATE/`).
2. **Branch** from `main`:
   - `feat/<scope>-<short-desc>` for features
   - `fix/<scope>-<short-desc>` for bug fixes
   - `chore/<scope>-<short-desc>` for maintenance
3. **Develop** with quality gates running locally:
   ```bash
   make lint
   make type
   make test
   ```
4. **Document.** If you change user-facing behavior, update
   `docs/` and (if it's an API change) bump `src/ecolens/api/openapi.yaml`
   via `make openapi-bump`.
5. **PR.** Use the template. Link the issue. Request a CODEOWNER review.
6. **CI must be green.** A CODEOWNER must approve. Squash-merge.

## Code conventions

- **Python:** `ruff format` + `ruff check`, `mypy --strict` on `src/`,
  type hints everywhere, no `Any` in public surfaces.
- **TypeScript:** `prettier` + `eslint`, `tsc --noEmit` clean, RSC by default.
- **SQL (dbt):** snake_case models, one concept per file, every model has
  a description and at least one test on a non-nullable column.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/).
  `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`,
  `perf:`, `build:`, `ci:`.
- **ADRs:** Any architectural decision lives in `docs/adr/NNNN-title.md`
  using the [MADR](https://adr.github.io/madr/) template.

## Adding a new region

A "region" is anything with an ISO-like code we can resolve to AEMO + OE.

1. Add the region code to `src/ecolens/config.py::SUPPORTED_REGIONS`.
2. Add a dbt seed / source for the new region in
   `dbt/ecolens/models/staging/`.
3. Add an entry to the OpenElectricity fetcher in
   `src/ecolens/emissions/openelectricity.py`.
4. Add a UI selector in `frontend/components/forms/region-select.tsx`.
5. Add a smoke test in `tests/integration/test_forecast_<region>.py`.
6. Update the model card (`docs/model-card.md`) with the new training set
   statistics.

## Adding a new emissions factor source

The single source of truth is
`dbt/ecolens/seeds/emissions_factors.csv` (versioned). To add a source:

1. Open an issue with the upstream URL, licence, and methodology.
2. Add the source as a dbt seed with a `source` column.
3. Add a singular test that the new factors produce a system-level intensity
   within ±2% of the published national value.
4. Bump `factors_version` in `src/ecolens/emissions/factors.py`.
5. Update the model card.

## Release process

- Tag a release with `v<semver>` — `release.yml` builds, signs, and pushes
  images, generates the SBOM, and opens a GitHub release.
- The `Production` stage in the MLflow model registry is what the API loads.
  Promotion is gated by CI (see `docs/ml/promotion.md`).

## Getting help

- **Discussions:** for design questions.
- **Issues:** for bugs and feature requests.
- **Security:** see [`SECURITY.md`](SECURITY.md) — please do not file
  public issues for vulns.

Welcome aboard. 🌱
