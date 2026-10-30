"""Rasterization and satin shading for the wind-driven silk surfaces."""
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

from effects.materials.fx import mix, rgb, shadow, shift, sm, smooth, sun
from effects.silk.geometry import grid_normals, sheet, word_cloth

SUPERSAMPLE = 2
FABRICS = (
    dict(face=(rgb(92, 12, 38), rgb(222, 64, 102), rgb(255, 205, 207)),
         back=(rgb(83, 34, 67), rgb(197, 94, 131), rgb(255, 220, 220)),
         opacity=(.42, .58)),
    dict(face=(rgb(9, 75, 83), rgb(38, 191, 190), rgb(194, 255, 247)),
         back=(rgb(18, 55, 103), rgb(57, 144, 201), rgb(198, 233, 255)),
         opacity=(.42, .58)),
    dict(face=(rgb(25, 43, 115), rgb(65, 111, 230), rgb(210, 223, 255)),
         back=(rgb(66, 37, 105), rgb(139, 94, 203), rgb(229, 212, 255)),
         opacity=(.42, .58)),
    dict(face=(rgb(106, 54, 11), rgb(236, 153, 43), rgb(255, 238, 174)),
         back=(rgb(112, 37, 39), rgb(211, 99, 68), rgb(255, 211, 169)),
         opacity=(.42, .58)),
    dict(face=(rgb(66, 28, 105), rgb(161, 92, 211), rgb(239, 211, 255)),
         back=(rgb(107, 34, 94), rgb(218, 91, 162), rgb(255, 215, 235)),
         opacity=(.42, .58)),
    dict(face=(rgb(14, 78, 53), rgb(55, 182, 106), rgb(205, 252, 195)),
         back=(rgb(34, 69, 89), rgb(90, 157, 186), rgb(212, 239, 248)),
         opacity=(.42, .58)),
)


def rasterize(size, xy, triangles, order):
    """Draw triangles (in `order`, later ones on top) into an id buffer; 0 means empty."""
    image = Image.new('I', size)
    draw = ImageDraw.Draw(image)
    for k in order:
        a, b, c = triangles[k]
        draw.polygon((tuple(xy[a]), tuple(xy[b]), tuple(xy[c])), fill=int(k)+1)
    return np.asarray(image)


def barycentric(px, py, xy, tri):
    p0, p1, p2 = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
    v0, v1 = p1-p0, p2-p0
    dx, dy = px-p0[:, 0], py-p0[:, 1]
    det = v0[:, 0]*v1[:, 1]-v1[:, 0]*v0[:, 1]
    det = np.where(np.abs(det) < 1e-9, 1e-9, det)
    l1 = np.clip((dx*v1[:, 1]-v1[:, 0]*dy)/det, 0, 1)
    l2 = np.clip((v0[:, 0]*dy-dx*v0[:, 1])/det, 0, 1)
    total = np.maximum(1., l1+l2)
    l1, l2 = l1/total, l2/total
    return np.stack((1-l1-l2, l1, l2), 1)


