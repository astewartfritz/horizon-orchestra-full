//! HNSW (Hierarchical Navigable Small World) approximate nearest neighbor index.
//!
//! Supports cosine similarity and L2 (Euclidean) distance metrics.
//! Designed for fast vector search in the Orchestra embedding pipeline.

use std::collections::{BinaryHeap, HashMap, HashSet};
use std::cmp::Ordering;
use std::fs::File;
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::Path;

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

use crate::{OrchestraError, OrchestraResult};

/// Distance metric for vector comparisons.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DistanceMetric {
    Cosine,
    L2,
}

/// Configuration for the HNSW index.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HNSWConfig {
    /// Number of dimensions per vector.
    pub dimensions: usize,
    /// Maximum number of connections per node per layer.
    pub m: usize,
    /// Maximum number of connections for the zero layer.
    pub m0: usize,
    /// Size of the dynamic candidate list during construction.
    pub ef_construction: usize,
    /// Size of the dynamic candidate list during search.
    pub ef_search: usize,
    /// Distance metric to use.
    pub metric: DistanceMetric,
}

impl Default for HNSWConfig {
    fn default() -> Self {
        HNSWConfig {
            dimensions: 1536,
            m: 16,
            m0: 32,
            ef_construction: 200,
            ef_search: 50,
            metric: DistanceMetric::Cosine,
        }
    }
}

/// A node in the HNSW graph.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct HNSWNode {
    id: String,
    vector: Vec<f32>,
    /// Connections per layer: layer_index -> Vec<node_index>
    connections: Vec<Vec<usize>>,
    level: usize,
}

/// Candidate entry for priority queue operations.
#[derive(Debug, Clone)]
struct Candidate {
    index: usize,
    distance: f32,
}

impl PartialEq for Candidate {
    fn eq(&self, other: &Self) -> bool {
        self.distance == other.distance
    }
}
impl Eq for Candidate {}

impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        // Min-heap: reverse ordering so smallest distance is popped first.
        other.distance.partial_cmp(&self.distance)
    }
}

impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> Ordering {
        self.partial_cmp(other).unwrap_or(Ordering::Equal)
    }
}

/// Search result: (id, similarity/distance score).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub id: String,
    pub score: f32,
}

/// HNSW vector index supporting insert, search, batch operations, and persistence.
#[derive(Debug, Serialize, Deserialize)]
pub struct HNSWIndex {
    config: HNSWConfig,
    nodes: Vec<HNSWNode>,
    /// Maps external ID to internal node index.
    id_to_index: HashMap<String, usize>,
    /// Entry point node index (top-level node).
    entry_point: Option<usize>,
    /// Maximum level in the graph.
    max_level: usize,
    /// Level generation multiplier: 1/ln(M).
    level_mult: f64,
}

impl HNSWIndex {
    /// Create a new empty HNSW index with the given configuration.
    pub fn new(config: HNSWConfig) -> Self {
        let level_mult = 1.0 / (config.m as f64).ln();
        HNSWIndex {
            config,
            nodes: Vec::new(),
            id_to_index: HashMap::new(),
            entry_point: None,
            max_level: 0,
            level_mult,
        }
    }

    /// Insert a vector with the given ID.
    pub fn insert(&mut self, id: &str, vector: &[f32]) -> OrchestraResult<()> {
        if vector.len() != self.config.dimensions {
            return Err(OrchestraError::EmbeddingIndex(format!(
                "expected {} dimensions, got {}",
                self.config.dimensions,
                vector.len()
            )));
        }

        if self.id_to_index.contains_key(id) {
            return Err(OrchestraError::EmbeddingIndex(format!(
                "duplicate id: {}",
                id
            )));
        }

        let level = self.random_level();
        let node_idx = self.nodes.len();

        let node = HNSWNode {
            id: id.to_string(),
            vector: vector.to_vec(),
            connections: vec![Vec::new(); level + 1],
            level,
        };

        self.nodes.push(node);
        self.id_to_index.insert(id.to_string(), node_idx);

        if self.entry_point.is_none() {
            self.entry_point = Some(node_idx);
            self.max_level = level;
            return Ok(());
        }

        let entry = self.entry_point.unwrap();

        // Traverse from top level down to the node's level, greedily finding nearest.
        let mut current = entry;
        for lc in (level + 1..=self.max_level).rev() {
            current = self.greedy_search(current, vector, lc);
        }

        // For each level of the new node, find and connect neighbors.
        for lc in 0..=std::cmp::min(level, self.max_level) {
            let neighbors = self.search_layer(current, vector, self.config.ef_construction, lc);
            let max_conn = if lc == 0 { self.config.m0 } else { self.config.m };
            let selected: Vec<usize> = neighbors.iter().take(max_conn).map(|c| c.index).collect();

            // Connect new node to neighbors.
            self.nodes[node_idx].connections[lc] = selected.clone();

            // Connect neighbors back to new node (bidirectional).
            for &neighbor_idx in &selected {
                if lc < self.nodes[neighbor_idx].connections.len() {
                    self.nodes[neighbor_idx].connections[lc].push(node_idx);

                    // Prune if too many connections.
                    if self.nodes[neighbor_idx].connections[lc].len() > max_conn {
                        let nv = self.nodes[neighbor_idx].vector.clone();
                        let mut conn_dists: Vec<(usize, f32)> = self.nodes[neighbor_idx]
                            .connections[lc]
                            .iter()
                            .map(|&ci| (ci, self.distance(&nv, &self.nodes[ci].vector)))
                            .collect();
                        conn_dists.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal));
                        self.nodes[neighbor_idx].connections[lc] =
                            conn_dists.iter().take(max_conn).map(|&(i, _)| i).collect();
                    }
                }
            }

