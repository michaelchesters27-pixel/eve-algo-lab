# EVE Command Centre v3.0.2 — Clean Legacy Test History

## Fixed

- The Legacy Fixed Ladder workspace now opens blank instead of automatically displaying the most recent stored test.
- Old results are available only through an explicit **View previous tests** archive control.
- Archived runs are clearly labelled with their date, resolution and stored-result status.
- Selecting an archived run adds an **ARCHIVED TEST** warning and prevents it being mistaken for a new result.
- Starting a new test immediately clears any archived selection and shows only the new run.
- Basket results remain hidden until a current test completes or a specific archived test is deliberately selected.
- The M5-versus-M1 comparison is now inside the archive rather than appearing as current evidence.
- Active queued/running tests can still be restored safely after a page refresh.

## Preserved

- Existing Supabase backtest records are retained as an archive.
- Fixed Ladder v2.61 M5 approximation and M1 replay routes are unchanged.
- All research, strategy, validation, MT5 generation and demo-testing functions are unchanged.

## Database and variables

No Supabase SQL, Railway variable or Netlify variable changes are required.
