# cython: boundscheck=False, wraparound=False, cdivision=True
# cython: language_level=3
"""
Fast path connectivity checker using Cython BFS flood fill.

Uses the pathing_grid.data_numpy from python-sc2 to determine if
a unit at one position can physically reach another position.

Usage in main.py:
    from path_check_helper import PathChecker

    # In on_start():
    self.path_checker = PathChecker(self.game_info.pathing_grid)

    # Anywhere during the game:
    if self.path_checker.can_reach(unit.position, target_position):
        # Unit can physically walk there
    else:
        # No land path exists (e.g., island, blocked by unpathable terrain)
        pass
"""

import numpy as np
cimport numpy as np
from libc.stdlib cimport malloc, free

ctypedef np.uint8_t UINT8

cdef struct QueueNode:
    int x
    int y


def flood_fill_reachable(np.ndarray[UINT8, ndim=2] grid, int start_x, int start_y):
    """BFS flood fill from (start_x, start_y) on the pathing grid.

    Returns a Python set of (x, y) tuples representing all reachable pathable cells.
    This is useful for caching - compute once, check membership many times.
    """
    cdef int height = grid.shape[0]
    cdef int width = grid.shape[1]
    cdef np.ndarray[UINT8, ndim=2] visited = np.zeros((height, width), dtype=np.uint8)
    cdef int found, r, dy, dx, ny, nx, head, tail, i
    cdef QueueNode current

    # Clamp start to grid bounds
    if start_x < 0: start_x = 0
    if start_x >= width: start_x = width - 1
    if start_y < 0: start_y = 0
    if start_y >= height: start_y = height - 1

    # If start is not pathable, find nearest pathable cell
    if grid[start_y, start_x] == 0:
        found = 0
        for r in range(1, 10):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    ny = start_y + dy
                    nx = start_x + dx
                    if 0 <= ny < height and 0 <= nx < width and grid[ny, nx] != 0:
                        start_y = ny
                        start_x = nx
                        found = 1
                        break
                if found: break
            if found: break
        if not found:
            return set()

    # Allocate BFS queue
    cdef int max_queue = height * width
    cdef QueueNode *queue = <QueueNode *>malloc(max_queue * sizeof(QueueNode))
    if queue == NULL:
        return set()

    head = 0
    tail = 0

    queue[tail].x = start_x
    queue[tail].y = start_y
    tail += 1
    visited[start_y, start_x] = 1

    # 4-directional neighbors (SC2 pathing grid uses 4-connectivity)
    cdef int dirs[4][2]
    dirs[0][0] = 0; dirs[0][1] = -1
    dirs[1][0] = 0; dirs[1][1] = 1
    dirs[2][0] = -1; dirs[2][1] = 0
    dirs[3][0] = 1; dirs[3][1] = 0

    while head < tail:
        current = queue[head]
        head += 1

        for i in range(4):
            nx = current.x + dirs[i][0]
            ny = current.y + dirs[i][1]

            if 0 <= nx < width and 0 <= ny < height:
                if not visited[ny, nx] and grid[ny, nx] != 0:
                    visited[ny, nx] = 1
                    queue[tail].x = nx
                    queue[tail].y = ny
                    tail += 1

    free(queue)

    # Convert visited array to set of tuples
    result = set()
    for y in range(height):
        for x in range(width):
            if visited[y, x]:
                result.add((x, y))

    return result


