# DataDownloader

Environmental data downloader for ecological restoration work. Pull sites
and time series from **USGS Water Data**, **Portland BES Aquarius**, and
**NRCS SNOTEL** through one interface — or use the Streamlit GUI to
discover sites on a map and export CSV / SQLite.

## Requirements

- Windows + PowerShell (use `;` between commands, not `&&`)
- Python / conda env with `requests`, `pandas`, `python-dotenv`
- A `.env` file in this folder (never commit it):

```env
AQUARIUS_BASE_URL=...
AQUARIUS_USERNAME=...
AQUARIUS_PASSWORD=...
USGS_API_KEY=...          # optional; ~1000 req/hr with key vs ~50 without
OUTPUT_DIRECTORY=...
```

## Backend (library + live tests)

```powershell
cd data-downloader
python tests\hammer_test.py          # all three sources (~30 s)
python tests\hammer_test.py usgs     # usgs | aquarius | snotel
```

Example (Python):

```python
from data_sources import create_source, list_sources

for desc in list_sources():
    print(desc.key, desc.display_name)

usgs = create_source("usgs")
sites = usgs.get_sites(state="OR", site_ids=["14211400"])
params = usgs.available_parameters_dataframe(["14211400"])
```

## Streamlit GUI

Install GUI extras into the **same** env you use to run Streamlit
(if Aquarius fails with `No module named 'dotenv'`, you're probably on
base miniforge — install the requirements there or activate your project env):

```powershell
cd data-downloader
pip install -r requirements-gui.txt
streamlit run gui\app.py
```

Browser opens at `http://localhost:8501`.

### Typical workflow

1. Pick a source in the sidebar (USGS / Aquarius / SNOTEL).
2. **Find sites** — state / site IDs / USGS agency+type, **or**
   draw a box, **or** upload a shapefile ZIP.
3. Narrow with **Include / Exclude / Search** (no extra API calls).
4. Click map pins or use **Sites to inspect** → **Show available parameters**.
5. Under **Download**, pick series + dates → **Download data**.
6. Save as **one CSV/SQLite** or **one file per series (ZIP)**.

### Quick test sites

| Source | Example |
|---|---|
| USGS | `14211400` (Johnson Creek) — use Agency `USGS`, Site type `ST` |
| Aquarius | Find sites, Include `HYDRA`, or id `HYDRA-1` |
| SNOTEL | State `OR`, or `302:OR:SNTL` — turn off Verify SSL on the work network |

### Notes

- USGS Oregon mixes other agencies (`OR004-…`); many have no downloadable
  series in the continuous/daily API. Prefer Agency `USGS`.
- Shapefile search uses the file's **bounding box**, not the exact
  polygon. Lon/lat (WGS84) only; projected shapefiles are rejected.
- SNOTEL map-area / shapefile search still needs a **State** filled in.
- Work network: leave Aquarius SSL verification off; turn SNOTEL SSL off
  in the sidebar if requests fail.

## Layout

```
data-downloader/
  data_sources/     # BaseDataSource + USGS / Aquarius / SNOTEL + registry
  gui/              # Streamlit app
  tests/            # Live hammer_test.py
  aquarius_data_downloader.py   # Original precip→SQLite client
  storm*.py / gauge_analysis.py # Downstream rainfall analysis
  HANDOFF.md
  requirements-gui.txt
```
