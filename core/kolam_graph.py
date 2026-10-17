"""A constructive one-component Sikku diagram, with explicit crossing pairings.

Start with one four-corner cycle per pulli. For every edge of a spanning tree,
delete the facing side of both cycles and splice their endpoints in parallel.
Each splice joins two components (a tree has no cycles). After V-1 splices the
corner graph is connected and 2-regular, hence a single closed circuit. Shared
geometric crossings on non-tree sides NEVER identify topological vertices.
"""
from __future__ import annotations

import math
import networkx as nx


def plan_grid(size: int, grid: str, notes: list[dict]) -> dict:
    if not 2 <= size <= 15 or grid not in {"ner", "idukku"}:
        raise ValueError("Choose ner/idukku and a grid size from 2 to 15.")
    lattice = nx.grid_2d_graph(size, size)
    for k, (u, v) in enumerate(sorted(lattice.edges())):
        note = notes[k % len(notes)] if notes else {}
        pitch = float(note.get("semitone", 0))
        gamaka = float(note.get("gamaka", 0))
        # No random seed or process-dependent hash: music + grid fully determine it.
        phase = (u[0] * 31 + u[1] * 17 + v[0] * 13 + v[1] * 7)
        lattice[u][v]["weight"] = (1 + math.sin(phase + pitch * .7)) + gamaka * .003 + k * 1e-7
    tree = nx.minimum_spanning_tree(lattice, weight="weight")
    graph = nx.Graph()
    a = .24
    offsets = [(-a, -a), (a, -a), (a, a), (-a, a)]
    for dot in sorted(lattice):
        for c, offset in enumerate(offsets):
            graph.add_node((*dot, c), point=[dot[0] + offset[0], dot[1] + offset[1]])
            graph.add_edge((*dot, c), (*dot, (c + 1) % 4))
    # Facing corner pairs ordered across the same direction.
    def faces(u, v):
        return ([1, 2], [0, 3]) if v[0] > u[0] else ([3, 2], [0, 1])

    crossing_specs = {}
    for u, v in sorted(lattice.edges()):
        ca, cb = faces(u, v)
        if tree.has_edge(u, v):
            graph.remove_edge((*u, ca[0]), (*u, ca[1]))
            graph.remove_edge((*v, cb[0]), (*v, cb[1]))
            for i in range(2):
                graph.add_edge((*u, ca[i]), (*v, cb[i]))
        else:
            cross_id = f"{u[0]}-{u[1]}:{v[0]}-{v[1]}"
            mid = [(u[0] + v[0]) / 2, (u[1] + v[1]) / 2]
            for dot, corners, over in [(u, ca, True), (v, cb, False)]:
                key = frozenset([(*dot, corners[0]), (*dot, corners[1])])
                normal = [mid[0] - dot[0], mid[1] - dot[1]]
                crossing_specs[key] = dict(id=cross_id, point=mid, dot=dot,
                                           normal=normal, over=over)

    loops = nx.number_connected_components(graph)
    if loops != 1 or not all(d == 2 for _, d in graph.degree()) or not nx.is_eulerian(graph):
        raise RuntimeError("Structural single-loop invariant failed.")
    circuit = list(nx.eulerian_circuit(graph, source=(0, 0, 0)))
    anchors = []
    for u, v in circuit:
        anchors.append({"point": graph.nodes[u]["point"], "crossing": None})
        spec = crossing_specs.get(frozenset([u, v]))
        if spec:
            start, end = graph.nodes[u]["point"], graph.nodes[v]["point"]
            delta = [end[0] - start[0], end[1] - start[1]]
            norm = math.hypot(*delta)
            # Orient using the side's traversal, preserving the two transverse strands.
            canonical = 1 if (delta[1] if abs(delta[1]) > abs(delta[0]) else delta[0]) > 0 else -1
            tangent = [delta[i] / norm + spec["normal"][i] * .9 * canonical for i in range(2)]
            anchors.append({"point": spec["point"], "crossing": spec["id"],
                            "over": spec["over"], "tangent": tangent})

    def transform(point):
        x, y = point
        if grid == "idukku":
            return [(x - y) / math.sqrt(2), (x + y - (size - 1)) / math.sqrt(2)]
        return [x - (size - 1) / 2, y - (size - 1) / 2]

    for anchor in anchors:
        anchor["point"] = transform(anchor["point"])
        if "tangent" in anchor and grid == "idukku":
            x, y = anchor["tangent"]
            anchor["tangent"] = [(x - y) / math.sqrt(2), (x + y) / math.sqrt(2)]
    return dict(anchors=anchors, dots=[transform(d) for d in sorted(lattice)],
                loop_count=loops, closed=True, degree=2, dot_count=size * size,
                splice_count=tree.number_of_edges(), crossing_count=len(crossing_specs) // 2,
                graph_edges=graph.number_of_edges(), grid=grid, size=size)
