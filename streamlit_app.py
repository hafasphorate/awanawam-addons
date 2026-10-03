from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Crowd Prediction Validation", layout="wide")

CROWD_DENSITY_FIELDS = ("projected_peak_density", "peak_density", "peak_crowd_density", "crowd_density_peak", "max_crowd_density", "projected_crowd_density", "crowd_density", "density_peak")
ARRAY_HINTS = ("vga_floorplan_nodes", "floorplan_nodes", "nodes", "cells", "areas", "zones", "records", "metrics", "items", "data")
DENSITY_SCALE_MAX = 7
DENSITY_COLORSCALE = [
    [0.0, "#22c55e"],
    [1 / DENSITY_SCALE_MAX, "#22c55e"],
    [2 / DENSITY_SCALE_MAX, "#facc15"],
    [3 / DENSITY_SCALE_MAX, "#facc15"],
    [4 / DENSITY_SCALE_MAX, "#f97316"],
    [5 / DENSITY_SCALE_MAX, "#ef4444"],
    [1.0, "#b91c1c"],
]



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


def parse_upload(upload: Any) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(upload.getvalue().decode("utf-8-sig"))
    found = find_record_array(data)
    if found is None:
        raise ValueError("No non-empty array of JSON objects was found.")
    return found[0], found[1], data


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


def canonical_value(value: Any, coordinate: bool = False) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = Decimal(str(value))
            if coordinate:
                number = number.quantize(Decimal("0.001"))
            return format(number.normalize(), "f")
        except InvalidOperation:
            return str(value)
    return str(value).strip()


def record_key(record: dict[str, Any], key_fields: tuple[str, ...]) -> str | None:
    values = [record.get(field) for field in key_fields]
    if any(value is None or (isinstance(value, str) and not value.strip()) for value in values):
        return None
    coordinates = {"x", "y", "x_coord", "y_coord", "x_coordinate", "y_coordinate"}
    return json.dumps(
        [canonical_value(value, field.lower() in coordinates) for field, value in zip(key_fields, values)],
        ensure_ascii=False,
    )


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


def find_wall_lines(data: dict[str, Any]) -> list[Any]:
    for container in (data, data.get("floorplan", {})):
        if not isinstance(container, dict):
            continue
        for field in ("wall_lines", "cad_walls"):
            lines = container.get(field)
            if isinstance(lines, list) and lines:
                return lines
    return []


def find_trajectory_node_ids(data: dict[str, Any]) -> set[str] | None:
    trajectories = data.get("trajectories")
    if not isinstance(trajectories, list):
        return None
    return {
        canonical_value(record["grid_node_idx"])
        for record in trajectories
        if isinstance(record, dict) and record.get("grid_node_idx") is not None
    }


