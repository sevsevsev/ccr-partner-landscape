# SY26-27 CCR Partner Landscape

A Streamlit app for the School District of Philadelphia's College and Career Readiness partner programs.
It reads the shared SY2627 CCR Program Data Google Sheet (cached for 10 minutes) and shows where partners
overlap, which district high schools have no partner listed, and who could coordinate with whom.

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.

On Windows, keep the project (or at least the virtual environment) on a short path such as `C:\dev\ccr-partner-landscape`.
Deep folder trees push pyarrow's DLL path past the Windows path limit and `st.dataframe` then fails to import it.

## Where the data comes from

| Data | Source | How it updates |
|---|---|---|
| Programs, Enrollment by School and Grade, Issues | The shared Google Sheet, read through its public CSV endpoint (the sheet must stay shared as "Anyone with the link") | Every 10 minutes while the app is open, or the **Refresh data now** button in the sidebar |
| District high school list, enrollment, locations | `data/district_schools.json`, built from the City of Philadelphia's public list of schools (downloaded 2026-11-12), matched by ULCS code, the district's school ID number | Replace the file to update |
| City boundary | `data/philly_boundary.json`, simplified from the same open data | Static |

To point the app at a different sheet, set `sheet_id` in `.streamlit/secrets.toml`:

```toml
sheet_id = "1q7qPxJAIGQBtGbj31_jmAAo5Gb1ULTJzUYticiylM90"
```

## Known data repairs

- Philadelphia Academies, Inc. rows in the shared sheet are shifted one column left (the comma in the name was read as a
  column break). `ccr_data.py` shifts them back and recovers each school name from its ULCS code.
- Rows whose grade counts are all multiples of 5 are marked with an asterisk as likely planned group sizes rather than
  counts of actual students.
- In the city dataset, a duplicate Olney row and an implausible enrollment for The LINC were corrected when building
  `district_schools.json`.

## Deploy

The app has no secrets and no database, so it runs anywhere Streamlit does. On
[Streamlit Community Cloud](https://streamlit.io/cloud): push this folder to a GitHub repository, create an app, and
point it at `app.py`. `requirements.txt` is picked up automatically.

## Test the data layer

```bash
python tests/test_data.py
```

The test builds the landscape from the CSV snapshots in `tests/fixtures` (saved from the sheet on 2026-11-12) and
checks the headline figures.
