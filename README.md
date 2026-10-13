# Case Scraper

`main.py` runs a browser-based scraper for Israel's court website. It searches cases by opening date, optionally filters by case type, collects each case's details, and saves progress to a JSON file.

## Setup

Use Python 3.10 or newer. From PowerShell, open the project directory and install Playwright and its Chromium browser:

```powershell
cd C:\Users\noahd\OneDrive\Desktop\Case_Scraper
python -m pip install playwright
python -m playwright install chromium
```

An internet connection and access to the court website are required.

## Run the scraper

```powershell
python main.py
```

The script prompts for:

1. **Search date:** enter `DD/MM/YYYY`, or press Enter to use `DEFAULT_SEARCH_DATE` from `config.py` (currently `06/09/2026`).
2. **Case-type filter:** enter `10078` for תה״ג or `10071` for ת״כ, or press Enter for no filter.

Chromium opens in a visible window by default. Progress, individual case results, and final status counts appear in the terminal.

### Command-line options

| Option | Purpose | Default |
| --- | --- | --- |
| `--date DD/MM/YYYY` | Set the case-opening date to search. | Prompt for a date. |
| `--case-type-id INTEGER` | Filter using the website's case-type option value. | Prompt; blank means no filter. |
| `--output PATH` | Choose the JSON output file. | Timestamped file under `output/`. |
| `--headless` | Run Chromium without a visible window. | Visible browser. |
| `--resume PATH` | Load an existing checkpoint and save further progress to it; create it if missing. | New run. |
| `--non-interactive` | Disable prompts; a new run requires `--date`, and an omitted type means all types. | Interactive prompts. |

For example, search a date and extract all matching cases:

```powershell
python main.py --date 06/09/2026
```

This still prompts for the case-type filter. Press Enter to search without a filter.

To set every search option and choose an output file:

```powershell
python main.py --date 06/09/2026 --case-type-id 10071 --output output/results.json --headless
```

Choose one of these case-type filter values:

| Case type | Filter integer |
| --- | --- |
| תה״ג | `10078` |
| ת״כ | `10071` |

The example above uses ת״כ (`10071`). Use `--case-type-id 10078` for תה״ג. `--headless` hides the browser but does not suppress prompts for omitted search options. An invalid date also triggers a correction prompt.

## Resume and PM2

Resume an existing file without redoing completed Sides extractions:

```powershell
python main.py --resume output/results.json --headless
```

The saved date, case-type filter, and case list are reused. Pending, in-progress,
failed, and partial cases are retried, preserving previously extracted data.
An already complete checkpoint exits without launching a browser. Invalid JSON
is rejected without overwriting it. Resume loads the main JSON, not its `.tmp`
file; an interrupted save may require retrying the last case.

The included `ecosystem.config.cjs` runs one process, resumes the same checkpoint,
and restarts after five seconds on failure or unfinished cases. It stops after
all cases complete. Set the path to your existing checkpoint before starting:

```powershell
$env:CASE_CHECKPOINT = 'C:\path\to\existing\cases.json'
pm2 start ecosystem.config.cjs
pm2 logs case-scraper
```

If a process named `case-scraper` already exists, stop and remove its old PM2
entry with `pm2 delete case-scraper` before starting this configuration.
For a new checkpoint, set `CASE_DATE` to `DD/MM/YYYY` and optionally
`CASE_TYPE_ID` before starting. `CASE_PYTHON` can select the Python executable
with Playwright installed. The default checkpoint is `output/pm2_cases.json`.
Keep one process per checkpoint file. A persistent website error leaves that
case unfinished and will continue being retried on subsequent restarts.

## What main.py does

1. Reads command-line arguments and prompts for missing search settings.
2. Launches Chromium with Playwright and creates a browser context.
3. Calls `open_results_page()` and `populate_cases()` from `court_search.py` to search and collect case records.
4. Saves an initial checkpoint with all collected cases marked `pending`.
5. Processes cases sequentially. For each case, it marks the entry `in_progress`, opens the case folder, and calls `GetCaseDetails()` from `case_details.py`.
6. Saves the extracted data and status, then reuses the case page's header search for the next case. If a lookup returns a website error, closes that page and retries the same case once in a fresh page. Continues to the next case even if extraction fails.
7. Records the finish time, saves the final checkpoint, prints status counts and the output location, and closes the browser.

`main.py` extracts only Factors → Sides (`sides`) for each case. A case is
marked `completed` when this tab is collected, or `partial` if it is unavailable.
Other callers of `GetCaseDetails()` still collect all supported tabs by default.

## Saved results

By default, results are saved relative to the directory where you run the command:

```text
output/cases_YYYYMMDD_HHMMSS_microseconds.json
```

The JSON contains `started_at`, `search_date`, `case_type_id`, and a `cases` list. A normally finished run also has `finished_at`. Run timestamps are stored in UTC; the default filename uses local time.

Each entry in `cases` contains:

