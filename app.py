# app.py
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from environment_analyzer.scoring_model import (
    compute_all_scores_for_product,
    load_products,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "product_aware_complete_20251127_235835.json"

# Threshold used when a metric must be “excellent” (0–100); ≥80 qualifies.
MUST_HAVE_THRESHOLD = 80.0

app = Flask(__name__)


# ---------- Data loading & preprocessing ----------
def _load_all_products() -> List[Dict[str, Any]]:
    products = load_products(str(DATA_FILE))
    return products


PRODUCTS_RAW: List[Dict[str, Any]] = _load_all_products()


def _all_categories() -> List[str]:
    cats = set()
    for p in PRODUCTS_RAW:
        for c in p.get("product_categories") or []:
            name = c.get("category_name")
            if name:
                cats.add(name)
    return sorted(cats)


def _find_product_by_id(pid: int) -> Dict[str, Any] | None:
    for p in PRODUCTS_RAW:
        try:
            if int(p.get("id")) == pid:
                return p
        except (TypeError, ValueError):
            continue
    return None


def _coerce_weight(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _grade_label(score: Optional[float]) -> str:
    if score is None:
        return "Missing data"
    if score >= 80:
        return "Excellent"
    if score >= 50:
        return "Pass"
    return "Fail"


def _resolve_image(product: Dict[str, Any]) -> Optional[str]:
    candidate_keys = [
        "image",
        "cover_image",
        "thumbnail",
        "product_image",
        "product_photo",
    ]
    for key in candidate_keys:
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_image_url(value.strip())
    images = product.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str) and first.strip():
            return _normalize_image_url(first.strip())
        if isinstance(first, dict):
            for candidate in ("url", "image", "src"):
                val = first.get(candidate)
                if isinstance(val, str) and val.strip():
                    return _normalize_image_url(val.strip())
    return None


def _normalize_image_url(path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    cleaned = path.lstrip("/")
    return f"https://architectsdeclareapp.s3.amazonaws.com/media/{cleaned}"


# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/material/<int:product_id>")
def material_detail(product_id: int):
    """
    Server-rendered detail page showing the three component scores plus metadata.
    """
    product = _find_product_by_id(product_id)
    if not product:
        return "Material not found", 404

    scored = compute_all_scores_for_product(
        product,
        reference_lifespan=20.0,  # default reference lifespan
    )
    categories = [c.get("category_name") for c in (product.get("product_categories") or []) if c.get("category_name")]

    scored["total_label"] = _grade_label(scored.get("total_score"))
    return render_template(
        "material_detail.html",
        product=scored,
        categories=categories,
    )


@app.route("/api/material/<int:product_id>", methods=["GET"])
def api_material_detail(product_id: int):
    product = _find_product_by_id(product_id)
    if not product:
        return jsonify({"success": False, "error": "Material not found"}), 404

    scored = compute_all_scores_for_product(
        product,
        reference_lifespan=20.0,
    )
    categories = [
        c.get("category_name")
        for c in (product.get("product_categories") or [])
        if c.get("category_name")
    ]

    image_url = _resolve_image(product)

    detail = {
        "id": scored.get("id"),
        "manufacturer_name": scored.get("manufacturer_name"),
        "product_name": scored.get("product_name"),
        "product_code": scored.get("product_code"),
        "product_description": scored.get("product_description"),
        "categories": categories,
        "hazardous_substances_score": scored.get("hazardous_substances_score"),
        "circularity_lifespan_score": scored.get("circularity_lifespan_score"),
        "certification_score": scored.get("certification_score"),
        "total_score": scored.get("total_score"),
        "total_label": _grade_label(scored.get("total_score")),
        "hazardous_substances_score_missing": scored.get("hazardous_substances_score_missing", {}),
        "circularity_lifespan_score_missing": scored.get("circularity_lifespan_score_missing", {}),
        "volatile_organic_compounds": scored.get("volatile_organic_compounds"),
        "substances_of_concern": scored.get("substances_of_concern"),
        "recyclable_percentage": scored.get("recyclable_percentage"),
        "recycled_content_percentage": scored.get("recycled_content_percentage"),
        "reusable": scored.get("reusable"),
        "expected_lifespan_years": scored.get("expected_lifespan_years"),
        "independent_lca": scored.get("independent_lca"),
        "certifications": scored.get("certifications") or [],
        "image_url": image_url,
    }

    return jsonify({"success": True, "item": detail})


@app.route("/api/filters", methods=["GET"])
def get_filters():
    """
    Provide the metadata required by the front-end filters:
    - List of categories
    - Metric definitions (id, label, description)
    """
    metrics = [
        {
            "id": "hazardous_substances",
            "label": "Hazardous substances (VOC + substances of concern)",
            "description": "Emphasizes low VOC emissions and minimized substances of concern.",
        },
        {
            "id": "circularity",
            "label": "Circularity & Lifetime (CLSI)",
            "description": "Combines recycled input, recyclability, lifetime, and reusability.",
        },
        {
            "id": "certification",
            "label": "Certifications (LCA & third-party)",
            "description": "Rewards independent LCA and high-value environmental certifications.",
        },
    ]

    data = {
        "categories": _all_categories(),
        "metrics": metrics,
    }
    return jsonify({"success": True, "data": data})


@app.route("/api/recommend", methods=["POST"])
def recommend_materials():
    """
    Core recommendation endpoint.
    Expects:
      - category: optional category filter
      - required_metrics: metrics that must be “excellent” (>=80)
      - weights: weight mapping per metric, e.g. {"hazardous_substances": 0.4, ...}
    Returns:
      - Sorted material list with component scores and totals.
    """
    payload = request.get_json(silent=True) or {}

    category = (payload.get("category") or "").strip() or None
    required_metrics = payload.get("required_metrics") or []
    weights_raw = payload.get("weights") or {}

    w_hazardous_substances = _coerce_weight(weights_raw.get("hazardous_substances"), 0.4)
    w_circ = _coerce_weight(weights_raw.get("circularity"), 0.4)
    w_cert = _coerce_weight(weights_raw.get("certification"), 0.2)

    items: List[Dict[str, Any]] = []

    for p in PRODUCTS_RAW:
        if category:
            cat_names = [
                c.get("category_name")
                for c in (p.get("product_categories") or [])
                if c.get("category_name")
            ]
            if category not in cat_names:
                continue

        scored = compute_all_scores_for_product(
            p,
            weight_hazardous_substances=w_hazardous_substances,
            weight_circularity=w_circ,
            weight_certification=w_cert,
            reference_lifespan=20.0,
        )

        ok = True
        for m in required_metrics:
            if m == "hazardous_substances":
                hazardous_substances_score = scored.get("hazardous_substances_score")
                if hazardous_substances_score is None or hazardous_substances_score < MUST_HAVE_THRESHOLD:
                    ok = False
                    break
            if (
                m == "circularity"
                and scored.get("circularity_lifespan_score", 0.0) < MUST_HAVE_THRESHOLD
            ):
                ok = False
                break
            if (
                m == "certification"
                and scored.get("certification_score", 0.0) < MUST_HAVE_THRESHOLD
            ):
                ok = False
                break
        if not ok:
            continue

        cat_names = [
            c.get("category_name")
            for c in (p.get("product_categories") or [])
            if c.get("category_name")
        ]

        total_score = scored.get("total_score")
        image_url = _resolve_image(p)

        item = {
            "id": scored.get("id"),
            "manufacturer_name": scored.get("manufacturer_name"),
            "product_name": scored.get("product_name"),
            "product_code": scored.get("product_code"),
            "product_description": scored.get("product_description"),
            "categories": cat_names,
            "hazardous_substances_score": scored.get("hazardous_substances_score"),
            "hazardous_substances_score_missing": scored.get("hazardous_substances_score_missing", {}),
            "circularity_lifespan_score": scored.get("circularity_lifespan_score"),
            "circularity_lifespan_score_missing": scored.get("circularity_lifespan_score_missing", {}),
            "certification_score": scored.get("certification_score"),
            "total_score": total_score,
            "total_label": _grade_label(total_score),
            "volatile_organic_compounds": scored.get("volatile_organic_compounds"),
            "substances_of_concern": scored.get("substances_of_concern"),
            "recyclable_percentage": scored.get("recyclable_percentage"),
            "recycled_content_percentage": scored.get("recycled_content_percentage"),
            "reusable": scored.get("reusable"),
            "expected_lifespan_years": scored.get("expected_lifespan_years"),
            "independent_lca": scored.get("independent_lca"),
            "certifications": scored.get("certifications") or [],
            "image_url": image_url,
        }
        items.append(item)

    items.sort(key=lambda x: x.get("total_score", 0.0), reverse=True)

    return jsonify({"success": True, "count": len(items), "items": items})


if __name__ == "__main__":
    app.run(debug=True)
