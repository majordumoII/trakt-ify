from trakt_ify.graph import GraphConfig, build_graph


def _watched(*ids: int) -> dict[int, dict]:
    return {i: {"title": f"Film {i}", "year": 2000 + i, "plays": 1} for i in ids}


def test_jaccard_uses_full_related_sets_not_library_intersection():
    # 1 and 2 share three catalog titles (100-102) that are NOT in the library.
    # Intersecting with the library first would leave them unconnected.
    related = {1: {100, 101, 102, 103}, 2: {100, 101, 102, 104}}
    payload = build_graph(related, _watched(1, 2), "u", GraphConfig(min_weight=0.0))

    assert len(payload.edges) == 1
    edge = payload.edges[0]
    # R'(1) = {1,100..103}, R'(2) = {2,100..102,104}: |n| = 3, |u| = 7
    assert edge.shared == 3
    assert abs(edge.weight - 3 / 7) < 1e-4


def test_direct_listing_counts_and_weight_is_bounded():
    related = {1: {2}, 2: {1}}
    payload = build_graph(related, _watched(1, 2), "u", GraphConfig(min_weight=0.0))
    assert payload.edges[0].weight == 1.0


def test_min_weight_prunes_and_isolated_nodes_drop():
    related = {1: {100, 101}, 2: {100, 200, 201, 202, 203, 204}, 3: {300}}
    payload = build_graph(related, _watched(1, 2, 3), "u", GraphConfig(min_weight=0.2))
    assert payload.edges == []
    assert payload.nodes == []
    assert payload.meta.movie_count == 3


def test_unwatched_sources_are_ignored_and_communities_ranked():
    related = {
        1: {10, 11, 12}, 2: {10, 11, 12}, 3: {10, 11, 12},
        4: {20, 21}, 5: {20, 21},
        99: {10, 11, 12},  # not watched
    }
    payload = build_graph(related, _watched(1, 2, 3, 4, 5), "u", GraphConfig(min_weight=0.1))
    ids = {n.id for n in payload.nodes}
    assert 99 not in ids
    by_id = {n.id: n for n in payload.nodes}
    assert by_id[1].community == by_id[2].community == 0  # largest first
    assert by_id[4].community == by_id[5].community == 1


def test_top_k_caps_edges_per_node():
    hub = {i: {1000} for i in range(1, 21)}
    payload = build_graph(hub, _watched(*range(1, 21)), "u", GraphConfig(min_weight=0.0, top_k=3))
    degrees = [n.degree for n in payload.nodes]
    # An edge survives if it's in either endpoint's top-k, so degree can exceed
    # k, but it must stay far below the complete graph's 19.
    assert max(degrees) < 19
    assert payload.meta.edge_count < 190
