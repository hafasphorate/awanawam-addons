from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Crowd Prediction Validation", layout="wide")

ID_HINTS = ("cell_id", "cellid", "area_id", "areaid", "zone_id", "zoneid", "node_id", "id", "cell", "area")
METRIC_HINTS = ("crowd_density", "crowd_count", "occupancy", "people_count", "people", "visitors", "count", "density", "value")
ARRAY_HINTS = ("vga_floorplan_nodes", "cells", "areas", "zones", "records", "metrics", "items", "data")

st.title("AwanAwam: Crowd Prediction Validation")
st.write("Combine observed crowd metrics from multiple JSON files and compare them with a prediction.")


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


def default_index(options: list[str], hints: tuple[str, ...]) -> int:
    normalized = [option.lower().replace("-", "").replace(" ", "") for option in options]
    for hint in hints:
        for index, option in enumerate(normalized):
            if option == hint:
                return index
    for index, option in enumerate(normalized):
        if any(hint in option for hint in hints):
            return index
    return 0


def get_key_options(records: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    names = fields_in(records)
    choices = {
        f"Field: {name}": (name,)
        for name in names
        if name.lower().replace("-", "").replace(" ", "") in ID_HINTS or name.lower().endswith("_id")
    }
    x_field = next((name for name in names if name.lower() in ("x", "x_coord", "x_coordinate")), None)
    y_field = next((name for name in names if name.lower() in ("y", "y_coord", "y_coordinate")), None)
    if x_field and y_field:
        choices[f"Coordinates: {x_field} + {y_field}"] = (x_field, y_field)
    if not choices:
        choices = {f"Field: {name}": (name,) for name in names}
    return choices


def metric_fields(records: list[dict[str, Any]]) -> list[str]:
    names = fields_in(records)
    return [name for name in names if any(is_number(record.get(name)) for record in records)]


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


st.header("1. Upload JSON data")
left, right = st.columns(2)
with left:
    st.subheader("Observed metrics")
    observed_uploads = st.file_uploader("Upload one or more observed JSON files", type=["json"], accept_multiple_files=True, key="observed_uploads")
with right:
    st.subheader("Predicted metrics")
    prediction_upload = st.file_uploader("Upload a prediction JSON file", type=["json"], key="prediction_upload")

observed_sources: list[tuple[str, list[dict[str, Any]]]] = []
prediction_source: tuple[str, list[dict[str, Any]]] | None = None
for upload in observed_uploads or []:
    try:
        path, records = parse_upload(upload)
        observed_sources.append((upload.name, records))
        st.caption(f"{upload.name}: {len(records):,} rows found at `{path}`")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.error(f"{upload.name}: {error}")
if prediction_upload is not None:
    try:
        path, records = parse_upload(prediction_upload)
        prediction_source = (prediction_upload.name, records)
        st.caption(f"{prediction_upload.name}: {len(records):,} rows found at `{path}`")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.error(f"{prediction_upload.name}: {error}")

if observed_sources or prediction_source:
    st.header("2. Match cells and metrics")
    observed_rows = [record for _, rows in observed_sources for record in rows]
    predicted_rows = prediction_source[1] if prediction_source else []
    observed_keys = get_key_options(observed_rows) if observed_rows else {}
    prediction_keys = get_key_options(predicted_rows) if predicted_rows else {}
    observed_metrics = metric_fields(observed_rows)
    predicted_metrics = metric_fields(predicted_rows)
    usable_fields = bool(observed_keys and prediction_keys and observed_metrics and predicted_metrics)
    if not observed_keys:
        observed_keys = {"No usable cell key found": ()}
    if not prediction_keys:
        prediction_keys = {"No usable cell key found": ()}
    if not observed_metrics:
        observed_metrics = ["No numeric metric field"]
    if not predicted_metrics:
        predicted_metrics = ["No numeric metric field"]

    if observed_sources and prediction_source:
        cols = st.columns(4)
        with cols[0]:
            observed_key_label = st.selectbox("Observed cell key", list(observed_keys), index=default_index(list(observed_keys), ID_HINTS), key="observed_key")
        with cols[1]:
            observed_metric = st.selectbox("Observed metric", observed_metrics, index=default_index(observed_metrics, METRIC_HINTS), key="observed_metric")
        with cols[2]:
            prediction_key_label = st.selectbox("Prediction cell key", list(prediction_keys), index=default_index(list(prediction_keys), ID_HINTS), key="prediction_key")
        with cols[3]:
            prediction_metric = st.selectbox("Prediction metric", predicted_metrics, index=default_index(predicted_metrics, METRIC_HINTS), key="prediction_metric")

        tolerance = st.number_input("Accuracy tolerance (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0, help="A cell is accurate when prediction error is within this percentage of its observed value.")
        signatures = (
            tuple((upload.name, hash(upload.getvalue())) for upload in observed_uploads or []),
            (prediction_upload.name, hash(prediction_upload.getvalue())),
            observed_key_label, observed_metric, prediction_key_label, prediction_metric, tolerance,
        )
        if not usable_fields:
            st.warning("The selected JSON records need a usable cell key and at least one numeric metric field on each side.")
        elif st.button("Compare cells", type="primary"):
            observed_key_fields = observed_keys[observed_key_label]
            prediction_key_fields = prediction_keys[prediction_key_label]
            merged, duplicate_observed, conflicts, skipped_observed = merge_observed(observed_sources, observed_key_fields)
            predictions, duplicate_predictions, skipped_predictions = index_records(predicted_rows, prediction_key_fields)
            results = []
            missing_metric_count = 0
            for key, actual_record in merged.items():
                predicted_record = predictions.get(key)
                actual = actual_record.get(observed_metric)
                predicted = predicted_record.get(prediction_metric) if predicted_record else None
                if not is_number(actual) or not is_number(predicted):
                    if predicted_record is not None:
                        missing_metric_count += 1
                    continue
                absolute_error = abs(predicted - actual)
                relative_error = (0.0 if predicted == 0 else math.inf) if actual == 0 else absolute_error / abs(actual) * 100
                results.append({
                    "Cell key": ", ".join(str(actual_record.get(field, "")) for field in observed_key_fields),
                    "Observed": actual, "Predicted": predicted, "Absolute error": absolute_error,
                    "Relative error (%)": relative_error,
                    "Within tolerance": relative_error <= tolerance or math.isclose(relative_error, tolerance, rel_tol=1e-12, abs_tol=1e-12),
                })
            if not results:
                st.error("No cells matched with numeric values. Check the selected cell keys and metric fields.")
            else:
                errors = [row["Absolute error"] for row in results]
                nonzero_actual = [row for row in results if row["Observed"] != 0]
                payload = {
                    "rows": results, "merged": list(merged.values()), "tolerance": tolerance,
                    "duplicates": duplicate_observed, "conflicts": conflicts,
                    "skipped_observed": skipped_observed, "skipped_prediction": skipped_predictions,
                    "duplicate_predictions": duplicate_predictions, "missing_metrics": missing_metric_count,
                    "mae": sum(errors) / len(errors),
                    "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
                    "mape": sum(row["Relative error (%)"] for row in nonzero_actual) / len(nonzero_actual) if nonzero_actual else None,
                    "bias": sum(row["Predicted"] - row["Observed"] for row in results) / len(results),
                    "pass_count": sum(row["Within tolerance"] for row in results),
                }
                st.session_state["comparison_payload"] = payload
                st.session_state["comparison_signature"] = signatures
        payload = st.session_state.get("comparison_payload")
        if payload and st.session_state.get("comparison_signature") == signatures:
            rows = payload["rows"]
            accuracy = payload["pass_count"] / len(rows) * 100
            common_keys = {record_key(record, observed_keys[observed_key_label]) for record in payload["merged"]}
            predicted_index, _, _ = index_records(predicted_rows, prediction_keys[prediction_key_label])
            common_keys.discard(None)
            unmatched = len(common_keys - predicted_index.keys()) + len(predicted_index.keys() - common_keys)
            st.header("3. Comparison results")
            cards = st.columns(4)
            cards[0].metric(f"Within {tolerance:g}% tolerance", f'{accuracy:.1f}%', f'{payload["pass_count"]:,} / {len(rows):,} matched cells')
            cards[1].metric("Matched cells", f"{len(rows):,}")
            cards[2].metric("Unmatched cells", f"{unmatched:,}")
            cards[3].metric("Overlapping observed rows", f'{payload["duplicates"]:,}')
            error_cards = st.columns(4)
            error_cards[0].metric("MAE", f'{payload["mae"]:,.3f}', help="Mean absolute error")
            error_cards[1].metric("RMSE", f'{payload["rmse"]:,.3f}', help="Root mean squared error")
            error_cards[2].metric("MAPE", "—" if payload["mape"] is None else f'{payload["mape"]:,.2f}%', help="Mean absolute percentage error; excludes observed zeros")
            error_cards[3].metric("Bias", f'{payload["bias"]:+,.3f}', help="Average prediction minus observed value")
            if payload["conflicts"]:
                st.warning(f'{payload["conflicts"]:,} overlapping observed values differed; the last uploaded non-empty value was kept.')
            if payload["missing_metrics"]:
                st.info(f'{payload["missing_metrics"]:,} matching cells were missing a numeric selected metric.')
            if payload["skipped_observed"] or payload["skipped_prediction"]:
                st.caption(f'Rows without a usable cell key skipped: {payload["skipped_observed"]:,} observed, {payload["skipped_prediction"]:,} predicted.')
            if payload["duplicate_predictions"]:
                st.caption(f'{payload["duplicate_predictions"]:,} repeated prediction keys; the last row was used.')

            result_frame = pd.DataFrame(rows).sort_values("Relative error (%)", ascending=False)
            visible = result_frame.head(500).copy()
            visible["Relative error (%)"] = visible["Relative error (%)"].map(lambda value: "∞" if math.isinf(value) else f"{value:.2f}%")
            visible["Within tolerance"] = visible["Within tolerance"].map({True: "Yes", False: "No"})
            st.subheader("Cell-by-cell results")
            st.dataframe(visible, hide_index=True, width="stretch")
            if len(result_frame) > 500:
                st.caption(f"Showing 500 largest errors out of {len(result_frame):,} matched cells.")

            csv_frame = result_frame.copy()
            csv_frame["Relative error (%)"] = csv_frame["Relative error (%)"].map(lambda value: "Infinity" if math.isinf(value) else value)
            download_left, download_right = st.columns(2)
            download_left.download_button("Download merged observed JSON", json.dumps(payload["merged"], ensure_ascii=False, indent=2), "merged-observed-metrics.json", "application/json")
            download_right.download_button("Download comparison CSV", csv_frame.to_csv(index=False), "crowd-comparison.csv", "text/csv")
            st.caption("Accuracy is the share of matched cells within the selected relative-error tolerance. For observed zero, only a predicted zero is within tolerance. MAPE excludes observed zeros.")
    else:
        st.info("Add at least one observed JSON file and one prediction JSON file to compare.")