def shade(mesh, tri_ids, bary, light):
    """Satin colour and opacity for pixels whose layer is triangle `tri_ids` at barycentric `bary`."""
    tri = mesh['triangles'][tri_ids]

    def interp(values):
        v = values[tri]
        return np.einsum('kj,kj...->k...', bary, v)
    n = interp(mesh['normal'])
    n /= np.maximum(1e-6, np.linalg.norm(n, axis=1, keepdims=True))
    w = interp(mesh['w'])
    arc = interp(mesh['arc'])
    cavity = interp(mesh['cavity'])
    visible = interp(mesh['visible'])
    density = interp(mesh['density'])
    letter = mesh['letter'][tri[:, 0]]
    face = n[:, 2] >= 0
    n = n*np.where(face, 1., -1.)[:, None]
    fabrics = [FABRICS[i % len(FABRICS)] for i in range(int(letter.max())+1)]
    dark_f, base_f = (np.array([f['face'][c] for f in fabrics])[letter] for c in range(2))
    dark_b, base_b = (np.array([f['back'][c] for f in fabrics])[letter] for c in range(2))
    side = face[:, None].astype(float)
    dark, base = mix(dark_b, dark_f, side), mix(base_b, base_f, side)

    ndl = n@light
    diffuse = np.clip((ndl+.7)/1.7, 0, 1)
    colour = mix(dark, base, (.32+.58*diffuse)[:, None])
    grazing = 1-np.clip(n[:, 2], 0, 1)
    colour = colour*(1-.22*cavity)[:, None]
    # A subtle seam defines the thin free edge without a bright reflective rim.
    hem = smooth(np.abs(w), .88, .95)
    colour *= (1-.09*hem)[:, None]

    sheer, laid = (np.array([f['opacity'][k] for f in fabrics])[letter] for k in range(2))
    opacity = (sheer+(laid-sheer)*np.clip(density, 0, 1))*.82
    # A single sheet stays sheer even at a grazing angle.  Overlapping folds become denser through the
    # layer composite, instead of forcing every edge-on triangle nearly opaque.
    alpha = opacity*(.78+.32*grazing)
    alpha = np.maximum(alpha, hem*(opacity+.06))*np.clip(visible, 0, 1)
    return np.clip(colour, 0, 1), alpha, arc, w, letter