            if !neighbors.is_empty() {
                current = neighbors[0].index;
            }
        }

        // Update entry point if new node has higher level.
        if level > self.max_level {
            self.entry_point = Some(node_idx);
            self.max_level = level;
        }

        Ok(())
    }

    /// Search for the top_k nearest neighbors to the query vector.
    pub fn search(&self, query: &[f32], top_k: usize) -> OrchestraResult<Vec<SearchResult>> {
        if query.len() != self.config.dimensions {
            return Err(OrchestraError::EmbeddingIndex(format!(
                "expected {} dimensions, got {}",
                self.config.dimensions,
                query.len()
            )));
        }

        if self.nodes.is_empty() {
            return Ok(Vec::new());
        }

        let entry = self.entry_point.unwrap();

        // Greedily descend from top to layer 1.
        let mut current = entry;
        for lc in (1..=self.max_level).rev() {
            current = self.greedy_search(current, query, lc);
        }

        // Search layer 0 with ef_search candidates.
        let candidates = self.search_layer(current, query, self.config.ef_search, 0);

        // Return top_k results.
        let results: Vec<SearchResult> = candidates
            .into_iter()
            .take(top_k)
            .map(|c| SearchResult {
                id: self.nodes[c.index].id.clone(),
                score: if self.config.metric == DistanceMetric::Cosine {
                    1.0 - c.distance // Convert distance to similarity.
                } else {
                    c.distance
                },
            })
            .collect();

        Ok(results)
    }

    /// Batch insert multiple vectors.
    pub fn batch_insert(&mut self, ids: &[String], vectors: &[Vec<f32>]) -> OrchestraResult<usize> {
        if ids.len() != vectors.len() {
            return Err(OrchestraError::EmbeddingIndex(
                "ids and vectors must have equal length".to_string(),
            ));
        }

        let mut inserted = 0;
        for (id, vec) in ids.iter().zip(vectors.iter()) {
            self.insert(id, vec)?;
            inserted += 1;
        }

        Ok(inserted)
    }

    /// Save the index to disk as a binary file.
    pub fn save(&self, path: &Path) -> OrchestraResult<()> {
        let file = File::create(path)?;
        let writer = BufWriter::new(file);
        serde_json::to_writer(writer, self).map_err(|e| {
            OrchestraError::EmbeddingIndex(format!("serialize index: {}", e))
        })?;
        Ok(())
    }

    /// Load an index from disk.
    pub fn load(path: &Path) -> OrchestraResult<Self> {
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        let index: HNSWIndex = serde_json::from_reader(reader).map_err(|e| {
            OrchestraError::EmbeddingIndex(format!("deserialize index: {}", e))
        })?;
        Ok(index)
    }

    /// Return the number of vectors in the index.
    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    /// Check if the index is empty.
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    // --- Internal helpers ---

    /// Greedy search: find the nearest node to query at the given layer.
    fn greedy_search(&self, entry: usize, query: &[f32], layer: usize) -> usize {
        let mut current = entry;
        let mut current_dist = self.distance(query, &self.nodes[current].vector);

        loop {
            let mut changed = false;
            if layer < self.nodes[current].connections.len() {
                for &neighbor in &self.nodes[current].connections[layer] {
                    let d = self.distance(query, &self.nodes[neighbor].vector);
                    if d < current_dist {
                        current = neighbor;
                        current_dist = d;
                        changed = true;
                    }
                }
            }
            if !changed {
                break;
            }
        }

        current
    }

    /// Search a single layer, returning ef candidates sorted by distance.
    fn search_layer(&self, entry: usize, query: &[f32], ef: usize, layer: usize) -> Vec<Candidate> {
        let mut visited = HashSet::new();
        let mut candidates = BinaryHeap::new();
        let mut results = BinaryHeap::new();

        let d = self.distance(query, &self.nodes[entry].vector);
        candidates.push(Candidate { index: entry, distance: d });
        visited.insert(entry);

        while let Some(current) = candidates.pop() {
            // Check if we've found enough and current is worse than worst result.
            if results.len() >= ef {
                break;
            }

            results.push(Candidate {
                index: current.index,
                distance: current.distance,
            });

            if layer < self.nodes[current.index].connections.len() {
                for &neighbor in &self.nodes[current.index].connections[layer] {
                    if visited.insert(neighbor) {
                        let nd = self.distance(query, &self.nodes[neighbor].vector);
                        candidates.push(Candidate { index: neighbor, distance: nd });
                    }
                }
            }
        }

        // Collect and sort results by distance.
        let mut result_vec: Vec<Candidate> = results.into_iter().collect();
        result_vec.sort_by(|a, b| a.distance.partial_cmp(&b.distance).unwrap_or(Ordering::Equal));
        result_vec
    }

    /// Compute distance between two vectors based on the configured metric.
    fn distance(&self, a: &[f32], b: &[f32]) -> f32 {
        match self.config.metric {
            DistanceMetric::Cosine => cosine_distance(a, b),
            DistanceMetric::L2 => l2_distance(a, b),
        }
    }

    /// Generate a random level for a new node using exponential distribution.
    fn random_level(&self) -> usize {
        let r: f64 = rand::random::<f64>();
        let level = (-r.ln() * self.level_mult) as usize;
        level
    }
}

