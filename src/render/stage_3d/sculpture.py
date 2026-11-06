"""Actual contour sidewalls for the clean 3D typography preset."""

import numpy as np

VERTEX = '''
#version 330
uniform mat4 mvp;
uniform mat4 model;
uniform mat3 normal_matrix;
in vec3 position;
in vec3 normal;
out vec3 world;
out vec3 surface_normal;
void main() {
    vec4 p = model*vec4(position,1.);
    world = p.xyz;
    surface_normal = normalize(normal_matrix*normal);
    gl_Position = mvp*vec4(position,1.);
}
'''

FRAGMENT = '''
#version 330
uniform vec3 eye;
uniform vec3 tint;
uniform float opacity;
uniform float time;
in vec3 world;
in vec3 surface_normal;
out vec4 color;
void main() {
    vec3 n=normalize(surface_normal);
    vec3 view=normalize(eye-world);
    vec3 key=normalize(vec3(-.45+.2*sin(time*.55),.75,1.));
    vec3 half_vector=normalize(key+view);
    float diffuse=.26+.64*max(0.,dot(n,key));
    float specular=pow(max(0.,dot(n,half_vector)),38.);
    float rim=pow(1.-abs(dot(n,view)),4.);
    vec3 shade=tint*diffuse+vec3(.86,.91,1.)*(specular*.7+rim*.12);
    color=vec4(clamp(shade,0.,1.)*opacity,opacity);
}
'''


def side_vertices(mask):
    """Normalized xy contours with front z=0 and back z=-1, including counter walls."""
    from skimage.measure import approximate_polygon, find_contours

    alpha = np.asarray(mask, dtype=np.float32) / 255
    height, width = alpha.shape
    vertices = []
    for contour in find_contours(alpha, 0.5):
        contour = approximate_polygon(contour, tolerance=0.85)
        if len(contour) < 4:
            continue
        if np.linalg.norm(contour[0] - contour[-1]) > 0.1:
            contour = np.vstack([contour, contour[0]])
        for a, b in zip(contour, contour[1:]):
            delta = b - a
            length = float(np.linalg.norm(delta))
            if length < 0.1:
                continue
            # Pixel-space outward normal, verified against the alpha field for holes as well as outer edges.
            ny, nx = -delta[1] / length, delta[0] / length
            midpoint = (a + b) / 2
            probe = np.rint(midpoint + np.array([ny, nx]) * 1.5).astype(int)
            if 0 <= probe[0] < height and 0 <= probe[1] < width and alpha[tuple(probe)] > 0.5:
                ny, nx = -ny, -nx
            normal = (nx * width, -ny * height, 0.0)
            af = (a[1] / width - 0.5, 0.5 - a[0] / height, 0.0)
            bf = (b[1] / width - 0.5, 0.5 - b[0] / height, 0.0)
            ab = (*af[:2], -1.0)
            bb = (*bf[:2], -1.0)
            for point in (af, bf, bb, af, bb, ab):
                vertices.append((*point, *normal))
    return np.asarray(vertices, dtype='f4').reshape((-1, 6))
