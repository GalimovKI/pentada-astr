# GPU dependency reuse and successful dev deployment

Code: `ede4f473a794ef7411569e075019c9ae2a57eece` on origin/dev; packaging commit `72a71f9`. Fresh teammate revision `596e9e5e306916e0d939fa90f75a5a2f82fde5b1` was merged and preserved. Extends finding `20261121T211917Z-30ed3162`.

## Finding and implementation

Run [44951289621](https://github.com/GalimovKI/pentada-astr/actions/runs/44951289621) hit the 40-minute deploy limit while filling the cold GPU dependency cache. During this investigation, PyPI address 151.101.64.223:443 stalled; three other resolved addresses connected in about 45–55 ms. This is a point-in-time network observation.

The Dockerfile optionally copies only the installed venv from a trusted prior image, retaining the pinned Python base. Locked uv reconciliation removes the old application and only fetches missing/changed requirements. A separate build-tools layer prepares build requirements; source wheel construction is offline with Docker network disabled. The fresh wheel is installed in runtime. Model stages remain independent. Compose and .env.example expose the optional seed, BUILD_CACHE.md documents operation, and .dockerignore excludes macOS AppleDouble files. CPU defaults work without a seed.

On the academic rootless Docker host, the working image `pentada-mailsearch-backend:dev-d2ca7bd5b401f4ca6805f3f8e9772db0267a067f` was tagged `pentada-mailsearch-dependencies:py312-cu130-d2ca7bd`. Offline locked reconciliation took 0.6 seconds and only uninstalled the old app, without CUDA downloads. Dev shared environment now sets `BACKEND_DEPENDENCIES_SEED_IMAGE` to that tag. It was updated atomically under the deploy lock; backup: `/home/rusikye/pentada-astr-dev/backups/20261121T222551Z-dependency-seed/.env.production`. Secrets are excluded from this record.

Build tools were warmed once with `docker build --target build-tools --output type=cacheonly --add-host pypi.org:151.101.128.223 --add-host files.pythonhosted.org:151.101.128.223 --build-arg DEPENDENCIES_SEED_IMAGE=pentada-mailsearch-dependencies:py312-cu130-d2ca7bd --build-arg INCLUDE_MINILM=1 --build-arg MINILM_DEVICE=cuda -f infra/docker/backend.Dockerfile .`. No static DNS override was committed or persisted; normal CI used normal DNS.

## Verification and limits

- Final merged GPU image built on academic host. 79 backend tests passed with isolated PostgreSQL 17.12, no skips; actual CUDA profile check passed. Logs attached.
- 11 infra tests passed; Compose GPU/seed config validated. Local default CPU image and mailsearch validate passed.
- A fully offline CPU build from an older app seed installed a new source marker and excluded uv/build tools from runtime, verifying source replacement.
- An initial manually tarred test context contained macOS AppleDouble migration files and failed. Scratch files were cleaned, ignore rule added, final source transferred via git archive, and all 79 tests passed. Production was unaffected.
- Final CI [44956816247](https://github.com/GalimovKI/pentada-astr/actions/runs/44956816247) succeeded: deploy 22:28:28–22:29:52 UTC on 2026-11-21, **84 seconds**. Captured BuildKit log showed dependency and build-tools RUN steps CACHED. Academic dev current symlink matches the final full SHA.
- After deployment, HTTPS /dev/, /dev/api/v1/mailboxes, /main/, /main/api/v1/mailboxes on smartmail-hackaton.ru all returned 200.

This duration used a prevalidated image and warm caches on the same academic host; it is not a cold-build benchmark or a guarantee. Changed locked requirements or missing caches/seed can still require downloads; retain the trusted seed tag. Model pins, weights and lock versions were not changed by this fix. No search-quality eval was repeated; teammate search changes were preserved and backend-tested. Early packaging checks used uncommitted implementation; final merged validation and CI used the published commit above.

To reproduce the candidate image from that commit on the academic Docker host: `docker build --build-arg DEPENDENCIES_SEED_IMAGE=pentada-mailsearch-dependencies:py312-cu130-d2ca7bd --build-arg INCLUDE_MINILM=1 --build-arg MINILM_DEVICE=cuda -f infra/docker/backend.Dockerfile -t pentada-mailsearch-backend:dependency-seed-check .`. Evidence logs and compact CI metadata accompany this record.
