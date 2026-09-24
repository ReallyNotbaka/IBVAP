"""Tactical vision enhancement filters: FLIR thermal simulations and defogging.

Provides military-grade image processing enhancements:
- White-Hot FLIR: High-temperature entities (humans, engines) render bright white.
- Black-Hot FLIR: Heat signatures render dark against ambient background.
- Ironbow False-Color Thermal: Standard military IR False-Color LUT (blue -> red -> yellow -> white).
- CLAHE Tactical Defog: Contrast Limited Adaptive Histogram Equalization with dark channel prior.
"""

from __future__ import annotations

import cv2
import numpy as np


def apply_white_hot_flir(image: np.ndarray) -> np.ndarray:
    """Simulate White-Hot Forward Looking Infrared (FLIR) thermal imaging."""
    if len(image.shape) == 3 and image.shape[2] == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # Contrast stretch with thermal curve emphasis
    norm = cv2.normalize(gray, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
    # Apply non-linear gamma curve to simulate radiometric temperature distribution
    lookup_table = np.array([((i / 255.0) ** 1.35) * 255 for i in np.arange(0, 256)]).astype("uint8")
    stretched = cv2.LUT(norm, lookup_table)
    # Subtle blur to emulate thermal diffusion / sensor point spread function
    blurred = cv2.GaussianBlur(stretched, (3, 3), 0)
    return cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)


def apply_black_hot_flir(image: np.ndarray) -> np.ndarray:
    """Simulate Black-Hot FLIR thermal imaging (inverted heat signature)."""
    white_hot = apply_white_hot_flir(image)
    return cv2.bitwise_not(white_hot)


def apply_ironbow_flir(image: np.ndarray) -> np.ndarray:
    """Simulate military Ironbow false-color thermal palette."""
    if len(image.shape) == 3 and image.shape[2] == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # Pre-process with CLAHE for local thermal contrast
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    # Apply Inferno / Ironbow colormap
    return cv2.applyColorMap(enhanced, cv2.COLORMAP_INFERNO)


def apply_tactical_defog(image: np.ndarray) -> np.ndarray:
    """Apply tactical defog / haze penetration using LAB CLAHE and unsharp masking."""
    if len(image.shape) != 3 or image.shape[2] != 3:
        return image.copy()

    # Convert to LAB color space
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # Apply CLAHE to luminance channel
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)

    # Merge back and convert to BGR
    merged = cv2.merge((cl, a, b))
    enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    # High-pass unsharp mask for perimeter edge clarity
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
    unsharp = cv2.addWeighted(enhanced, 1.35, gaussian, -0.35, 0)
    return np.clip(unsharp, 0, 255).astype(np.uint8)


def process_tactical_filter(image: np.ndarray, mode: str) -> np.ndarray:
    """Apply the specified tactical vision mode."""
    mode_lower = mode.strip().lower()
    if mode_lower in {"white-hot", "white_hot", "w_hot"}:
        return apply_white_hot_flir(image)
    if mode_lower in {"black-hot", "black_hot", "b_hot"}:
        return apply_black_hot_flir(image)
    if mode_lower in {"ironbow", "iron", "thermal"}:
        return apply_ironbow_flir(image)
    if mode_lower in {"defog", "clahe", "haze"}:
        return apply_tactical_defog(image)
    return image