def paint_silk(F, canvas, t):
    """Lay every letter's sheet of silk at progress t into `canvas`."""
    cloth = word_cloth(F)
    if cloth is None:
        return
    meshes = []
    for k, letter in enumerate(cloth['letters']):
        mesh = sheet(F, t, cloth, k)
        if mesh is not None:
            mesh['letter'] = letter['index']
            meshes.append(mesh)
    if not meshes:
        return

    points, visible, arc, w, cavity, density, normal, tangent, letter, triangles = [], [], [], [], [], [], [], [], [], []
    offset = 0
    for mesh in meshes:
        ns, nw = mesh['points'].shape[:2]
        n, tg = grid_normals(mesh['points'])
        idx = np.arange(ns*nw).reshape(ns, nw)
        a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
        quads = np.concatenate((np.stack((a, b, c), 1), np.stack((a, c, d), 1)))
        vis = mesh['visible'].ravel()
        quads = quads[vis[quads].min(1) > .5]
        triangles.append(quads+offset)
        offset += ns*nw
        for store, value in ((points, mesh['points']), (visible, mesh['visible']), (arc, mesh['arc']), (w, mesh['w']),
                             (cavity, mesh['cavity']), (density, mesh['density']), (normal, n), (tangent, tg)):
            value = np.asarray(value)
            store.append(value.reshape(ns*nw, *value.shape[2:]))
        letter.append(np.full(ns*nw, mesh['letter']))
    mesh = dict(points=np.concatenate(points), visible=np.concatenate(visible), arc=np.concatenate(arc),
                w=np.concatenate(w), cavity=np.concatenate(cavity), density=np.concatenate(density), normal=np.concatenate(normal),
                tangent=np.concatenate(tangent), letter=np.concatenate(letter), triangles=np.concatenate(triangles))
    tris = mesh['triangles']
    if not len(tris):
        return
    S = SUPERSAMPLE
    xy = mesh['points'][:, :2]*S
    depth = mesh['points'][tris, 2].mean(1)
    H2, W2 = F.H*S, F.W*S
    box = np.stack((xy[tris, 0].min(1), xy[tris, 1].min(1), xy[tris, 0].max(1), xy[tris, 1].max(1)), 1)
    onstage = (box[:, 2] >= 0) & (box[:, 3] >= 0) & (box[:, 0] < W2) & (box[:, 1] < H2)
    order = np.argsort(depth, kind='stable')
    order = order[onstage[order]]
    if not len(order):
        return
    near = rasterize((W2, H2), xy, tris, order)
    far = rasterize((W2, H2), xy, tris, order[::-1])

    light = sun(-2.25, .72)
    ys, xs = np.nonzero(near)
    px, py = xs+.5, ys+.5
    ids = near[ys, xs]-1
    colour_n, alpha_n, arc_n, w_n, letter_n = shade(mesh, ids, barycentric(px, py, xy, tris[ids]), light)
    z_near = np.full((H2, W2), -1e9)
    z_near[ys, xs] = np.einsum('kj,kj->k', barycentric(px, py, xy, tris[ids]), mesh['points'][tris[ids], 2])
    a_near = np.zeros((H2, W2))
    a_near[ys, xs] = alpha_n

    # The far layer only counts where it is a different piece of cloth, not the same one seen again.
    far_ids = far[ys, xs]-1
    bary_far = barycentric(px, py, xy, tris[far_ids])
    far_arc = np.einsum('kj,kj->k', bary_far, mesh['arc'][tris[far_ids]])
    far_w = np.einsum('kj,kj->k', bary_far, mesh['w'][tris[far_ids]])
    far_letter = mesh['letter'][tris[far_ids, 0]]
    distinct = (far_letter != letter_n) | (np.abs(far_arc-arc_n) > .12) | (np.abs(far_w-w_n) > .7)

    # Each layer shades what lies below it: compare depth with the near layer seen from the light.
    reach = F.u*.045*S
    lifted = shift(z_near, round(-light[1]/light[2]*reach), round(-light[0]/light[2]*reach))
    cover = shift(a_near, round(-light[1]/light[2]*reach), round(-light[0]/light[2]*reach))

    def shadow_on(z):
        return np.clip((lifted[ys, xs]-z-F.u*.01)/(F.u*.12), 0, 1)*cover[ys, xs]
    occlusion = np.zeros((H2, W2))
    occlusion[ys, xs] = shadow_on(z_near[ys, xs])
    occlusion = gaussian_filter(occlusion, F.u*.02*S)
    colour_n = colour_n*(1-.45*occlusion[ys, xs])[:, None]

    premult = np.zeros((H2, W2, 3))
    alpha = np.zeros((H2, W2))
    premult[ys, xs] = colour_n*alpha_n[:, None]
    alpha[ys, xs] = alpha_n
    if distinct.any():
        k = np.nonzero(distinct)[0]
        colour_f, alpha_f, *_ = shade(mesh, far_ids[k], bary_far[k], light)
        z_far = np.einsum('kj,kj->k', bary_far[k], mesh['points'][tris[far_ids[k]], 2])
        under = 1-.55*np.maximum(occlusion[ys[k], xs[k]], alpha_n[k]*np.clip((z_near[ys[k], xs[k]]-z_far)/(F.u*.1), 0, 1)*.6)
        colour_f = colour_f*under[:, None]
        rest = 1-alpha_n[k]
        premult[ys[k], xs[k]] += colour_f*(alpha_f*rest)[:, None]
        alpha[ys[k], xs[k]] += alpha_f*rest

    premult = premult.reshape(F.H, S, F.W, S, 3).mean((1, 3))
    alpha = alpha.reshape(F.H, S, F.W, S).mean((1, 3))
    # The final contour is the actual glyph.  The moving surface bends into it; at the very end, cloth
    # behind edge-on pleats fills the remaining gaps and loose material outside the stroke folds behind.
    settled = sm(t, .68, .98)
    contour = 1-settled+settled*F.ink
    premult *= contour[..., None]
    alpha *= contour
    backing = np.zeros_like(premult)
    for index, (left, right) in enumerate(cloth['spans']):
        fabric = FABRICS[index % len(FABRICS)]
        left, right = max(0, int(left)), min(F.W, int(right))
        wave = .7+.18*np.sin(math.tau*(F.X[:, left:right]*2.2+F.Y[:, left:right]*.55)+index*1.3)
        backing[:, left:right] = mix(fabric['face'][0], fabric['face'][1], wave[..., None])
    backing_alpha = F.ink*settled*np.clip((.58-alpha)/.58, 0, 1)*.58
    canvas.over(backing, backing_alpha)
    # A broad opaque outline made the transparent sheets read as cut-out stickers.  Keep only a faint,
    # close contact shadow; the folds themselves provide the depth cues.
    canvas.over(rgb(8, 24, 30), shadow(alpha, F, .025, .04, .025, .065))
    canvas.c[..., :3] = premult+canvas.c[..., :3]*(1-alpha[..., None])
    canvas.c[..., 3] = alpha+canvas.c[..., 3]*(1-alpha)