/// Cosine distance = 1 - cosine_similarity.
fn cosine_distance(a: &[f32], b: &[f32]) -> f32 {
    let mut dot = 0.0f32;
    let mut norm_a = 0.0f32;
    let mut norm_b = 0.0f32;

    for i in 0..a.len() {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }

    let denom = norm_a.sqrt() * norm_b.sqrt();
    if denom == 0.0 {
        return 1.0;
    }

    1.0 - (dot / denom)
}

/// L2 (Euclidean) distance.
fn l2_distance(a: &[f32], b: &[f32]) -> f32 {
    let mut sum = 0.0f32;
    for i in 0..a.len() {
        let diff = a[i] - b[i];
        sum += diff * diff;
    }
    sum.sqrt()
}

// --- PyO3 Python bindings ---

#[pyclass(name = "HNSWIndex")]
pub struct PyHNSWIndex {
    inner: HNSWIndex,
}

#[pymethods]
impl PyHNSWIndex {
    /// Create a new HNSW index.
    #[new]
    #[pyo3(signature = (dimensions=1536, m=16, ef_construction=200, ef_search=50, metric="cosine"))]
    fn new(dimensions: usize, m: usize, ef_construction: usize, ef_search: usize, metric: &str) -> PyResult<Self> {
        let dist_metric = match metric {
            "cosine" => DistanceMetric::Cosine,
            "l2" | "euclidean" => DistanceMetric::L2,
            _ => return Err(pyo3::exceptions::PyValueError::new_err("metric must be 'cosine' or 'l2'")),
        };

        let config = HNSWConfig {
            dimensions,
            m,
            m0: m * 2,
            ef_construction,
            ef_search,
            metric: dist_metric,
        };

        Ok(PyHNSWIndex {
            inner: HNSWIndex::new(config),
        })
    }

    /// Insert a vector.
    fn insert(&mut self, id: &str, vector: Vec<f32>) -> PyResult<()> {
        Ok(self.inner.insert(id, &vector)?)
    }

    /// Search for top_k nearest neighbors.
    fn search(&self, query: Vec<f32>, top_k: usize) -> PyResult<Vec<(String, f32)>> {
        let results = self.inner.search(&query, top_k)?;
        Ok(results.into_iter().map(|r| (r.id, r.score)).collect())
    }

    /// Batch insert vectors.
    fn batch_insert(&mut self, ids: Vec<String>, vectors: Vec<Vec<f32>>) -> PyResult<usize> {
        Ok(self.inner.batch_insert(&ids, &vectors)?)
    }

    /// Save index to file.
    fn save(&self, path: &str) -> PyResult<()> {
        Ok(self.inner.save(Path::new(path))?)
    }

    /// Load index from file.
    #[staticmethod]
    fn load(path: &str) -> PyResult<Self> {
        let inner = HNSWIndex::load(Path::new(path))?;
        Ok(PyHNSWIndex { inner })
    }

    /// Number of vectors in the index.
    fn __len__(&self) -> usize {
        self.inner.len()
    }
}

/// Register embedding index types in the Python module.
pub fn register_python_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyHNSWIndex>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cosine_distance_identical() {
        let a = vec![1.0, 0.0, 0.0];
        let b = vec![1.0, 0.0, 0.0];
        assert!((cosine_distance(&a, &b)).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_distance_orthogonal() {
        let a = vec![1.0, 0.0];
        let b = vec![0.0, 1.0];
        assert!((cosine_distance(&a, &b) - 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_l2_distance() {
        let a = vec![0.0, 0.0];
        let b = vec![3.0, 4.0];
        assert!((l2_distance(&a, &b) - 5.0).abs() < 1e-6);
    }

    #[test]
    fn test_index_empty_search() {
        let config = HNSWConfig {
            dimensions: 3,
            ..Default::default()
        };
        let index = HNSWIndex::new(config);
        let results = index.search(&[1.0, 0.0, 0.0], 5).unwrap();
        assert!(results.is_empty());
    }
}
