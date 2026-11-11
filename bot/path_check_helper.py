
Path connectivity checker for the Arpy StarCraft2 bot.

Provides a PathChecker class that uses BFS on the pathing grid
to determine whether two points are connected by a walkable path.

This is the pure-Python fallback (the Cython version is faster but
requires compilation, which may not be available in all deployment
environments).
"""

from collections import deque
from sc2.position import Point2


class PathChecker:
    """Check walkable connectivity between two Point2 positions.

    Usage:
        pc = PathChecker(bot)          # bot = the Arpy instance
        connected = pc.connected(a, b) # True if a walkable path exists
    """

    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def connected(self, a, b, step=1.0, max_nodes=5000):
        """Return True if *a* and *b* are connected via the pathing grid.

        Parameters
        ----------
        a, b : Point2
            Start and end positions.
        step : float
            Grid resolution for the BFS (1.0 = every tile).
        max_nodes : int
            Safety cap on visited nodes to avoid per-frame lag.

        The BFS explores walkable tiles from *a*.  If it reaches a tile
        within ``step`` distance of *b*, the two points are considered
        connected.
        """
        if a is None or b is None:
            return False

        # Quick check: if both points are on the same tile they are
        # trivially connected.
        if a.distance_to(b) <= step:
            return True

        # If either point is not in the pathing grid, they cannot be
        # connected (unless they are adjacent to a walkable tile).
        if not self.bot.in_pathing_grid(a) and not self._has_walkable_neighbor(a, step):
            return False
        if not self.bot.in_pathing_grid(b) and not self._has_walkable_neighbor(b, step):
            return False

        # BFS from a towards b
        visited = set()
        start_key = (int(round(a.x / step)), int(round(a.y / step)))
        goal_key = (int(round(b.x / step)), int(round(b.y / step)))

        queue = deque([start_key])
        visited.add(start_key)

        while queue and len(visited) < max_nodes:
            cx, cy = queue.popleft()

            # Reached the goal tile?
            if (cx, cy) == goal_key:
                return True

            # 4-directional expansion
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                nkey = (nx, ny)
                if nkey in visited:
                    continue
                pt = Point2((nx * step, ny * step))
                if self.bot.in_pathing_grid(pt):
                    visited.add(nkey)
                    queue.append(nkey)

        # Exhausted search budget -- assume not connected
        return False

    def _has_walkable_neighbor(self, pt, step=1.0):
        """Return True if at least one adjacent tile is walkable."""
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            npt = Point2((pt.x + dx * step, pt.y + dy * step))
            if self.bot.in_pathing_grid(npt):
                return True
        return False
