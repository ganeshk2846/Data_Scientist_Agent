"""V2 semantic layer: completeness, metric aggregation, table registry, layers.

Nothing here imports a model client. Every figure this package reports is a
row count read from the warehouse through a read-only connection, or a fixed
catalog fact (SAFE-8).
"""
