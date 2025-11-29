"""
scoring_model.py

Utility script that computes environmental scores for Product Aware JSON datasets.

Features:
1. Load the entire product list from a JSON file.
2. For every product, compute:
   - hazardous_substances_score (0-100)
   - circularity_lifespan_score (0-100)
   - certification_score        (0-100)
   - total_score                (0-100, weighted aggregate)
3. Optionally export the scored products to a new JSON file.

Command-line example:
    python scoring_model.py \
        --input product_aware_complete_20251127_235835.json \
        --output scored_products.json \
        --reference-lifespan 20

You can adjust the reference lifespan to match your industry/material context (e.g., 25–30 years).
"""

import argparse
import json
from typing import Any, Dict, List, Optional


# =========================
# Utility helpers
# =========================

def load_products(path: str) -> List[Dict[str, Any]]:
    """Load the product list from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("The JSON root must be a list.")
    return data


def save_products(path: str, data: List[Dict[str, Any]]) -> None:
    """Dump scored product data back to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def try_parse_percentage(value: Any) -> Optional[float]:
    """
    Attempt to parse a field into a percentage (0-100).
    - "76" -> 76.0
    - 76 -> 76.0
    - "Unsure" / None / "" -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        # Strings that do not start with a digit (e.g., "Unsure") are treated as invalid.
        if not (v[0].isdigit() or (v[0] == "-" and len(v) > 1 and v[1].isdigit())):
            return None
        try:
            return float(v)
        except ValueError:
            return None
    return None


# =========================
# Score 1: Hazardous substances
# =========================

def compute_hazardous_substances_score(product: Dict[str, Any]) -> tuple[Optional[float], Dict[str, bool]]:
    """
    Compute the hazardous substances score (0-100) using:
      - volatile_organic_compounds
      - substances_of_concern

    Rules:
      VOC (0‒2 points):
        * “No emissions” / highest tier → 2
        * “Low emissions” → 1
        * “High emissions” → 0
        * Any other value → mark as missing

      Substances of concern (0‒1 point):
        * “No” → 1
        * “Unsure” → missing
        * “Yes” → 0

      Scoring:
        * If both inputs are missing → return None with missing flags
        * If exactly one input exists → it covers the full 50 points, the missing half counts as 0
        * If both exist → each contributes 50% of the total

    Returns (score, missing_info).
    """
    voc = (product.get("volatile_organic_compounds") or "").strip()
    subs = (product.get("substances_of_concern") or "").strip()

    missing_info = {"voc_missing": False, "substances_missing": False}

    voc_points = None
    voc_lower = voc.lower()
    
    if "no emissions" in voc_lower or voc == "Yes - No Emissions":
        voc_points = 2
    elif "low emissions" in voc_lower or voc == "Yes - Low Emissions":
        voc_points = 1
    elif "high emissions" in voc_lower:
        voc_points = 0
    else:
        missing_info["voc_missing"] = True
        voc_points = None

    subs_points = None
    if subs == "No":
        subs_points = 1
    elif subs == "Yes":
        subs_points = 0
    elif subs == "Unsure" or not subs:
        missing_info["substances_missing"] = True
        subs_points = None

    if voc_points is None and subs_points is None:
        return None, missing_info
    elif voc_points is None:
        score = subs_points * 50.0
        return round(score, 2), missing_info
    elif subs_points is None:
        score = (voc_points / 2.0) * 50.0
        return round(score, 2), missing_info
    else:
        voc_score = (voc_points / 2.0) * 50.0
        subs_score = subs_points * 50.0
        total_score = voc_score + subs_score
        return round(total_score, 2), missing_info


# =========================
# Score 2: Circularity & Lifetime Score Index (CLSI)
# =========================

def compute_circularity_lifespan_score(
    product: Dict[str, Any], 
    reference_lifespan: float = 20.0
) -> tuple[float, Dict[str, bool]]:
    """
    Circularity & Lifetime Score Index (CLSI), scaled to 0–100.

    Inspired by the Material Circularity Indicator (MCI), the score blends:
      1. Material circularity (recycled input + recyclable output)
      2. Product lifetime utility
      3. Reusability preference (reuse > recycle)

    Inputs:
      - recycled_content_percentage (0–100)
      - recyclable_percentage (0–100)
      - reusable ("Yes" / "Unsure" / "No" / empty)
      - expected_lifespan_years

    reference_lifespan defaults to 20 years but can be tuned (25–30 is typical).

    Returns (score, missing_info) where missing_info tracks which inputs were absent.
    """
    missing_info = {
        "recycled_content_missing": False,
        "recyclable_missing": False,
        "lifespan_missing": False,
        "reusable_missing": False,
    }
    
    # Step 1: normalize raw inputs

    # 1.1 Recycled content R_in = recycled_content_percentage / 100
    recycled_content_pct = try_parse_percentage(product.get("recycled_content_percentage"))
    if recycled_content_pct is None:
        missing_info["recycled_content_missing"] = True
        R_in = None
    else:
        R_in = recycled_content_pct / 100.0  # normalize to 0–1
    
    # 1.2 Recyclable output R_out = recyclable_percentage / 100
    recyclable_pct = try_parse_percentage(product.get("recyclable_percentage"))
    if recyclable_pct is None:
        missing_info["recyclable_missing"] = True
        R_out = None
    else:
        R_out = recyclable_pct / 100.0  # normalize to 0–1
    
    # 1.3 Lifetime factor S_life = min(1, L / L_ref)
    lifespan_years = product.get("expected_lifespan_years")
    if lifespan_years is None:
        missing_info["lifespan_missing"] = True
        S_life = None
    else:
        try:
            L = float(lifespan_years)
            S_life = min(1.0, L / reference_lifespan)
        except (TypeError, ValueError):
            missing_info["lifespan_missing"] = True
            S_life = None
    
    # 1.4 Reuse factor S_reuse
    reusable_val = (product.get("reusable") or "").strip()
    if not reusable_val:
        missing_info["reusable_missing"] = True
        S_reuse = None
    elif reusable_val == "Yes":
        S_reuse = 1.0
    elif reusable_val == "Unsure":
        S_reuse = 0.5
    else:  # "No" or anything else
        S_reuse = 0.0
    
    # Step 2: material circularity sub-score S_mat
    # S_mat = (R_in + R_out) / 2, falling back when data is missing.
    
    if R_in is None and R_out is None:
        S_mat = None
    elif R_in is None:
        S_mat = R_out
    elif R_out is None:
        S_mat = R_in
    else:
        S_mat = (R_in + R_out) / 2.0
    
    # Step 3: aggregate into CLSI = w_mat*S_mat + w_life*S_life + w_reuse*S_reuse
    
    w_mat = 0.4
    w_life = 0.4
    w_reuse = 0.2
    
    # Use neutral value 0.5 when a component is missing.
    S_mat_final = S_mat if S_mat is not None else 0.5
    S_life_final = S_life if S_life is not None else 0.5
    S_reuse_final = S_reuse if S_reuse is not None else 0.5
    
    CI_CL = w_mat * S_mat_final + w_life * S_life_final + w_reuse * S_reuse_final
    
    CLSI = 100.0 * CI_CL
    return round(CLSI, 2), missing_info


# =========================
# Score 3: Certifications
# =========================

HIGH_VALUE_CERT_KEYWORDS = [
    "Environmental Product Declaration",  # EPD
    "EPD",
    "Cradle to Cradle",
    "C2C",
    "Declare label",
    "GreenTag – Green Rate",
    "GreenTag – Health Rate",
    "GreenTag – LCA Rate",
    "GECA",
    "GREENGUARD",
    "Health Product Declaration",
    "HPD",
    "SCS Indoor Advantage",
]


def compute_certification_score(product: Dict[str, Any]) -> float:
    """
    Certification score (0-100) using:
      - independent_lca
      - certifications list

    Rules:
      - High-value certifications (keywords in HIGH_VALUE_CERT_KEYWORDS):
          +2 each, counted up to 2 entries (max +4)
      - Other certifications:
          +1 each, counted up to 3 entries (max +3)
      - independent_lca == "Yes":
          +2

    Maximum raw points = 4 + 3 + 2 = 9, then scaled to 0–100.
    """
    certs = product.get("certifications") or []
    high_value_count = 0
    other_count = 0

    for c in certs:
        name = (c.get("certification") or "").strip()
        if not name:
            continue
        name_lower = name.lower()
        if any(keyword.lower() in name_lower for keyword in HIGH_VALUE_CERT_KEYWORDS):
            high_value_count += 1
        else:
            other_count += 1

    high_value_points = min(high_value_count, 2) * 2  # up to +4
    other_points = min(other_count, 3) * 1           # up to +3

    lca_flag = (product.get("independent_lca") or "").strip()
    lca_points = 2 if lca_flag == "Yes" else 0

    total_points = high_value_points + other_points + lca_points
    max_points = 9
    score = (total_points / max_points) * 100 if max_points > 0 else 0.0
    return round(score, 2)


# =========================
# Aggregation & CLI entry point
# =========================

def compute_all_scores_for_product(
    product: Dict[str, Any],
    weight_hazardous_substances: float = 0.4,
    weight_circularity: float = 0.4,
    weight_certification: float = 0.2,
    reference_lifespan: float = 20.0,
) -> Dict[str, Any]:
    """
    Compute the three core scores plus the weighted total for a single product.

    Args:
        reference_lifespan: lifespan baseline (years) used when calculating CLSI.
    """
    hazardous_substances_result = compute_hazardous_substances_score(product)
    hazardous_substances_score, hazardous_substances_missing = hazardous_substances_result

    circularity_result = compute_circularity_lifespan_score(
        product, reference_lifespan=reference_lifespan
    )
    circularity_score, circularity_missing = circularity_result

    certification = compute_certification_score(product)

    hazardous_substances_for_total = (
        hazardous_substances_score if hazardous_substances_score is not None else 0.0
    )
    circularity_for_total = circularity_score

    total = (
        hazardous_substances_for_total * weight_hazardous_substances
        + circularity_for_total * weight_circularity
        + certification * weight_certification
    )

    result = dict(product)
    result["hazardous_substances_score"] = hazardous_substances_score
    result["hazardous_substances_score_missing"] = hazardous_substances_missing
    result["circularity_lifespan_score"] = round(circularity_score, 2)
    result["circularity_lifespan_score_missing"] = circularity_missing
    result["certification_score"] = round(certification, 2)
    result["total_score"] = round(total, 2)
    return result


def main():
    parser = argparse.ArgumentParser(description="Score Product Aware materials for sustainability.")
    parser.add_argument(
        "--input",
        type=str,
        default="product_aware_complete_20251127_235835.json",
        help="Input JSON path (raw product data)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="scored_products.json",
        help="Output JSON path (scored data)",
    )
    parser.add_argument(
        "--reference-lifespan",
        type=float,
        default=20.0,
        help="Reference lifespan (years) for CLSI, default 20",
    )
    args = parser.parse_args()

    products = load_products(args.input)

    scored_products: List[Dict[str, Any]] = []
    for p in products:
        scored = compute_all_scores_for_product(
            p,
            reference_lifespan=args.reference_lifespan,
        )
        scored_products.append(scored)

    scored_products.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    save_products(args.output, scored_products)

    print("Top 5 products by total_score:")
    for item in scored_products[:5]:
        name = item.get("product_name") or item.get("product_code") or item.get("id")
        print(
            f"- {name}: total={item['total_score']}, "
            f"hazardous_substances={item['hazardous_substances_score']}, "
            f"circularity={item['circularity_lifespan_score']}, "
            f"cert={item['certification_score']}"
        )


if __name__ == "__main__":
    main()
