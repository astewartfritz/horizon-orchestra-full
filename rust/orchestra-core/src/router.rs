use pyo3::prelude::*;

/// Represents the class/role of an agent in the router.
#[derive(Debug, Clone, PartialEq)]
pub enum AgentClass {
    Coder,
    Reasoner,
    Summarizer,
    Validator,
    Scratch,
    Searcher,
    Extractor,
    Planner,
}

impl AgentClass {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "coder" => AgentClass::Coder,
            "reasoner" => AgentClass::Reasoner,
            "summarizer" => AgentClass::Summarizer,
            "validator" => AgentClass::Validator,
            "scratch" => AgentClass::Scratch,
            "searcher" => AgentClass::Searcher,
            "extractor" => AgentClass::Extractor,
            "planner" => AgentClass::Planner,
            _ => AgentClass::Reasoner,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            AgentClass::Coder => "coder",
            AgentClass::Reasoner => "reasoner",
            AgentClass::Summarizer => "summarizer",
            AgentClass::Validator => "validator",
            AgentClass::Scratch => "scratch",
            AgentClass::Searcher => "searcher",
            AgentClass::Extractor => "extractor",
            AgentClass::Planner => "planner",
        }
    }

    pub fn default_model(&self) -> &'static str {
        match self {
            AgentClass::Coder => "qwen2.5-coder:7b",
            AgentClass::Reasoner => "deepseek-r1:8b",
            AgentClass::Summarizer => "qwen2.5:3b",
            AgentClass::Validator => "qwen2.5:7b",
            AgentClass::Scratch => "qwen2.5:1.5b",
            AgentClass::Searcher => "qwen2.5:3b",
            AgentClass::Extractor => "qwen2.5:3b",
            AgentClass::Planner => "qwen2.5:7b",
        }
    }
}

/// A single step in a routing plan.
#[derive(Debug, Clone)]
pub struct PlanStep {
    pub step: usize,
    pub agent: AgentClass,
    pub goal: String,
}

/// A complete routing plan produced by the planner.
#[derive(Debug, Clone)]
pub struct RouterPlan {
    pub steps: Vec<PlanStep>,
    pub intent: String,
}

/// Result from a dispatched agent call.
#[derive(Debug, Clone)]
pub struct AgentResult {
    pub step: usize,
    pub agent: String,
    pub status: String,
    pub output: String,
    pub error: Option<String>,
}

/// High-performance model selector that maps task types → models
/// without any LLM call. Uses a simple priority-based matcher.
pub struct ModelSelector {
    overrides: Vec<(String, String)>,
}

impl ModelSelector {
    pub fn new() -> Self {
        ModelSelector {
            overrides: Vec::new(),
        }
    }

    pub fn with_override(mut self, task_pattern: &str, model: &str) -> Self {
        self.overrides
            .push((task_pattern.to_lowercase(), model.to_string()));
        self
    }

    pub fn select(&self, agent: &AgentClass, task_hint: &str) -> String {
        let task_lower = task_hint.to_lowercase();
        for (pattern, model) in &self.overrides {
            if task_lower.contains(pattern) {
                return model.clone();
            }
        }
        agent.default_model().to_string()
    }
}

/// Fast intent classifier that uses keyword matching + optional regex.
/// No LLM call — runs in microseconds for high-throughput routing.
pub struct IntentClassifier {
    code_keywords: Vec<String>,
    reasoning_keywords: Vec<String>,
    summary_keywords: Vec<String>,
    search_keywords: Vec<String>,
}

impl IntentClassifier {
    pub fn new() -> Self {
        IntentClassifier {
            code_keywords: vec![
                "write code",
                "implement",
                "function",
                "class",
                "bug",
                "fix",
                "refactor",
                "compile",
                "syntax",
                "algorithm",
            ]
            .into_iter()
            .map(String::from)
            .collect(),
            reasoning_keywords: vec![
                "reason",
                "explain why",
                "analyze",
                "compare",
                "difference between",
                "logical",
                "deduce",
                "inference",
            ]
            .into_iter()
            .map(String::from)
            .collect(),
            summary_keywords: vec![
                "summarize",
                "summarise",
                "tl;dr",
                "condense",
                "brief",
                "overview",
            ]
            .into_iter()
            .map(String::from)
            .collect(),
            search_keywords: vec!["search", "find", "look up", "research", "fetch", "retrieve"]
                .into_iter()
                .map(String::from)
                .collect(),
        }
    }

    pub fn classify(&self, input: &str) -> &'static str {
        let lower = input.to_lowercase();
        if self.matches_any(&lower, &self.code_keywords) {
            return "code";
        }
        if self.matches_any(&lower, &self.reasoning_keywords) {
            return "reasoning";
        }
        if self.matches_any(&lower, &self.summary_keywords) {
            return "summary";
        }
        if self.matches_any(&lower, &self.search_keywords) {
            return "search";
        }
        "general"
    }

    fn matches_any(&self, text: &str, keywords: &[String]) -> bool {
        keywords.iter().any(|kw| text.contains(kw))
    }
}