def make_floorplan_figure(
    records: list[dict[str, Any]],
    coordinate_fields: tuple[str, ...],
    density_field: str,
    wall_lines: list[Any],
    unobserved_grid_nodes: set[str],
    comparison_keys: set[str] | None = None,
    actual_exceeds_prediction_keys: set[str] | None = None,
) -> go.Figure:
    wall_x: list[float | None] = []
    wall_y: list[float | None] = []
    for segment in wall_lines:
        if isinstance(segment, dict):
            xs, ys = segment.get("x"), segment.get("y")
            if isinstance(xs, list) and isinstance(ys, list) and len(xs) >= 2 and len(ys) >= 2:
                points = [(xs[0], ys[0]), (xs[-1], ys[-1])]
            else:
                continue
        elif isinstance(segment, list) and len(segment) >= 2:
            points = [segment[0], segment[-1]]
        else:
            continue
        if not all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in points):
            continue
        if not all(is_number(value) for point in points for value in point[:2]):
            continue
        wall_x.extend([points[0][0], points[1][0], None])
        wall_y.extend([points[0][1], points[1][1], None])

    nodes_with_data = []
    nodes_without_data = []
    nodes_over_predicted = []
    nodes_not_over_predicted = []
    for record in records:
        if len(coordinate_fields) != 2 or not all(is_number(record.get(field)) for field in coordinate_fields):
            continue
        if comparison_keys is not None:
            key = record_key(record, coordinate_fields)
            if key in comparison_keys:
                if key in (actual_exceeds_prediction_keys or set()):
                    nodes_over_predicted.append(record)
                else:
                    nodes_not_over_predicted.append(record)
            else:
                nodes_without_data.append(record)
            continue
        grid_node_idx = record.get("grid_node_idx")
        density = record.get(density_field)
        unobserved = grid_node_idx is not None and canonical_value(grid_node_idx) in unobserved_grid_nodes and (density is None or density == 0)
        if unobserved or not is_number(density):
            nodes_without_data.append(record)
        else:
            nodes_with_data.append(record)

    figure = go.Figure()
    if wall_x:
        figure.add_trace(
            go.Scattergl(
                x=wall_x,
                y=wall_y,
                mode="lines",
                line={"color": "#59645f", "width": 1},
                hoverinfo="skip",
                showlegend=False,
                name="Floorplan walls",
            )
        )
    if comparison_keys is None and nodes_with_data:
        figure.add_trace(
            go.Scattergl(
                x=[record[coordinate_fields[0]] for record in nodes_with_data],
                y=[record[coordinate_fields[1]] for record in nodes_with_data],
                mode="markers",
                marker={
                    "size": 6,
                    "color": [record[density_field] for record in nodes_with_data],
                    "colorscale": DENSITY_COLORSCALE,
                    "cmin": 0,
                    "cmax": DENSITY_SCALE_MAX,
                    "showscale": True,
                    "colorbar": {
                        "title": "people / m²",
                        "tick0": 0,
                        "dtick": 1,
                        "len": 0.82,
                        "lenmode": "fraction",
                        "thickness": 18,
                        "thicknessmode": "pixels",
                        "x": 1.02,
                        "xanchor": "left",
                        "y": 0.5,
                        "yanchor": "middle",
                        "outlinewidth": 0,
                    },
                },
                hovertemplate="x: %{x:.2f}<br>y: %{y:.2f}<br>peak density: %{marker.color:.3f}<extra></extra>",
                showlegend=False,
                name="Grid nodes",
            )
        )
    if comparison_keys is not None and nodes_not_over_predicted:
        figure.add_trace(
            go.Scattergl(
                x=[record[coordinate_fields[0]] for record in nodes_not_over_predicted],
                y=[record[coordinate_fields[1]] for record in nodes_not_over_predicted],
                mode="markers",
                marker={"size": 6, "color": "#98a19d", "opacity": 0.55},
                hovertemplate="x: %{x:.2f}<br>y: %{y:.2f}<br>Actual did not exceed prediction<extra></extra>",
                name="Actual ≤ predicted",
            )
        )
    if comparison_keys is not None and nodes_over_predicted:
        figure.add_trace(
            go.Scattergl(
                x=[record[coordinate_fields[0]] for record in nodes_over_predicted],
                y=[record[coordinate_fields[1]] for record in nodes_over_predicted],
                mode="markers",
                marker={"size": 7, "color": "#e53935", "opacity": 0.95},
                hovertemplate="x: %{x:.2f}<br>y: %{y:.2f}<br>Actual exceeded prediction<extra></extra>",
                name="Actual > predicted",
            )
        )
    if nodes_without_data:
        figure.add_trace(
            go.Scattergl(
                x=[record[coordinate_fields[0]] for record in nodes_without_data],
                y=[record[coordinate_fields[1]] for record in nodes_without_data],
                mode="markers",
                marker={"symbol": "circle", "size": 6, "color": "#ffffff", "opacity": 0.2, "line": {"width": 0}},
                hovertemplate="x: %{x:.2f}<br>y: %{y:.2f}<br>No crowd data<extra></extra>",
                name="No data",
            )
        )
    figure.update_layout(
        height=650,
        margin={"l": 10, "r": 15, "t": 10, "b": 10},
        xaxis={"title": coordinate_fields[0], "showgrid": False, "zeroline": False},
        yaxis={"title": coordinate_fields[1], "showgrid": False, "zeroline": False, "scaleanchor": "x", "scaleratio": 1},
    )
    return figure


st.title("AwanAwam: Crowd Prediction Validation")
st.write("Combine actual crowd data, review the floorplan, then compare peak crowd density against a prediction.")

