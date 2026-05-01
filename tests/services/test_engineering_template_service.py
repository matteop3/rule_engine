"""
Unit tests for the engineering template service.

Covers:
- `would_create_cycle`: self-loop, two-node, three-node cycles, longer chains,
  shortcuts, empty graph, disconnected sub-graphs, and diamond shapes.
- `acquire_template_graph_lock`: executes successfully against PostgreSQL.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import EngineeringTemplateItem
from app.services.engineering_template import acquire_template_graph_lock, would_create_cycle
from tests.fixtures.catalog_items import ensure_catalog_entry


def _add_edge(db: Session, parent: str, child: str, *, sequence: int = 0) -> EngineeringTemplateItem:
    """Insert a single template edge after ensuring both catalog rows exist."""
    ensure_catalog_entry(db, parent)
    ensure_catalog_entry(db, child)
    edge = EngineeringTemplateItem(
        parent_part_number=parent,
        child_part_number=child,
        quantity=Decimal("1"),
        sequence=sequence,
    )
    db.add(edge)
    db.commit()
    return edge


# ============================================================
# would_create_cycle
# ============================================================


def test_self_loop_is_reported_as_cycle(db_session: Session) -> None:
    ensure_catalog_entry(db_session, "A")

    cycles, path = would_create_cycle(db_session, "A", "A")

    assert cycles is True
    assert path == ["A", "A"]


def test_self_loop_does_not_query_template_graph(db_session: Session) -> None:
    """Self-loop is short-circuited before touching catalog or template tables."""
    cycles, path = would_create_cycle(db_session, "GHOST", "GHOST")

    assert cycles is True
    assert path == ["GHOST", "GHOST"]


def test_two_node_cycle(db_session: Session) -> None:
    _add_edge(db_session, "A", "B")

    cycles, path = would_create_cycle(db_session, "B", "A")

    assert cycles is True
    assert path == ["B", "A", "B"]


def test_three_node_cycle(db_session: Session) -> None:
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "B", "C")

    cycles, path = would_create_cycle(db_session, "C", "A")

    assert cycles is True
    assert path == ["C", "A", "B", "C"]


def test_long_chain_closing_edge_creates_cycle(db_session: Session) -> None:
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "B", "C")
    _add_edge(db_session, "C", "D")

    cycles, path = would_create_cycle(db_session, "D", "A")

    assert cycles is True
    assert path == ["D", "A", "B", "C", "D"]


def test_chain_extension_does_not_create_cycle(db_session: Session) -> None:
    """Adding A→D when D is a fresh part is safe even if A→B→C exists."""
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "B", "C")
    ensure_catalog_entry(db_session, "D")

    cycles, path = would_create_cycle(db_session, "A", "D")

    assert cycles is False
    assert path == []


def test_shortcut_edge_does_not_create_cycle(db_session: Session) -> None:
    """A→C is a shortcut over A→B→C; no cycle, just a redundant path."""
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "B", "C")

    cycles, path = would_create_cycle(db_session, "A", "C")

    assert cycles is False
    assert path == []


def test_empty_graph_never_cycles(db_session: Session) -> None:
    ensure_catalog_entry(db_session, "A")
    ensure_catalog_entry(db_session, "B")

    cycles, path = would_create_cycle(db_session, "A", "B")

    assert cycles is False
    assert path == []


def test_disconnected_sub_graphs_do_not_cycle(db_session: Session) -> None:
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "X", "Y")

    a_to_x_cycles, _ = would_create_cycle(db_session, "A", "X")
    y_to_a_cycles, _ = would_create_cycle(db_session, "Y", "A")

    assert a_to_x_cycles is False
    assert y_to_a_cycles is False


def test_diamond_shape_closing_edge_creates_cycle(db_session: Session) -> None:
    """Diamond A→B, A→C, B→D, C→D; adding D→A closes a cycle through one branch."""
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "A", "C")
    _add_edge(db_session, "B", "D")
    _add_edge(db_session, "C", "D")

    cycles, path = would_create_cycle(db_session, "D", "A")

    assert cycles is True
    assert path[0] == "D"
    assert path[-1] == "D"
    assert path[1] == "A"
    assert path[2] in {"B", "C"}
    assert len(path) == 4


def test_reverse_direction_in_chain_is_safe(db_session: Session) -> None:
    """Given A→B→C, an edge from a fresh node into A does not create a cycle."""
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "B", "C")
    ensure_catalog_entry(db_session, "ROOT")

    cycles, _ = would_create_cycle(db_session, "ROOT", "A")

    assert cycles is False


def test_cycle_detection_handles_visited_nodes(db_session: Session) -> None:
    """A node reachable through multiple paths is visited at most once."""
    _add_edge(db_session, "A", "B")
    _add_edge(db_session, "A", "C")
    _add_edge(db_session, "B", "D")
    _add_edge(db_session, "C", "D")
    _add_edge(db_session, "D", "E")

    cycles, _ = would_create_cycle(db_session, "A", "F")

    assert cycles is False


# ============================================================
# acquire_template_graph_lock
# ============================================================


def test_advisory_lock_acquires_without_error(db_session: Session) -> None:
    acquire_template_graph_lock(db_session)


def test_advisory_lock_is_idempotent_within_transaction(db_session: Session) -> None:
    """Re-acquiring the same advisory lock within a single transaction is allowed."""
    acquire_template_graph_lock(db_session)
    acquire_template_graph_lock(db_session)


@pytest.mark.parametrize("calls", [1, 3, 5])
def test_advisory_lock_handles_repeated_calls(db_session: Session, calls: int) -> None:
    for _ in range(calls):
        acquire_template_graph_lock(db_session)
