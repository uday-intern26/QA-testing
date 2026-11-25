# AIJewel Earring Earlobe Alignment QA

Local QA framework for AIJewel virtual try-on. It answers one question: when a virtual earring is shown on a user, is the **attachment point** actually on the earlobe?

The decision is geometric. Image similarity and Applitools are secondary and never override the anchor check.

## Three layers

1. **Frame selection** — extract frames, drop blur, duplicates, missing faces, and unstable poses.
2. **Earlobe + earring anchor detection** — estimate the earlobe from the MediaPipe ear contour, and read the earring attachment point from the try-on debug anchor.
3. **Placement validation** — compare those normalized points, score every frame, then apply pass rate and consecutive-failure rules.

Internal pieces (frame selector, earlobe detector, earring detector, placement validator, temporal validator, visual comparison, test runner, report writer) stay separate. The dashboard groups them into the three layers above.

## Run locally

```bash
docker compose up --build
```

- Dashboard: http://localhost:3000
- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs

Copy `.env.example` to `.env` when you want to override thresholds. The compose file already supplies defaults, and it does not use AWS, Kubernetes, or a remote database. SQLite and captured media stay under `data/`.

Without Docker, from `backend/`:

```bash
pip install -r requirements.txt
playwright install chromium
python scripts/download_model.py
uvicorn app.main:app --reload --port 8000
```

From `frontend/`:

```bash
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` for the dev server.

## Tester workflow

1. Open the dashboard and enter the public Amplify URL, username, and password.
2. Click **Validate Application**. Playwright opens the page, logs in, and returns a screenshot. The password is not stored, logged, or returned.
3. Save the application. Only the URL and username are kept.
4. Upload one or more reference images (PNG, JPG, JPEG, WEBP). The reference stores a **relative** placement vector: earring anchor minus earlobe anchor, divided by ear width.
5. Configure the test: jewellery id, ear side, FPS (1, 2, 5, or 10), confidence, and pass/fail thresholds.
6. Run the test and enter the password again. It lives only for that execution.
7. Watch Layer 1, Layer 2, and Layer 3. Open any frame to see the earlobe dot, earring attachment dot, placement ellipse, and distance.
8. Download the JSON report. A manual review can be recorded on a frame; it does not replace the automated result.

`Video/File` mode analyzes a local recording plus an optional anchor sidecar, so the geometry pipeline can run with no network. Desktop automation has an adapter boundary and returns a clear “not implemented” error.

## Preferred earring anchor

Do not use the bounding-box center of the jewellery. The try-on app should publish the attachment transform projected through the camera.

Browser bridge:

```javascript
window.__AIJEWEL_QA__ = {
  jewelry_id: "E123",
  jewelry_type: "earring",
  left: { x: 0.423, y: 0.371, visible: true, rotation: 3.2, scale: 1.02 },
  right: { x: 0.578, y: 0.371, visible: true, rotation: -2.1, scale: 1.02 }
};
```

Or `GET /debug/tryon-state` with the same shape. Coordinates are normalized to the try-on viewport, `0.0` to `1.0`, origin at the top left.

`unity/EarringQAAnchorProvider.cs` projects the attachment transforms. `unity/AIJewelQA.jslib` publishes that JSON onto `window.__AIJEWEL_QA__` for a WebGL build.

If the debug anchor is missing, a fallback detector runs (template match against the reference attachment, then a local contrast blob). The point it returns is the location nearest the earlobe, not the blob center. Confidence is lower, and the report says the debug anchor was unavailable.

## Placement rule

```text
dx = earring_x - earlobe_x
dy = earring_y - earlobe_y
normalized_distance = hypot(dx, dy) / ear_width
```

With `zone_y_scale` at `1`, that is the spec formula. The allowed region is an ellipse (a circle at the default scale) around the earlobe:

- `normalized_distance <= pass_threshold` and confidence is high enough → PASS
- up to `fail_threshold` → WARNING
- beyond that, or a missing anchor, or low confidence → FAIL

The whole capture passes only when the pass rate and the maximum consecutive failures stay inside the configured limits, and both anchors were found for every required ear. Left and right are scored separately. If either side fails, the overall result fails.

Thresholds come from the test configuration and the environment defaults. They are not hard-coded in the validator.

## Applitools

Leave `APPLITOOLS_ENABLED=false` for a fully local run. OpenCV SSIM, a perceptual hash, and a normalized difference are still recorded as informational visual metrics. They do not decide anatomical alignment.

## Tests

```bash
cd backend
pytest
```

Unit tests cover distance, normalization, the placement zone, earlobe landmark handling, pass rate, consecutive failures, and reference vector comparison. The integration test runs a local video through frame extraction, landmarks, the debug anchor, placement, and the final PASS/FAIL report.

## Layout

- `backend/app/api` — thin FastAPI routes
- `backend/app/services` — test runner and the three layers
- `backend/app/cv` — landmarks, ear geometry, overlays
- `backend/app/adapters` — Playwright and the try-on port
- `frontend` — QA dashboard
- `data/` — references, captures, frames, results, reports
