# EVE Algo Lab v2.0.1 — Strategy Lab Layout Fix

This is a focused interface repair for the Strategy Lab. All v2.0 autonomous strategy generation, testing, research and database logic remain unchanged.

## Fixed

- Added proper internal padding to the Autonomous Strategy Worker panel.
- Added proper internal padding to the Strategy Candidate Explorer panel.
- Prevented the first letters of the green section labels from being clipped by the rounded panel edge.
- Added safe minimum-width handling so long Strategy Lab headings wrap inside the card instead of pushing through its boundary.
- Added a smaller but still safe card inset on narrow screens.
- Versioned the frontend assets to force browsers and Netlify to load the corrected CSS.

## Deployment

Replace the existing GitHub repository contents with this complete folder and wait for Netlify and Railway to redeploy. Then force-refresh the browser.

No Supabase SQL or environment-variable changes are required.
