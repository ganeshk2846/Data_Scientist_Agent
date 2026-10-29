"""Read interfaces for the metadata catalog, join graph and value index."""
import hashlib
import json
from pathlib import Path


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CatalogIntegrityError(ValueError):
    """Published artifacts do not belong to the same completed build."""


class CatalogAPI:
    def __init__(self, catalog_path: str | Path):
        self.path = Path(catalog_path)
        self._manifest_path = self.path.parent / "published.json"
        raw = self.path.read_bytes()
        self.data = json.loads(raw.decode("utf-8"))
        self._published = self._load_manifest()
        expected = self._published.get("artifacts", {}).get(self.path.name)
        if not expected or hashlib.sha256(raw).hexdigest() != expected:
            raise CatalogIntegrityError(f"catalog publication mismatch: {self.path.name}")

    def _load_manifest(self) -> dict:
        if not self._manifest_path.exists():
            raise CatalogIntegrityError("catalog publication manifest is missing")
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _verify_published(self, name: str) -> None:
        expected = self._published.get("artifacts", {}).get(name)
        actual = _sha256(self.path.parent / name)
        if not expected or actual != expected:
            raise CatalogIntegrityError(f"catalog publication mismatch: {name}")

    @property
    def catalog_version(self):
        return self.data["catalog_version"]

    def tables(self):
        return sorted(self.data["tables"])

    def schema(self, table: str | None = None):
        tables = self.data["tables"]
        if table is not None and table not in tables:
            raise KeyError(table)
        return {table: tables[table]} if table else tables

    def join_edges(self, *, approved_only: bool = True):
        edges = self.data.get("joins", [])
        return [e for e in edges if not approved_only or e["status"] == "approved"]

    def index(self):
        """Return the build-time indexes, keeping callers behind the catalog API.

        The catalog is committed after the index. A partially published refresh
        is rejected because the artifact no longer matches the last committed
        publication manifest, instead of serving an index that does not match
        the catalog.
        """
        self._verify_published("index_build.json")
        payload = json.loads((self.path.parent / "index_build.json").read_text(encoding="utf-8"))
        catalog_version = self.data.get("catalog_version")
        index_version = payload.get("catalog_version")
        if catalog_version and index_version != catalog_version:
            raise CatalogIntegrityError(
                f"catalog/index publication mismatch: catalog={catalog_version} index={index_version}"
            )
        return payload

    def paths(self, start_table: str, end_table: str, *, approved_only: bool = True):
        return JoinGraph(self.data.get("joins", [])).paths(start_table, end_table, approved_only=approved_only)

    def graph(self):
        """Read-only query layer over the catalog knowledge graph."""
        return KnowledgeGraph(self.data.get("graph", {}))

    def graph_nodes(self, node_type: str | None = None):
        return self.graph().nodes_of_type(node_type)

    def graph_neighbors(self, node_id: str, *, edge_type: str | None = None):
        return self.graph().neighbors(node_id, edge_type=edge_type)

    def graph_paths(self, source: str, target: str, *, max_depth: int = 6):
        return self.graph().paths(source, target, max_depth=max_depth)

    def profile_warnings(self, table: str, column: str) -> list[str]:
        stats = self.data.get("profiles", {}).get(table, {}).get("columns", {}).get(column, {})
        if stats.get("sensitive"):
            return []
        warnings = []
        if stats.get("null_rate", 0) >= 0.2:
            warnings.append(f"high null share ({stats['null_rate']:.0%})")
        if len(stats.get("formats", [])) > 1:
            warnings.append("mixed formats")
        if column.casefold() in {"deleted", "is_deleted", "deleted_at", "is_active", "active"} or column.casefold().endswith("_deleted_at"):
            warnings.append("possible soft-delete/active flag; confirm filter semantics")
        return warnings

    def search(self, query: str, *, limit: int = 10):
        words = set(query.lower().split())
        items = self.index()["keyword"]
        ranked = []
        for item in items:
            if item["kind"] == "column" and item["name"].split(".", 1)[0] not in self.data["tables"]:
                continue
            text = (item["name"] + " " + item["text"]).lower()
            score = sum(1 for word in words if word in text)
            if score:
                ranked.append((score, item))
        return [item for _, item in sorted(ranked, key=lambda x: (-x[0], x[1]["name"]))[:limit]]

    def value_lookup(self, value: str, *, limit: int = 10):
        values = self.index()["value_index"]
        needle = value.casefold()
        return [{"column": col, "value": v} for col, vals in values.items() for v in vals if needle in str(v).casefold()][:limit]


def _edge_endpoints(value):
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item]
    return [value] if value else []


class KnowledgeGraph:
    """Undirected node/edge queries over the persisted catalog graph.

    Join edges store column lists on each side, so both scalar and list
    endpoints are expanded into pairwise adjacency.
    """

    def __init__(self, graph: dict):
        self.graph = graph or {}
        self.nodes = {node["id"]: node for node in self.graph.get("nodes", [])}
        self.edges = list(self.graph.get("edges", []))
        self._adjacency: dict[str, list[tuple[str, dict]]] = {}
        for edge in self.edges:
            for source in _edge_endpoints(edge.get("source")):
                for target in _edge_endpoints(edge.get("target")):
                    if source == target:
                        continue
                    self._adjacency.setdefault(source, []).append((target, edge))
                    self._adjacency.setdefault(target, []).append((source, edge))

    def node(self, node_id: str):
        return self.nodes.get(node_id)

    def nodes_of_type(self, node_type: str | None = None) -> list[str]:
        return sorted(node_id for node_id, node in self.nodes.items()
                      if node_type is None or node.get("type") == node_type)

    def neighbors(self, node_id: str, *, edge_type: str | None = None) -> list[str]:
        found = []
        for neighbor, edge in self._adjacency.get(node_id, []):
            if edge_type is not None and edge.get("type") != edge_type:
                continue
            if neighbor not in found:
                found.append(neighbor)
        return sorted(found)

    def paths(self, source: str, target: str, *, max_depth: int = 6) -> list[dict]:
        if source == target:
            return []
        if max_depth < 1:
            raise ValueError("max_depth must be positive")
        queue = [(source, [])]
        visited = {source}
        while queue:
            current, path = queue.pop(0)
            if len(path) >= max_depth:
                continue
            for neighbor, edge in self._adjacency.get(current, []):
                if neighbor in visited:
                    continue
                candidate = path + [edge]
                if neighbor == target:
                    return candidate
                visited.add(neighbor)
                queue.append((neighbor, candidate))
        return []


class JoinGraph:
    """Table-level paths; query callers see only explicitly approved edges by default."""

    def __init__(self, edges):
        self.edges = edges

    def paths(self, start_table: str, end_table: str, *, approved_only: bool = True):
        if start_table == end_table:
            return []
        adjacency = {}
        for edge in self.edges:
            if approved_only and edge.get("status") != "approved":
                continue
            if not approved_only and edge.get("status") == "rejected":
                continue
            left, right = edge["left"]["table"], edge["right"]["table"]
            adjacency.setdefault(left, []).append((right, edge))
            adjacency.setdefault(right, []).append((left, edge))
        queue = [start_table]
        previous = {start_table: None}
        for current in queue:
            if current == end_table:
                break
            for neighbor, edge in adjacency.get(current, []):
                if neighbor not in previous:
                    previous[neighbor] = (current, edge)
                    queue.append(neighbor)
        if end_table not in previous:
            return []
        result = []
        current = end_table
        while previous[current] is not None:
            prior, edge = previous[current]
            result.append(edge)
            current = prior
        return list(reversed(result))
