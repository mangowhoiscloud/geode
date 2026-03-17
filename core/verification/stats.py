"""Statistical utilities for verification layer.

Pure math functions with no infrastructure or config dependencies.
"""

from __future__ import annotations

import numpy as np


def calculate_krippendorff_alpha(
    ratings_matrix: list[list[float | None]],
) -> float:
    """Compute Krippendorff's alpha using coincidence matrix (numpy-only).

    Uses the ordinal-compatible squared-difference metric function.
    Follows Krippendorff (2011) coincidence matrix formulation where
    each item with m_u raters contributes 1/(m_u-1) to each pair.

    References:
        Krippendorff, K. (2011). Computing Krippendorff's Alpha-Reliability.
            https://repository.upenn.edu/asc_papers/43
        Hayes, A.F. & Krippendorff, K. (2007). Answering the Call for a
            Standard Reliability Measure for Coding Data. Communication
            Methods and Measures, 1(1), 77-89. doi:10.1080/19312450709336664

    Args:
        ratings_matrix: List of raters, each with list of scores per item.
            None = missing rating.

    Returns:
        Alpha coefficient (-1.0 to 1.0). 1.0 = perfect agreement.
    """
    n_raters = len(ratings_matrix)
    if n_raters < 2:
        return 0.0

    n_items = len(ratings_matrix[0])
    if n_items == 0:
        return 0.0

    # Collect pairable values per item and build coincidence matrix
    all_values: list[float] = []
    items_data: list[list[float]] = []

    for item_idx in range(n_items):
        item_values: list[float] = [
            ratings_matrix[r][item_idx]  # type: ignore[misc]
            for r in range(n_raters)
            if ratings_matrix[r][item_idx] is not None
        ]
        if len(item_values) >= 2:
            items_data.append(item_values)
            all_values.extend(item_values)

    if not items_data or len(all_values) < 2:
        return 0.0

    n_total = len(all_values)

    # Observed disagreement (D_o) via coincidence matrix
    # Each item contributes pairs weighted by 1/(m_u - 1)
    observed_disagreement = 0.0
    for item_values in items_data:
        m = len(item_values)
        weight = 1.0 / (m - 1)
        for i in range(m):
            for j in range(i + 1, m):
                observed_disagreement += (item_values[i] - item_values[j]) ** 2 * 2.0 * weight

    # Expected disagreement (D_e) from marginal frequencies
    # D_e = 1/(n-1) * sum over all c,k pairs of n_c * n_k * delta(c,k)
    # For interval/ordinal squared-difference: delta(c,k) = (c-k)^2
    arr = np.array(all_values, dtype=np.float64)
    # Use vectorized pairwise: sum of (x_i - x_j)^2 for all i<j
    # = n * sum(x^2) - (sum(x))^2 ... via identity
    sum_sq = float(np.sum(arr**2))
    sum_val = float(np.sum(arr))
    expected_disagreement = 2.0 * (n_total * sum_sq - sum_val**2) / (n_total * (n_total - 1))

    if abs(expected_disagreement) < 1e-12:
        return 1.0  # Perfect agreement (no variance)

    # Canonical: alpha = 1 - D_o / D_e  (Krippendorff 2011)
    # observed_disagreement is accumulated raw; divide by n_total for mean per-value
    alpha = 1.0 - (observed_disagreement / n_total) / expected_disagreement
    return float(np.clip(alpha, -1.0, 1.0))
