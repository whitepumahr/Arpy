from __future__ import annotations

try:
    from .sc2_helper import circles_intersect as r_circles_intersect
    from .sc2_helper import find_points_inside_circle as r_find_points_inside_circle
except ImportError:
    import math as _math

    def r_circles_intersect(c1, c2, r1, r2):
        dx = c1[0] - c2[0]
        dy = c1[1] - c2[1]
        dist = _math.sqrt(dx * dx + dy * dy)
        return dist < r1 + r2

    def r_find_points_inside_circle(center, radius, map_height, map_width):
        result = []
        cx, cy = int(center[0]), int(center[1])
        r = int(radius)
        for x in range(max(0, cx - r), min(map_width, cx + r + 1)):
            for y in range(max(0, cy - r), min(map_height, cy + r + 1)):
                dx = x - cx
                dy = y - cy
                if dx * dx + dy * dy <= r * r:
                    result.append((x, y))
        return result


def circles_intersect(
    circle1_point2, circle2_point2, circle1_radius, circle2_radius
) -> bool:
    return r_circles_intersect(
        (circle1_point2[0], circle1_point2[1]),
        (circle2_point2[0], circle2_point2[1]),
        circle1_radius,
        circle2_radius,
    )


def find_points_inside_circle(
    point, radius: float, map_height: int, map_width: int
) -> list[tuple[int, int]]:
    return r_find_points_inside_circle(point, radius, map_height, map_width)
