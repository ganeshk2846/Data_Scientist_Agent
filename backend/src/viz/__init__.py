"""Visualization agent: deterministic chart choice for a step's ToolResult.

The agent reads column roles, the tool and the intent and returns
``VisualizationSpec`` objects that name **columns** of data the envelope
already carries (VZ-1). It never computes, bins, sorts or rounds a figure and
never calls a model, so it behaves identically with or without Ollama
(SAFE-8).
"""

from viz.builder import ARTIFACT_PATH_SEPARATOR, EVIDENCE_ROW_CAP, build_visualizations

__all__ = ["ARTIFACT_PATH_SEPARATOR", "EVIDENCE_ROW_CAP", "build_visualizations"]
