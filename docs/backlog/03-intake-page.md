# 03 — request-a-map intake page

The user-facing front door. Closes the loop on the asmr pipeline: someone submits a hack, it comes out the other side as a draft world for staff review. Pairs with asmr `extractor/09` (which is the spec from asmr's side — read it first).

**Don't start until `01` is solid.** A flaky loader behind a public intake page is worse than no page at all.

## Shape (sketch — settle with the user before building)

- **Submission.** Either a Metroid Construction (or romhack.net) link, or a direct ROM upload. Basic validation that the result is SM-based before queuing.
- **Patch application.** If the submission is a link/patch, apply it to a clean SM ROM transiently. **Never store ROMs or patches** — `LEGAL.md` analogue applies; process in a temp dir, delete after. Either the user supplies the base ROM on the server, or the submitter uploads a pre-patched ROM (decide with the user).
- **Queue + run.** Background job runs asmr's deterministic pipeline → bundle → `01`'s loader. Surface progress / failure to the submitter (job ID page, polling, whatever fits the unrest stack).
- **Review.** Result lands as a `hidden=True` world. Staff finish the manual steps from `02` and flip `hidden=False` deliberately.
- **Dedup.** Don't re-ingest the same hack twice. Allow staff to re-run a previously-ingested hack when the pipeline improves (re-import overwrites, doesn't duplicate — `01`'s idempotency carries this).

## Acceptance

A non-staff user can submit a hack via the page and (eventually) see a draft world appear; staff can finish the manual steps from `02` and publish.

## Open questions for when you start

- Auth model for the page. Recent commit `7c21a40` added auth — what's the gate for submissions? Anyone signed in? Staff-only initially while we build trust in the pipeline?
- Where the asmr pipeline runs — same host as maptroid, or a separate worker? Latency/queue depth tolerance.
- Failure surfacing: how much detail to show the submitter when the pipeline errors out. Probably "it failed, staff will look" rather than dumping tracebacks.

## Non-goals

- Auto-publishing without review. The whole point of "draft world" is staff still mediate what goes live.
- Hosting ROMs or patches. Anything stored persistently is the *output* (records + rendered PNGs), never the input.
- Handling non-SM games. Dread is a separate track.
- Anything in asmr itself — pipeline lives there; this is the wrapper.
