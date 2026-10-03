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

1. Upload one or more observed JSON exports. The app merges and displays the floorplan data before asking for the prediction.
2. Upload the prediction JSON.
3. Click **Compare peak crowd density**. The app automatically matches coordinates (`x`, `y`) or a cell ID and detects fields such as `peak_crowd_density` or AwanAwam's `crowd_density`.
4. Download the combined observed data as JSON or the comparison as CSV.

Nested JSON exports are searched for a non-empty array of object records. When observed rows overlap, non-empty values from later uploads replace earlier values for the same field; conflicting values are reported. The app processes uploaded files in memory and does not explicitly save them to disk. When hosted remotely, the files are sent to that Streamlit host for processing.

The reported accuracy is the percentage of matched cells within a 10% relative-error tolerance. MAE, RMSE, MAPE, and prediction bias are also shown. MAPE excludes observed values of zero; a zero observed value is within tolerance only when its prediction is also zero.

## Related project

[AwanAwam main repository](https://github.com/hafasphorate/awanawam)