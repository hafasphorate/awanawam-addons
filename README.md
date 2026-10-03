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
4. Review the second floorplan, which highlights cells where actual density exceeds predicted density in red. The results also report their percentage among valid compared cells.
5. Download the combined observed data as JSON or the comparison as CSV.

Nested JSON exports are searched for node records, including top-level `nodes` arrays. The observed preview draws the floorplan walls and peak-density-colored grid nodes when the JSON includes coordinates and wall segments. When observed rows overlap, non-empty values from later uploads replace earlier values for the same field; conflicting values are reported. The app processes uploaded files in memory and does not explicitly save them to disk. When hosted remotely, the files are sent to that Streamlit host for processing.

The reported accuracy is the percentage of valid matched cells within the selected relative-error tolerance. Actual zero or missing peak-density values are treated as no data and excluded. The actual-greater-than-predicted percentage uses only valid matched cells with numeric, non-zero actual density and numeric predicted density. MAE is mean absolute error, RMSE emphasizes larger errors, and MAPE is mean absolute percentage error for non-zero actual values. MAE and RMSE are also compared with mean actual density; as rough guidance, under 10% is low, 10-20% moderate, and over 20% high. Common MAPE guidance is under 10% very good, 10-20% good, 20-50% fair, and over 50% poor. These are context-dependent rules of thumb, not universal acceptance limits. Prediction bias is also shown.

## Related project

[AwanAwam main repository](https://github.com/hafasphorate/awanawam)