# EVE Algo Lab v1.6.1 — deployment guide

Use the existing **eve-algo-lab** GitHub repository. Do not upload this package to the separate trading-bot repository.

## Replace the GitHub repository contents

1. Unzip `EVE-ALGO-LAB-v1.6.1-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing **eve-algo-lab** GitHub repository with everything inside that folder.
4. Commit the replacement to `main`.
5. Wait for Railway and Netlify to redeploy automatically.
6. Open EVE and press **Ctrl + F5** once so the browser loads the new CSS.

## Do not run SQL again

When upgrading from v1.6.0, no Supabase SQL is required. Existing autonomous-learning tables and data are preserved.

## Do not change variables

No Railway or Netlify variables need added or changed.

## Expected result

The Live Data price remains on one line and the whole card fits cleanly at normal desktop and laptop widths. Autonomous learning continues exactly as before.
