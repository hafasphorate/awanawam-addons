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
3. Set the accuracy tolerance and click **Compare peak crowd density**. The app automatically matches coordinates (`x`, `y`) or a cell ID and detects fields such as `peak_density`, `projected_peak_density`, and AwanAwam's `crowd_density`.
4. Download the combined observed data as JSON or the comparison as CSV.

Nested JSON exports are searched for node records, including top-level `nodes` arrays. The observed preview draws the floorplan walls and peak-density-colored grid nodes when the JSON includes coordinates and wall segments. When observed rows overlap, non-empty values from later uploads replace earlier values for the same field; conflicting values are reported. The app processes uploaded files in memory and does not explicitly save them to disk. When hosted remotely, the files are sent to that Streamlit host for processing.

The reported accuracy is the percentage of matched cells within the selected relative-error tolerance. Actual zero or missing peak-density values are treated as no data and excluded from accuracy and error calculations. MAE is mean absolute error, RMSE emphasizes larger errors, and MAPE is mean absolute percentage error for non-zero actual values. Prediction bias is also shown.

## Related project

[AwanAwam main repository](https://github.com/hafasphorate/awanawam)