- `status`: the extraction status described below.
- `error`: `null`, or an exception type and message when extraction fails.
- `case`: the case type, number, name, interest, court, case status, internal `ID`, and extracted `details.tabs`.
- `missing_tabs`: tab keys that were not collected, when the detail call returns normally.

The entry's extraction `status` is separate from the court's case status stored inside `case.status`.

| Extraction status | Meaning |
| --- | --- |
| `pending` | Collected from search results but not yet processed. |
| `in_progress` | Detail extraction started; an interrupted attempt may retain this status. |
| `completed` | All expected tab keys were collected. |
| `partial` | Extraction returned, but one or more expected tabs were missing. |
| `failed` | Opening the folder or extracting details raised an exception. Previously collected details are retained. |

`completed` indicates that all expected tabs are present; it does not guarantee that every tab contains records.

The checkpoint is updated before and after each case. `save_checkpoint()` writes a temporary `.tmp` file and then replaces the JSON file after the write finishes. Output directories are created automatically. If you specify an existing output filename, its contents are replaced.

Saved checkpoints preserve progress for inspection, but the script does **not** automatically resume or retry a previous run. Errors during the initial search or checkpoint writes can stop the run.

## Average cases per day

```powershell
python Average_Case_Per_Day_Counter.py
```

This samples 100 distinct random dates from the last ten years, through yesterday,
including weekends and holidays. For example, running on October 5, 2026 samples
from October 5, 2016 through October 4, 2026. It counts unique cases across all
result pages without opening case details, prints each day's count, then prints
the total and average. Zero-case days are included in the average.
For each day, it writes the general search-result data (type, number, name,
interest, court, status, and internal ID) to a temporary JSON file on the same
filesystem as the summary, then deletes that file before proceeding. Temporary
records are also cleaned up if a write fails.
The browser stays on the same search page between dates. If the website returns
to its homepage, the script reopens the date-search menu and retries the same date.

Counts and the summary are checkpointed after each day to a timestamped JSON file
under `output/`. Each day's `elapsed_seconds` includes searches, retries,
collection, JSON serialization, writing, and deleting the daily records, and is
printed alongside its count. The overall timer also includes intermediate
summary checkpoint writes. Elapsed seconds are saved as
`elapsed_seconds` and printed at the end in hours, minutes, and seconds.
Searches are retried up to three times. Failed days are recorded
separately and excluded from the average; an incomplete run exits with status 1.

Optional flags: `--seed 42` to reproduce the sample on the same run date,
`--case-type-id INTEGER` to filter cases, `--output PATH` to choose the JSON file,
and `--headless` to hide the browser. Without a case-type filter, all types are counted.

## Per-case time and storage measurements

First generate the input from one random completed day in the last ten years:

```powershell
python Collect_Case_Test_Input.py
```

This collects all unique case rows across every result page, including case type,
number, name, interest, court, status, and internal ID. It replaces
`Case_Test_Output.json` after successful collection and prints pagination progress.
Failed searches retry the same date up to three times and preserve the old input
if collection fails. Use `--headless`, `--seed INTEGER`, or `--output PATH` as needed.
If the selected date has too few cases, rerun for another date or reduce the
consumption script's sample size.

```powershell
python Average_Comsumption_Per_Case_Finder.py
```

Enter the number of cases to extract, or press Enter for 10. The script randomly
selects unique records from `Case_Test_Output.json`, opens each case, and runs all
implemented detail-tab extractors. The input must contain at least as many unique
cases as the requested sample size.

The input can be a list of case-number strings, an object containing a `cases`
list of case records, or an existing `main.py` output. For example:

```json
{"cases": ["12345-09-26", "67890-09-26"]}
```

```powershell
python Average_Comsumption_Per_Case_Finder.py --count 5 --headless
```

Each case's time includes folder lookup and detail extraction. Storage is the
actual byte size of its UTF-8 JSON file, excluding measurement-summary overhead;
it does not measure downloaded documents or browser storage. Results print after
each case. Final averages include completed and partial cases and exclude failed
attempts. Missing tabs and failures are recorded explicitly.

Per-case files and `summary.json` are saved under a timestamped
`output/case_consumption_.../` directory. Optional flags are `--input PATH`,
`--count INTEGER` (or `-x INTEGER`), `--seed INTEGER`, `--output-dir PATH`, and
`--headless`. Failed extractions preserve partial data and do not stop later cases;
a run with failed cases exits with status 1.

## Main supporting files

| File | Responsibility |
| --- | --- |
| `main.py` | Command-line interface, browser lifecycle, sequential extraction, and JSON checkpoints. |
| `court_search.py` | Court website navigation, search filters, and case-result collection. |
| `case_details.py` | Opens case folders and scrapes individual detail tabs. |
| `grid_reader.py` | Reads paginated website grids. |
| `case.py` | Defines the case data structure. |
| `config.py` | Website URL, default search date, and browser-operation timeouts. |

`main.py` saves to JSON; it does not write to the database defined under `sql/`.

## Offline pipeline checks

```powershell
python -m unittest tests.test_pipeline
```

These checks use mocked browser operations to verify pipeline behavior without contacting the court website.