st.header("1. Import actual crowd metrics")
observed_uploads = st.file_uploader("Upload JSON files", type=["json"], accept_multiple_files=True, key="observed_uploads")
observed_sources: list[tuple[str, list[dict[str, Any]]]] = []
observed_wall_lines: list[Any] = []
observed_trajectory_nodes: set[str] = set()
has_trajectory_data = False
for upload in observed_uploads or []:
    try:
        path, records, data = parse_upload(upload)
        observed_sources.append((upload.name, records))
        if not observed_wall_lines:
            observed_wall_lines = find_wall_lines(data)
        trajectory_nodes = find_trajectory_node_ids(data)
        if trajectory_nodes is not None:
            has_trajectory_data = True
            observed_trajectory_nodes.update(trajectory_nodes)
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
        unobserved_grid_nodes = set()
        if has_trajectory_data:
            unobserved_grid_nodes = {
                canonical_value(record["grid_node_idx"])
                for record in floorplan_rows
                if record.get("grid_node_idx") is not None
                and canonical_value(record["grid_node_idx"]) not in observed_trajectory_nodes
            }
        st.plotly_chart(make_floorplan_figure(floorplan_rows, coordinate_fields, observed_density_field, observed_wall_lines, unobserved_grid_nodes))
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
        path, records, _ = parse_upload(prediction_upload)
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
        tolerance = st.number_input("Accuracy tolerance (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0)
        st.caption(f"Comparing `{observed_density_field}` with `{prediction_density_field}`. Cell matching is automatic using {', '.join(observed_key_fields)}.")
        signatures = (
            tuple((upload.name, hash(upload.getvalue())) for upload in observed_uploads or []),
            (prediction_upload.name, hash(prediction_upload.getvalue())),
            tolerance,
        )
        if st.button("Compare peak crowd density", type="primary"):
            predictions, duplicate_predictions, skipped_predictions = index_records(predicted_rows, prediction_key_fields)
            results = []
            comparison_keys = set()
            actual_exceeds_prediction_keys = set()
            missing_metric_count = 0
            no_actual_data_count = 0
            for key, actual_record in merged.items():
                predicted_record = predictions.get(key)
                actual = actual_record.get(observed_density_field)
                predicted = predicted_record.get(prediction_density_field) if predicted_record else None
                if not is_number(actual) or actual == 0:
                    no_actual_data_count += 1
                    continue
                if not is_number(predicted):
                    if predicted_record is not None:
                        missing_metric_count += 1
                    continue
                absolute_error = abs(predicted - actual)
                relative_error = absolute_error / abs(actual) * 100
                comparison_keys.add(key)
                if actual > predicted:
                    actual_exceeds_prediction_keys.add(key)
                results.append({
                    "Cell key": ", ".join(str(actual_record.get(field, "")) for field in observed_key_fields),
                    "Actual peak crowd density": actual,
                    "Predicted peak crowd density": predicted,
                    "Absolute error": absolute_error,
                    "Relative error (%)": relative_error,
                    "Within tolerance": relative_error <= tolerance or math.isclose(relative_error, tolerance, rel_tol=1e-12, abs_tol=1e-12),
                })
            if not results:
                    st.error("No matching cells had non-zero actual peak crowd density and numeric predictions.")
            else:
                errors = [row["Absolute error"] for row in results]
                nonzero_actual = [row for row in results if row["Actual peak crowd density"] != 0]
                payload = {
                    "rows": results,
                    "duplicates": duplicates,
                    "conflicts": conflicts,
                    "missing_metrics": missing_metric_count,
                    "no_actual_data": no_actual_data_count,
                    "skipped_observed": skipped_observed,
                    "skipped_prediction": skipped_predictions,
                    "duplicate_predictions": duplicate_predictions,
                    "tolerance": tolerance,
                    "comparison_keys": list(comparison_keys),
                    "actual_exceeds_prediction_keys": list(actual_exceeds_prediction_keys),
                    "mae": sum(errors) / len(errors),
                    "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
                    "mape": sum(row["Relative error (%)"] for row in nonzero_actual) / len(nonzero_actual) if nonzero_actual else None,
                    "pass_count": sum(row["Within tolerance"] for row in results),
                }
                st.session_state["comparison_payload"] = payload
                st.session_state["comparison_signature"] = signatures

        payload = st.session_state.get("comparison_payload")
        if payload and st.session_state.get("comparison_signature") == signatures:
            rows = payload["rows"]
            accuracy = payload["pass_count"] / len(rows) * 100
            mean_actual_density = sum(abs(row["Actual peak crowd density"]) for row in rows) / len(rows)
            mae_of_mean_percent = payload["mae"] / mean_actual_density * 100
            rmse_of_mean_percent = payload["rmse"] / mean_actual_density * 100
            prediction_keys, _, _ = index_records(predicted_rows, prediction_key_fields)
            actual_keys = set(merged)
            unmatched = len(actual_keys - prediction_keys.keys()) + len(prediction_keys.keys() - actual_keys)
            actual_exceeds_count = sum(row["Actual peak crowd density"] > row["Predicted peak crowd density"] for row in rows)
            actual_exceeds_percent = actual_exceeds_count / len(rows) * 100
            st.subheader("Results")
            cards = st.columns(5)
            cards[0].metric(f'Within {payload["tolerance"]:g}% tolerance', f"{accuracy:.1f}%", f'{payload["pass_count"]:,} / {len(rows):,} matched cells')
            cards[1].metric("Actual > predicted", f"{actual_exceeds_percent:.1f}%", f"{actual_exceeds_count:,} / {len(rows):,} valid cells")
            cards[2].metric("MAE", f'{payload["mae"]:,.3f}', help=f'Mean Absolute Error in people/m². This is {mae_of_mean_percent:.1f}% of mean actual density.')
            cards[3].metric("RMSE", f'{payload["rmse"]:,.3f}', help=f'Root Mean Squared Error in people/m²; larger errors count more. This is {rmse_of_mean_percent:.1f}% of mean actual density.')
            cards[4].metric("MAPE", "—" if payload["mape"] is None else f'{payload["mape"]:,.2f}%', help="Mean Absolute Percentage Error: average absolute error as a percentage of actual density. Zero actual values are excluded.")
            st.markdown(
                "**Rule-of-thumb reference, not universal acceptance limits:** "
                f"MAE is **{mae_of_mean_percent:.1f}%** and RMSE is **{rmse_of_mean_percent:.1f}%** of mean actual density "
                "(<10% low, 10–20% moderate, >20% high). "
                "MAPE: <10% very good, 10–20% good, 20–50% fair, >50% poor. "
                "Acceptable error depends on the use case; MAPE can be unstable for very small actual values."
            )
            st.caption(f'{payload["no_actual_data"]:,} zero or missing actual cells excluded as no data. {unmatched:,} unmatched cells. Bias (prediction minus actual): {sum(row["Predicted peak crowd density"] - row["Actual peak crowd density"] for row in rows) / len(rows):+.3f}.')
            if payload["missing_metrics"]:
                st.warning(f'{payload["missing_metrics"]:,} matching cells were missing a numeric density value.')
            if payload["duplicate_predictions"]:
                st.caption(f'{payload["duplicate_predictions"]:,} repeated prediction keys; the last row was used.')

            if len(observed_key_fields) == 2:
                st.subheader("Cells where actual density exceeds prediction")
                comparison_figure = make_floorplan_figure(
                    list(merged.values()),
                    observed_key_fields,
                    observed_density_field,
                    observed_wall_lines,
                    unobserved_grid_nodes,
                    set(payload["comparison_keys"]),
                    set(payload["actual_exceeds_prediction_keys"]),
                )
                st.plotly_chart(comparison_figure)

            result_frame = pd.DataFrame(rows).sort_values("Relative error (%)", ascending=False)
            result_frame["Relative error (%)"] = result_frame["Relative error (%)"].map(lambda value: "Infinity" if math.isinf(value) else f"{value:.2f}%")
            result_frame["Within tolerance"] = result_frame["Within tolerance"].map({True: "Yes", False: "No"})
            st.dataframe(result_frame, hide_index=True, width="stretch")
            st.download_button("Download comparison CSV", pd.DataFrame(rows).to_csv(index=False), "peak-crowd-density-comparison.csv", "text/csv")
            st.caption(f'A cell counts as accurate when relative error is at most {payload["tolerance"]:g}%. Zero or missing actual density is treated as no data and excluded from the comparison.')

