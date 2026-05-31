// graph.js — vis-network graph for the SkeinMinder pipeline topology.
// Exports: initGraph(), setNodeState(nodeName, state)

const _NODE_LABELS = {
  supervisor: "supervisor",
  project_first_filter: "project\nfirst filter",
  stash_first_filter: "stash\nfirst filter",
  assess_filter_quality: "assess\nfilter quality",
  low_confidence_output: "low confidence\noutput",
  pattern_search: "pattern\nsearch",
  recommend: "recommend",
  format_output: "format\noutput",
};

const _COLORS = {
  pending: { background: "#d9cfc5", border: "#b5aa9e", highlight: { background: "#d9cfc5", border: "#b5aa9e" } },
  active:  { background: "#8b2252", border: "#6d1a42", highlight: { background: "#8b2252", border: "#6d1a42" } },
  complete:{ background: "#4a7a4a", border: "#3a6a3a", highlight: { background: "#4a7a4a", border: "#3a6a3a" } },
};

let _network = null;
let _nodeDataset = null;

function initGraph() {
  const container = document.getElementById("graph-container");
  if (!container) return;

  _nodeDataset = new vis.DataSet(
    Object.keys(_NODE_LABELS).map((name) => ({
      id: name,
      label: _NODE_LABELS[name],
      color: _COLORS.pending,
      font: { color: "#2c2c2c", size: 12 },
      shape: "box",
      margin: 8,
    }))
  );

  const edges = new vis.DataSet([
    { from: "supervisor",             to: "project_first_filter" },
    { from: "supervisor",             to: "stash_first_filter" },
    { from: "project_first_filter",   to: "assess_filter_quality" },
    { from: "stash_first_filter",     to: "assess_filter_quality" },
    { from: "assess_filter_quality",  to: "pattern_search" },
    { from: "assess_filter_quality",  to: "low_confidence_output" },
    { from: "low_confidence_output",  to: "pattern_search" },
    { from: "pattern_search",         to: "recommend" },
    { from: "recommend",              to: "format_output" },
  ]);

  _network = new vis.Network(
    container,
    { nodes: _nodeDataset, edges },
    {
      layout: { hierarchical: { direction: "LR", sortMethod: "directed", levelSeparation: 130 } },
      physics: false,
      nodes: { shape: "box", font: { size: 12 } },
      edges: { arrows: "to", color: { color: "#b5aa9e" }, smooth: { type: "cubicBezier" } },
      interaction: { dragNodes: false, zoomView: false },
    }
  );
}

function setNodeState(nodeName, state) {
  if (!_nodeDataset || !_COLORS[state]) return;
  _nodeDataset.update({ id: nodeName, color: _COLORS[state] });
}
