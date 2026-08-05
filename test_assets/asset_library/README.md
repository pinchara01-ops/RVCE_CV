# Local demo asset library

This folder is intentionally for local test media only.  The video files in
`media/` are ignored by Git; `manifest.json` is the authoritative record of
their source, duration, geographic context, and licence/permission status.

Only download an asset when its manifest entry is marked `approved_local_use`.
Do not add ordinary YouTube uploads here unless a recorded licence or written
permission is added to the manifest first.

The first two intended demo flows are:

1. A public-domain, 20-minute police dashcam extract that exercises road,
   vehicle, and incident retrieval.
2. A CC BY 4.0 MEVA fixed-camera sequence assembled from four adjacent
   five-minute clips around an annotated `person_steals_object` event.

Any composed asset must retain source attribution and indicate that it was
trimmed or concatenated.
