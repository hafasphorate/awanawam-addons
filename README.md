# AwanAwam Add-ons

A companion Streamlit app for combining observed crowd metrics from multiple floorplan JSON exports and validating a predicted metric against them, cell by cell.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Use

1. Upload one or more observed JSON exports and one prediction JSON.
2. Choose the cell key and numeric metric on each side. AwanAwam exports such as `vga_floorplan_nodes` with `x`, `y`, and `crowd_density` are supported; coordinate pairs are offered as cell keys when present.
3. Set the relative-error tolerance and compare.
4. Download the merged observed data as JSON or the per-cell comparison as CSV.

Nested JSON exports are searched for a non-empty array of object records. When observed rows overlap, non-empty values from later uploads replace earlier values for the same field; conflicting values are reported. The app processes uploaded files in memory and does not explicitly save them to disk. When hosted remotely, the files are sent to that Streamlit host for processing.

The reported tolerance accuracy is the percentage of matched cells within the selected relative-error threshold. MAE, RMSE, MAPE, and prediction bias are also shown. MAPE excludes observed values of zero; a zero observed value is within tolerance only when its prediction is also zero.

## Related project

[AwanAwam main repository](https://github.com/hafasphorate/awanawam)