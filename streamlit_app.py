from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Crowd Prediction Validation", layout="wide")

ID_HINTS = ("cell_id", "cellid", "area_id", "areaid", "zone_id", "zoneid", "node_id", "id", "cell", "area")
CROWD_DENSITY_FIELDS = ("peak_crowd_density", "crowd_density_peak", "max_crowd_density", "crowd_density", "peak_density", "density_peak")
ARRAY_HINTS = ("vga_floorplan_nodes", "cells", "areas", "zones", "records", "metrics", "items", "data")



def find_record_array(value: Any, path: str = "$", depth: int = 0) -> tuple[str, list[dict[str, Any]]] | None:
    """Locate a likely row array in a nested AwanAwam JSON export."""
    if depth > 10:
        return None
    candidates: list[tuple[int, int, str, list[dict[str, Any]]]] = []
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            hint = max((len(token) for token in ARRAY_HINTS if token in path.lower()), default=0)
            candidates.append((hint, len(value), path, value))
        for index, child in enumerate(value):
            found = find_record_array(child, f"{path}[{index}]", depth + 1)
            if found:
                candidates.append((0, len(found[1]), found[0], found[1]))
    elif isinstance(value, dict):
        for key, child in value.items():
            found = find_record_array(child, f"{path}.{key}", depth + 1)
            if found:
                hint = max((len(token) for token in ARRAY_HINTS if token in found[0].lower()), default=0)
                candidates.append((hint, len(found[1]), found[0], found[1]))
    if not candidates:
        return None
    _, _, best_path, best_rows = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    return best_path, best_rows


def parse_upload(upload: Any) -> tuple[str, list[dict[str, Any]]]:
    data = json.loads(upload.getvalue().decode("utf-8-sig"))
    found = find_record_array(data)
    if found is None:
        raise ValueError("No non-empty array of JSON objects was found.")
    return found


def fields_in(records: list[dict[str, Any]]) -> list[str]:
    return sorted({field for record in records for field in record}, key=str.casefold)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def find_key_fields(records: list[dict[str, Any]]) -> tuple[str, ...] | None:
    names = fields_in(records)
    x_field = next((name for name in names if name.lower() in ("x", "x_coord", "x_coordinate")), None)
    y_field = next((name for name in names if name.lower() in ("y", "y_coord", "y_coordinate")), None)
    if x_field and y_field:
        return x_field, y_field
    normalized = {name.lower().replace("-", "").replace(" ", ""): name for name in names}
    for hint in ID_HINTS:
        if hint in normalized:
            return (normalized[hint],)
    return next(((name,) for name in names if name.lower().endswith("_id")), None)


def find_crowd_density_field(records: list[dict[str, Any]]) -> str | None:
    normalized = {name.lower().replace("-", "").replace(" ", ""): name for name in fields_in(records)}
    for field in CROWD_DENSITY_FIELDS:
        if field in normalized and any(is_number(record.get(normalized[field])) for record in records):
            return normalized[field]
    return None