def can_path_to(np.ndarray[UINT8, ndim=2] grid, int start_x, int start_y, int dest_x, int dest_y):
    """Check if a ground unit at (start_x, start_y) can reach (dest_x, dest_y).

    Does a BFS from start and stops as soon as dest is found (early exit).
    Much faster than flood_fill_reachable when you only need a yes/no answer.
    """
    cdef int height = grid.shape[0]
    cdef int width = grid.shape[1]
    cdef int found, r, dy, dx, ny, nx, head, tail, i
    cdef bint found_dest = False
    cdef QueueNode current

    # Clamp to grid bounds
    if start_x < 0: start_x = 0
    if start_x >= width: start_x = width - 1
    if start_y < 0: start_y = 0
    if start_y >= height: start_y = height - 1
    if dest_x < 0: dest_x = 0
    if dest_x >= width: dest_x = width - 1
    if dest_y < 0: dest_y = 0
    if dest_y >= height: dest_y = height - 1

    # Quick check: if dest is not pathable, can't reach it
    if grid[dest_y, dest_x] == 0:
        return False

    # If start == dest and start is pathable
    if start_x == dest_x and start_y == dest_y:
        return grid[start_y, start_x] != 0

    # Find nearest pathable cell to start if start is blocked
    if grid[start_y, start_x] == 0:
        found = 0
        for r in range(1, 10):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    ny = start_y + dy
                    nx = start_x + dx
                    if 0 <= ny < height and 0 <= nx < width and grid[ny, nx] != 0:
                        start_y = ny
                        start_x = nx
                        found = 1
                        break
                if found: break
            if found: break
        if not found:
            return False

    # Allocate visited and queue
    cdef np.ndarray[UINT8, ndim=2] visited = np.zeros((height, width), dtype=np.uint8)
    cdef int max_queue = height * width
    cdef QueueNode *queue = <QueueNode *>malloc(max_queue * sizeof(QueueNode))
    if queue == NULL:
        return False

    head = 0
    tail = 0

    queue[tail].x = start_x
    queue[tail].y = start_y
    tail += 1
    visited[start_y, start_x] = 1

    cdef int dirs[4][2]
    dirs[0][0] = 0; dirs[0][1] = -1
    dirs[1][0] = 0; dirs[1][1] = 1
    dirs[2][0] = -1; dirs[2][1] = 0
    dirs[3][0] = 1; dirs[3][1] = 0

    while head < tail:
        current = queue[head]
        head += 1

        for i in range(4):
            nx = current.x + dirs[i][0]
            ny = current.y + dirs[i][1]

            if nx == dest_x and ny == dest_y:
                found_dest = True
                break

            if 0 <= nx < width and 0 <= ny < height:
                if not visited[ny, nx] and grid[ny, nx] != 0:
                    visited[ny, nx] = 1
                    queue[tail].x = nx
                    queue[tail].y = ny
                    tail += 1

        if found_dest:
            break

    free(queue)
    return found_dest


def get_path_regions(np.ndarray[UINT8, ndim=2] grid):
    """Compute all connected pathable regions on the map.

    Returns a 2D numpy array of int32 where each pathable cell is labeled
    with its region ID (1, 2, 3, ...). Cells with value 0 are not pathable.

    This is the most efficient way to check connectivity between many points:
    compute once, then just check if region_id[start] == region_id[dest].
    """
    cdef int height = grid.shape[0]
    cdef int width = grid.shape[1]
    cdef np.ndarray[np.int32_t, ndim=2] regions = np.zeros((height, width), dtype=np.int32)
    cdef int region_id = 0
    cdef int head, tail, nx, ny, start_x, start_y, i
    cdef QueueNode current

    cdef int max_queue = height * width
    cdef QueueNode *queue = <QueueNode *>malloc(max_queue * sizeof(QueueNode))
    if queue == NULL:
        return regions

    cdef int dirs[4][2]
    dirs[0][0] = 0; dirs[0][1] = -1
    dirs[1][0] = 0; dirs[1][1] = 1
    dirs[2][0] = -1; dirs[2][1] = 0
    dirs[3][0] = 1; dirs[3][1] = 0

    for start_y in range(height):
        for start_x in range(width):
            if grid[start_y, start_x] != 0 and regions[start_y, start_x] == 0:
                region_id += 1
                head = 0
                tail = 0

                queue[tail].x = start_x
                queue[tail].y = start_y
                tail += 1
                regions[start_y, start_x] = region_id

                while head < tail:
                    current = queue[head]
                    head += 1

                    for i in range(4):
                        nx = current.x + dirs[i][0]
                        ny = current.y + dirs[i][1]

                        if 0 <= nx < width and 0 <= ny < height:
                            if grid[ny, nx] != 0 and regions[ny, nx] == 0:
                                regions[ny, nx] = region_id
                                queue[tail].x = nx
                                queue[tail].y = ny
                                tail += 1

    free(queue)
    return regions
