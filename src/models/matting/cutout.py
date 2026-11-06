"""BiRefNet background removal (rembg) for cutout illustrations."""
from __future__ import annotations
from PIL import Image


def remove_negative_space(source, biref_session):
    """Remove outer staging negative space while preserving drawn background features, props, and setting."""
    from rembg import remove
    import scipy.ndimage as ndi
    import numpy as np

    biref_cutout = remove(source, session=biref_session).convert('RGBA')
    biref_alpha = np.array(biref_cutout.getchannel('A'))

    arr = np.array(source.convert('RGB'))
    h, w, _ = arr.shape

    r, g, b = arr[..., 0].astype(float), arr[..., 1].astype(float), arr[..., 2].astype(float)
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    sat = np.where(max_c == 0, 0, (max_c - min_c) / (max_c + 1e-5))
    val = max_c

    corners = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]], dtype=float)
    light_corners = [c for c in corners if np.mean(c) > 210]
    corner_match = np.zeros((h, w), dtype=bool)
    if light_corners:
        ref_corner = np.mean(light_corners, axis=0)
        diff = np.linalg.norm(arr.astype(float) - ref_corner, axis=-1)
        corner_match = diff < 22

    is_neg_candidate = ((val > 232) & (sat < 0.10)) | corner_match

    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[0, :] = True
    border_mask[-1, :] = True
    border_mask[:, 0] = True
    border_mask[:, -1] = True

    structure = ndi.generate_binary_structure(2, 2)
    labeled, _ = ndi.label(is_neg_candidate, structure=structure)
    border_labels = np.unique(labeled[border_mask])
    border_labels = border_labels[border_labels != 0]

    is_negative_space = np.isin(labeled, border_labels)
    painted_content = ~is_negative_space
    painted_content = ndi.binary_fill_holes(painted_content)

    dist_inside = ndi.distance_transform_edt(painted_content)
    edge_alpha = np.clip(dist_inside * 128, 0, 255).astype(np.uint8)

    combined_alpha = np.maximum(biref_alpha, edge_alpha)
    combined_alpha[is_negative_space & (val > 238)] = 0
    from models.matting.staging import staging_alpha
    staging = staging_alpha(source)  # a flat staging backdrop of any colour (grey, beige...), not only near-white
    if staging is not None:
        combined_alpha = np.minimum(combined_alpha, (staging[0]*255).astype(np.uint8))

    result = source.convert('RGBA')
    result.putalpha(Image.fromarray(combined_alpha))
    if staging is not None:
        result = without_screen_colour(result, staging[1])
    return result


def without_screen_colour(cutout, reference, band=3):
    """A chroma screen's colour taken out of a cutout's edge, where a soft pixel is part subject, part screen (a
    green screen would leave a green halo): within `band` pixels of the cut, green above the stronger of red and
    blue is lowered to it on a green screen, and red and blue above green on a magenta one. Colours the screen does
    not dominate are left exactly as painted, so the subject itself never shifts; other backdrops (grey, beige) are
    left alone."""
    import numpy as np
    import scipy.ndimage as ndi
    pixels = np.asarray(cutout, dtype=float)
    rgb, alpha = pixels[..., :3], pixels[..., 3]/255
    r, g, b = np.asarray(reference, dtype=float)
    edge = ndi.binary_dilation(alpha < .5, iterations=band) & (alpha > 0)
    if g-max(r, b) > 80:      # a green screen
        rgb[..., 1] = np.where(edge, np.minimum(rgb[..., 1], np.maximum(rgb[..., 0], rgb[..., 2])), rgb[..., 1])
    elif min(r, b)-g > 80:    # a magenta screen
        spill = np.clip(np.minimum(rgb[..., 0], rgb[..., 2])-rgb[..., 1], 0, None)*edge
        rgb[..., 0], rgb[..., 2] = rgb[..., 0]-spill, rgb[..., 2]-spill
    pixels[..., :3] = rgb
    return Image.fromarray(pixels.round().astype('uint8'), 'RGBA')