def canonical_value(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except InvalidOperation:
            return str(value)
    return str(value).strip()


def record_key(record: dict[str, Any], key_fields: tuple[str, ...]) -> str | None:
    values = [record.get(field) for field in key_fields]
    if any(value is None or (isinstance(value, str) and not value.strip()) for value in values):
        return None
    return json.dumps([canonical_value(value) for value in values], ensure_ascii=False)


def merge_observed(sources: list[tuple[str, list[dict[str, Any]]]], key_fields: tuple[str, ...]) -> tuple[dict[str, dict[str, Any]], int, int, int]:
    merged: dict[str, dict[str, Any]] = {}
    duplicates = conflicts = skipped = 0
    for _, records in sources:
        for record in records:
            key = record_key(record, key_fields)
            if key is None:
                skipped += 1
                continue
            if key not in merged:
                merged[key] = dict(record)
                continue
            duplicates += 1
            for field, value in record.items():
                if value is None:
                    continue
                if merged[key].get(field) is not None and merged[key][field] != value:
                    conflicts += 1
                merged[key][field] = value
    return merged, duplicates, conflicts, skipped


def index_records(records: list[dict[str, Any]], key_fields: tuple[str, ...]) -> tuple[dict[str, dict[str, Any]], int, int]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates = skipped = 0
    for record in records:
        key = record_key(record, key_fields)
        if key is None:
            skipped += 1
            continue
        if key in indexed:
            duplicates += 1
        indexed[key] = record
    return indexed, duplicates, skipped


st.title("AwanAwam: Crowd Prediction Validation")
st.write("Combine actual crowd data, review the floorplan, then compare peak crowd density against a prediction.")

st.header("1. Import actual crowd metrics")
observed_uploads = st.file_uploader("Upload JSON files", type=["json"], accept_multiple_files=True, key="observed_uploads")
observed_sources: list[tuple[str, list[dict[str, Any]]]] = []
for upload in observed_uploads or []:
    try:
        path, records = parse_upload(upload)
        observed_sources.append((upload.name, records))
        st.caption(f"{upload.name}: {len(records):,} rows found at `{path}`")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.error(f"{upload.name}: {error}")

merged: dict[str, dict[str, Any]] = {}
observed_key_fields: tuple[str, ...] | None = None
observed_density_field: str | None = None
duplicates = conflicts = skipped_observed = 0
if observed_sources:
    observed_rows = [record for _, records in observed_sources for record in records]
    observed_key_fields = find_key_fields(observed_rows)
    observed_density_field = find_crowd_density_field(observed_rows)
    st.subheader("Combined actual floorplan")
    if observed_key_fields:
        merged, duplicates, conflicts, skipped_observed = merge_observed(observed_sources, observed_key_fields)
        floorplan_rows = list(merged.values())
        st.caption(f"{len(floorplan_rows):,} unique cells merged by {', '.join(observed_key_fields)}.")
        if conflicts:
            st.warning(f"{conflicts:,} overlapping values differed; the last uploaded non-empty value was kept.")
        if skipped_observed:
            st.caption(f"{skipped_observed:,} rows without a usable cell key were omitted from the merged view.")
    else:
        floorplan_rows = [record for _, records in observed_sources for record in records]
        st.warning("No coordinate pair or cell ID was found. Showing all rows, but they cannot be merged or compared automatically.")

    floorplan = pd.DataFrame(floorplan_rows)
    coordinate_fields = find_key_fields(floorplan_rows)
    if coordinate_fields and len(coordinate_fields) == 2 and observed_density_field:
        st.scatter_chart(floorplan, x=coordinate_fields[0], y=coordinate_fields[1], color=observed_density_field)
    st.dataframe(floorplan, hide_index=True, width="stretch")
    st.download_button(
        "Download combined actual data",
        json.dumps(floorplan_rows, ensure_ascii=False, indent=2),
        "combined-actual-crowd-metrics.json",
        "application/json",
    )

st.divider()
st.header("2. Compare peak crowd density")
prediction_upload = st.file_uploader("Upload prediction JSON", type=["json"], key="prediction_upload")
prediction_source: tuple[str, list[dict[str, Any]]] | None = None
if prediction_upload is not None:
    try:
        path, records = parse_upload(prediction_upload)
        prediction_source = (prediction_upload.name, records)
        st.caption(f"{prediction_upload.name}: {len(records):,} rows found at `{path}`")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.error(f"{prediction_upload.name}: {error}")

if observed_sources and prediction_source:
    predicted_rows = prediction_source[1]
    prediction_key_fields = find_key_fields(predicted_rows)
    prediction_density_field = find_crowd_density_field(predicted_rows)
    if not observed_key_fields or not prediction_key_fields:
        st.warning("Could not find matching floorplan coordinates or cell IDs in both datasets.")
    elif not observed_density_field or not prediction_density_field:
        st.warning("Could not find a peak crowd density field in both datasets.")
    else:
        st.caption(f"Comparing `{observed_density_field}` with `{prediction_density_field}`. Cell matching is automatic using {', '.join(observed_key_fields)}. Accuracy uses a 10% tolerance.")
        signatures = (
            tuple((upload.name, hash(upload.getvalue())) for upload in observed_uploads or []),
            (prediction_upload.name, hash(prediction_upload.getvalue())),
        )
        if st.button("Compare peak crowd density", type="primary"):
            predictions, duplicate_predictions, skipped_predictions = index_records(predicted_rows, prediction_key_fields)
            results = []
            missing_metric_count = 0
            for key, actual_record in merged.items():
                predicted_record = predictions.get(key)
                actual = actual_record.get(observed_density_field)
                predicted = predicted_record.get(prediction_density_field) if predicted_record else None
                if not is_number(actual) or not is_number(predicted):
                    if predicted_record is not None:
                        missing_metric_count += 1
                    continue
                absolute_error = abs(predicted - actual)
                relative_error = (0.0 if predicted == 0 else math.inf) if actual == 0 else absolute_error / abs(actual) * 100
                results.append({
                    "Cell key": ", ".join(str(actual_record.get(field, "")) for field in observed_key_fields),
                    "Actual peak crowd density": actual,
                    "Predicted peak crowd density": predicted,
                    "Absolute error": absolute_error,
                    "Relative error (%)": relative_error,
                    "Within 10%": relative_error <= 10 or math.isclose(relative_error, 10, rel_tol=1e-12, abs_tol=1e-12),
                })
            if not results:
                st.error("No matching cells had numeric peak crowd density values.")
            else:
                errors = [row["Absolute error"] for row in results]
                nonzero_actual = [row for row in results if row["Actual peak crowd density"] != 0]
                payload = {
                    "rows": results,
                    "duplicates": duplicates,
                    "conflicts": conflicts,
                    "missing_metrics": missing_metric_count,
                    "skipped_observed": skipped_observed,
                    "skipped_prediction": skipped_predictions,
                    "duplicate_predictions": duplicate_predictions,
                    "mae": sum(errors) / len(errors),
                    "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
                    "mape": sum(row["Relative error (%)"] for row in nonzero_actual) / len(nonzero_actual) if nonzero_actual else None,
                    "pass_count": sum(row["Within 10%"] for row in results),
                }
                st.session_state["comparison_payload"] = payload
                st.session_state["comparison_signature"] = signatures

        payload = st.session_state.get("comparison_payload")
        if payload and st.session_state.get("comparison_signature") == signatures:
            rows = payload["rows"]
            accuracy = payload["pass_count"] / len(rows) * 100
            prediction_keys, _, _ = index_records(predicted_rows, prediction_key_fields)
            actual_keys = set(merged)
            unmatched = len(actual_keys - prediction_keys.keys()) + len(prediction_keys.keys() - actual_keys)
            st.subheader("Results")
            cards = st.columns(4)
            cards[0].metric("Within 10% tolerance", f"{accuracy:.1f}%", f'{payload["pass_count"]:,} / {len(rows):,} matched cells')
            cards[1].metric("MAE", f'{payload["mae"]:,.3f}')
            cards[2].metric("RMSE", f'{payload["rmse"]:,.3f}')
            cards[3].metric("MAPE", "—" if payload["mape"] is None else f'{payload["mape"]:,.2f}%')
            st.caption(f"{unmatched:,} unmatched cells. Bias (prediction minus actual): {sum(row['Predicted peak crowd density'] - row['Actual peak crowd density'] for row in rows) / len(rows):+.3f}.")
            if payload["missing_metrics"]:
                st.warning(f'{payload["missing_metrics"]:,} matching cells were missing a numeric density value.')
            if payload["duplicate_predictions"]:
                st.caption(f'{payload["duplicate_predictions"]:,} repeated prediction keys; the last row was used.')

            result_frame = pd.DataFrame(rows).sort_values("Relative error (%)", ascending=False)
            result_frame["Relative error (%)"] = result_frame["Relative error (%)"].map(lambda value: "Infinity" if math.isinf(value) else f"{value:.2f}%")
            result_frame["Within 10%"] = result_frame["Within 10%"].map({True: "Yes", False: "No"})
            st.dataframe(result_frame, hide_index=True, width="stretch")
            st.download_button("Download comparison CSV", pd.DataFrame(rows).to_csv(index=False), "peak-crowd-density-comparison.csv", "text/csv")
            st.caption("A cell counts as accurate when relative error is at most 10%. For actual density zero, only a predicted zero is within tolerance. MAPE excludes zero actual values.")