/// Fast router that classifies intent and selects the optimal agent chain.
pub struct Router {
    classifier: IntentClassifier,
    selector: ModelSelector,
}

impl Router {
    pub fn new() -> Self {
        Router {
            classifier: IntentClassifier::new(),
            selector: ModelSelector::new(),
        }
    }

    pub fn classify_and_route(&self, input: &str) -> RouterPlan {
        let intent = self.classifier.classify(input);
        let steps = self.build_steps(intent);
        RouterPlan {
            steps,
            intent: intent.to_string(),
        }
    }

    fn build_steps(&self, intent: &str) -> Vec<PlanStep> {
        match intent {
            "code" => vec![
                PlanStep {
                    step: 1,
                    agent: AgentClass::Coder,
                    goal: "Implement the solution".into(),
                },
                PlanStep {
                    step: 2,
                    agent: AgentClass::Validator,
                    goal: "Validate correctness".into(),
                },
            ],
            "reasoning" => vec![
                PlanStep {
                    step: 1,
                    agent: AgentClass::Reasoner,
                    goal: "Decompose and analyze".into(),
                },
                PlanStep {
                    step: 2,
                    agent: AgentClass::Validator,
                    goal: "Verify logic".into(),
                },
            ],
            "summary" => vec![PlanStep {
                step: 1,
                agent: AgentClass::Summarizer,
                goal: "Condense the input".into(),
            }],
            "search" => vec![
                PlanStep {
                    step: 1,
                    agent: AgentClass::Searcher,
                    goal: "Find relevant information".into(),
                },
                PlanStep {
                    step: 2,
                    agent: AgentClass::Extractor,
                    goal: "Extract structured results".into(),
                },
            ],
            _ => vec![
                PlanStep {
                    step: 1,
                    agent: AgentClass::Reasoner,
                    goal: "Analyze the request".into(),
                },
                PlanStep {
                    step: 2,
                    agent: AgentClass::Summarizer,
                    goal: "Format the response".into(),
                },
            ],
        }
    }
}

// ── PyO3 bindings ──────────────────────────────────────────────

#[pyclass]
struct PyAgentClass {
    inner: AgentClass,
}

#[pymethods]
impl PyAgentClass {
    #[staticmethod]
    fn from_str(s: &str) -> Self {
        PyAgentClass {
            inner: AgentClass::from_str(s),
        }
    }

    fn __repr__(&self) -> String {
        self.inner.as_str().to_string()
    }
}

#[pyclass]
struct PyRouter {
    inner: Router,
}

#[pymethods]
impl PyRouter {
    #[new]
    fn new_py() -> Self {
        PyRouter {
            inner: Router::new(),
        }
    }

    fn classify(&self, input: &str) -> String {
        self.inner.classify_and_route(input).intent
    }

    fn route(&self, input: &str) -> PyResult<Vec<PyPlanStep>> {
        let plan = self.inner.classify_and_route(input);
        Ok(plan
            .steps
            .into_iter()
            .map(|s| PyPlanStep {
                step: s.step,
                agent: s.agent.as_str().to_string(),
                goal: s.goal,
            })
            .collect())
    }

    fn select_model(&self, agent: &str, task_hint: &str) -> String {
        let agent = AgentClass::from_str(agent);
        self.inner.selector.select(&agent, task_hint)
    }
}

#[pyclass]
#[derive(Clone)]
struct PyPlanStep {
    #[pyo3(get)]
    step: usize,
    #[pyo3(get)]
    agent: String,
    #[pyo3(get)]
    goal: String,
}

#[pyclass]
struct PyIntentClassifier {
    inner: IntentClassifier,
}

#[pymethods]
impl PyIntentClassifier {
    #[new]
    fn new_py() -> Self {
        PyIntentClassifier {
            inner: IntentClassifier::new(),
        }
    }

    fn classify(&self, input: &str) -> String {
        self.inner.classify(input).to_string()
    }
}

#[pyclass]
struct PyModelSelector {
    inner: ModelSelector,
}

#[pymethods]
impl PyModelSelector {
    #[new]
    fn new_py() -> Self {
        PyModelSelector {
            inner: ModelSelector::new(),
        }
    }

    fn with_override(&mut self, pattern: &str, model: &str) {
        let old = std::mem::replace(&mut self.inner, ModelSelector::new());
        self.inner = old.with_override(pattern, model);
    }

    fn select(&self, agent: &str, task_hint: &str) -> String {
        let agent = AgentClass::from_str(agent);
        self.inner.select(&agent, task_hint)
    }
}

pub fn register_python_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyRouter>()?;
    m.add_class::<PyPlanStep>()?;
    m.add_class::<PyIntentClassifier>()?;
    m.add_class::<PyModelSelector>()?;
    m.add_class::<PyAgentClass>()?;
    Ok(())
}
