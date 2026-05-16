use std::collections::{HashMap, VecDeque};

pub type GroupId = u32;
pub type ExprId = u32;

// ============================================================
// 1. OPERATORS
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum LogicalOp {
    Scan { table: String },
    Filter { predicate: ScalarExpr },
    Project { columns: Vec<String> },
    Join { kind: JoinKind, on: ScalarExpr },
    Aggregate { group_by: Vec<String>, aggrs: Vec<String> },
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum PhysicalOp {
    SeqScan { table: String },
    IndexScan { table: String, index: String },
    HashJoin { kind: JoinKind, on: ScalarExpr },
    MergeJoin { kind: JoinKind, on: ScalarExpr },
    NestedLoopJoin { kind: JoinKind, on: ScalarExpr },
    HashAgg { group_by: Vec<String>, aggrs: Vec<String> },
    Sort { keys: Vec<String> },
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Operator {
    Logical(LogicalOp),
    Physical(PhysicalOp),
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum JoinKind {
    Inner,
    Left,
    Right,
    Full,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum ScalarExpr {
    Column(String),
    Literal(i64),
    Eq(Box<ScalarExpr>, Box<ScalarExpr>),
    And(Box<ScalarExpr>, Box<ScalarExpr>),
}

// ============================================================
// 2. PHYSICAL PROPERTIES & REQUIREMENTS
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Hash, Default)]
pub enum SortDirection {
    #[default]
    Asc,
    Desc,
}

/// Physical requirements (sort order, distribution, etc.).
/// Winners are cached per unique RequiredProps key.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Default)]
pub struct RequiredProps {
    pub sort_order: Vec<(String, SortDirection)>,
}

impl RequiredProps {
    pub fn is_empty(&self) -> bool {
        self.sort_order.is_empty()
    }
}

// ============================================================
// 3. LOGICAL PROPERTIES (cached per group)
// ============================================================

/// Logical properties are independent of physical execution.
/// Computed once per group and shared by every equivalent expression.
#[derive(Debug, Clone, Default)]
pub struct LogicalProps {
    pub cardinality: f64,
    pub output_cols: Vec<String>,
    /// Interesting orders this group can deliver cheaply (e.g., from an index).
    pub interesting_orders: Vec<Vec<(String, SortDirection)>>,
}

// ============================================================
// 4. MEMO STRUCTURES
// ============================================================

#[derive(Debug, Clone)]
pub struct Group {
    pub id: GroupId,
    pub expressions: Vec<ExprId>,
    pub logical_exprs: Vec<ExprId>,
    pub physical_exprs: Vec<ExprId>,
    pub winners: HashMap<RequiredProps, Winner>,
    pub logical_props: Option<LogicalProps>,
    /// All transform rules have saturated for this group.
    pub explored: bool,
    /// All implementation rules have fired for this group.
    pub implemented: bool,
}

#[derive(Debug, Clone)]
pub struct GroupExpr {
    pub id: ExprId,
    pub group_id: GroupId,
    pub op: Operator,
    pub children: Vec<GroupId>,
    pub explored: bool,
    pub implemented: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Cost {
    pub total: f64,
}

#[derive(Debug, Clone)]
pub struct Winner {
    pub expr_id: ExprId,
    pub cost: Cost,
}

// ============================================================
// 5. CANONICALIZED FINGERPRINT
// ============================================================

/// Fingerprint for duplicate detection.
/// Commutative operators canonicalize child order so that
/// e.g. A ⋈ B and B ⋈ A hash to the same value.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ExprFingerprint {
    pub op: Operator,
    pub children: Vec<GroupId>,
}

impl ExprFingerprint {
    pub fn new(op: &Operator, children: &[GroupId]) -> Self {
        let mut children = children.to_vec();
        // Canonicalize: for commutative joins, sort children by GroupId.
        let is_commutative = matches!(
            op,
            Operator::Logical(LogicalOp::Join {
                kind: JoinKind::Inner,
                ..
            })
        );
        if is_commutative {
            children.sort_unstable();
        }
        Self {
            op: op.clone(),
            children,
        }
    }
}

// ============================================================
// 6. MEMO
// ============================================================

#[derive(Default)]
pub struct Memo {
    pub next_group_id: GroupId,
    pub next_expr_id: ExprId,
    pub groups: HashMap<GroupId, Group>,
    pub exprs: HashMap<ExprId, GroupExpr>,
    pub expr_fingerprint: HashMap<ExprFingerprint, ExprId>,
}

impl Memo {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn new_group(&mut self) -> GroupId {
        let id = self.next_group_id;
        self.next_group_id += 1;
        self.groups.insert(
            id,
            Group {
                id,
                expressions: vec![],
                logical_exprs: vec![],
                physical_exprs: vec![],
                winners: HashMap::new(),
                logical_props: None,
                explored: false,
                implemented: false,
            },
        );
        id
    }

    /// Insert an expression into the memo.
    /// Uses canonical fingerprinting to detect duplicates across groups.
    pub fn insert_expr(
        &mut self,
        target_group: GroupId,
        op: Operator,
        children: Vec<GroupId>,
    ) -> ExprId {
        let fp = ExprFingerprint::new(&op, &children);
        if let Some(existing_id) = self.expr_fingerprint.get(&fp).copied() {
            let existing_group = self.exprs[&existing_id].group_id;
            if existing_group != target_group {
                // Same logical expression already exists elsewhere → merge groups.
                self.merge_groups(existing_group, target_group);
            }
            return existing_id;
        }

        let expr_id = self.next_expr_id;
        self.next_expr_id += 1;

        let expr = GroupExpr {
            id: expr_id,
            group_id: target_group,
            op: op.clone(),
            children,
            explored: false,
            implemented: false,
        };

        self.exprs.insert(expr_id, expr);
        self.expr_fingerprint.insert(fp, expr_id);

        let group = self.groups.get_mut(&target_group).unwrap();
        group.expressions.push(expr_id);

        match op {
            Operator::Logical(_) => group.logical_exprs.push(expr_id),
            Operator::Physical(_) => group.physical_exprs.push(expr_id),
        }

        expr_id
    }

    pub fn merge_groups(&mut self, dst: GroupId, src: GroupId) {
        if dst == src {
            return;
        }

        let src_group = self.groups.remove(&src).unwrap();
        let dst_group = self.groups.get_mut(&dst).unwrap();

        // Move expressions from src → dst.
        for expr_id in src_group.expressions {
            let expr = self.exprs.get_mut(&expr_id).unwrap();
            expr.group_id = dst;
            dst_group.expressions.push(expr_id);
            match expr.op {
                Operator::Logical(_) => dst_group.logical_exprs.push(expr_id),
                Operator::Physical(_) => dst_group.physical_exprs.push(expr_id),
            }
        }

        // Merge winners (keep cheaper).
        for (props, winner) in src_group.winners {
            dst_group
                .winners
                .entry(props)
                .and_modify(|w| {
                    if winner.cost.total < w.cost.total {
                        *w = winner.clone();
                    }
                })
                .or_insert(winner);
        }

        // Merge logical props.
        if let Some(src_props) = src_group.logical_props {
            dst_group.logical_props = Some(match dst_group.logical_props.take() {
                Some(dst_props) => LogicalProps {
                    cardinality: src_props.cardinality.min(dst_props.cardinality),
                    output_cols: if dst_props.output_cols.is_empty() {
                        src_props.output_cols
                    } else {
                        dst_props.output_cols
                    },
                    interesting_orders: dst_props.interesting_orders,
                },
                None => src_props,
            });
        }

        // Rewrite all child references from src → dst.
        for expr in self.exprs.values_mut() {
            for child in &mut expr.children {
                if *child == src {
                    *child = dst;
                }
            }
        }

        // Rebuild fingerprints (in production, only touch affected exprs).
        let all_ids: Vec<ExprId> = self.exprs.keys().copied().collect();
        self.expr_fingerprint.clear();
        for expr_id in all_ids {
            let expr = &self.exprs[&expr_id];
            let fp = ExprFingerprint::new(&expr.op, &expr.children);
            self.expr_fingerprint.insert(fp, expr_id);
        }
    }

    /// Compute or retrieve cached logical properties for a group.
    pub fn get_logical_props(&mut self, group_id: GroupId, stats: &dyn StatsProvider) -> LogicalProps {
        if let Some(props) = self.groups[&group_id].logical_props.clone() {
            return props;
        }
        let expr_id = self.groups[&group_id]
            .logical_exprs
            .first()
            .copied()
            .or_else(|| self.groups[&group_id].physical_exprs.first().copied());
        let props = if let Some(eid) = expr_id {
            self.derive_logical_props(eid, stats)
        } else {
            LogicalProps::default()
        };
        self.groups.get_mut(&group_id).unwrap().logical_props = Some(props.clone());
        props
    }

    fn derive_logical_props(&self, expr_id: ExprId, stats: &dyn StatsProvider) -> LogicalProps {
        let expr = &self.exprs[&expr_id];
        let mut cardinality = stats.cardinality(expr.group_id);
        let mut output_cols = vec![];
        let mut interesting_orders = vec![];

        match &expr.op {
            Operator::Logical(LogicalOp::Scan { table }) => {
                output_cols.push(format!("{}.*", table));
            }
            Operator::Logical(LogicalOp::Project { columns }) => {
                output_cols = columns.clone();
            }
            Operator::Logical(LogicalOp::Join { .. }) => {
                cardinality = expr
                    .children
                    .iter()
                    .map(|c| stats.cardinality(*c))
                    .product();
            }
            Operator::Physical(PhysicalOp::IndexScan { table, index }) => {
                output_cols.push(format!("{}.*", table));
                interesting_orders.push(vec![(index.clone(), SortDirection::Asc)]);
            }
            Operator::Physical(PhysicalOp::Sort { keys }) => {
                interesting_orders.push(
                    keys.iter()
                        .map(|k| (k.clone(), SortDirection::Asc))
                        .collect(),
                );
            }
            _ => {}
        }

        LogicalProps {
            cardinality,
            output_cols,
            interesting_orders,
        }
    }
}

// ============================================================
// 7. RULES
// ============================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuleType {
    Transform,
    Implement,
}

pub trait Rule {
    fn rule_type(&self) -> RuleType;
    fn matches(&self, expr: &GroupExpr, memo: &Memo) -> bool;
    fn apply(&self, expr_id: ExprId, ctx: &mut RuleContext) -> Vec<ExprId>;
}

pub struct RuleContext<'a> {
    pub memo: &'a mut Memo,
}

// --- Transform Rules ---

pub struct JoinCommuteRule;

impl Rule for JoinCommuteRule {
    fn rule_type(&self) -> RuleType {
        RuleType::Transform
    }

    fn matches(&self, expr: &GroupExpr, _memo: &Memo) -> bool {
        matches!(
            expr.op,
            Operator::Logical(LogicalOp::Join {
                kind: JoinKind::Inner,
                ..
            })
        ) && expr.children.len() == 2
    }

    fn apply(&self, expr_id: ExprId, ctx: &mut RuleContext) -> Vec<ExprId> {
        let expr = ctx.memo.exprs.get(&expr_id).unwrap().clone();
        match expr.op {
            Operator::Logical(LogicalOp::Join { kind, on }) => {
                let new_children = vec![expr.children[1], expr.children[0]];
                // Canonical fingerprint automatically deduplicates with original.
                let new_expr = ctx.memo.insert_expr(
                    expr.group_id,
                    Operator::Logical(LogicalOp::Join { kind, on }),
                    new_children,
                );
                vec![new_expr]
            }
            _ => vec![],
        }
    }
}

// --- Implementation Rules ---

pub struct HashJoinImplementRule;

impl Rule for HashJoinImplementRule {
    fn rule_type(&self) -> RuleType {
        RuleType::Implement
    }

    fn matches(&self, expr: &GroupExpr, _memo: &Memo) -> bool {
        matches!(expr.op, Operator::Logical(LogicalOp::Join { .. }))
    }

    fn apply(&self, expr_id: ExprId, ctx: &mut RuleContext) -> Vec<ExprId> {
        let expr = ctx.memo.exprs.get(&expr_id).unwrap().clone();
        match expr.op {
            Operator::Logical(LogicalOp::Join { kind, on }) => {
                let phys = Operator::Physical(PhysicalOp::HashJoin { kind, on });
                let new_expr = ctx.memo.insert_expr(expr.group_id, phys, expr.children);
                vec![new_expr]
            }
            _ => vec![],
        }
    }
}

pub struct MergeJoinImplementRule;

impl Rule for MergeJoinImplementRule {
    fn rule_type(&self) -> RuleType {
        RuleType::Implement
    }

    fn matches(&self, expr: &GroupExpr, _memo: &Memo) -> bool {
        matches!(expr.op, Operator::Logical(LogicalOp::Join { .. }))
    }

    fn apply(&self, expr_id: ExprId, ctx: &mut RuleContext) -> Vec<ExprId> {
        let expr = ctx.memo.exprs.get(&expr_id).unwrap().clone();
        match expr.op {
            Operator::Logical(LogicalOp::Join { kind, on }) => {
                let phys = Operator::Physical(PhysicalOp::MergeJoin { kind, on });
                let new_expr = ctx.memo.insert_expr(expr.group_id, phys, expr.children);
                vec![new_expr]
            }
            _ => vec![],
        }
    }
}

// ============================================================
// 8. DERIVE REQUIRED CHILD PROPERTIES
// ============================================================

/// Given a parent physical expression and required physical properties,
/// return the required properties for each child.
///
/// This allows top-down enforcement: a MergeJoin requiring sorted input
/// will ask both children to deliver data sorted on the join keys.
pub fn derive_required_child_props(
    expr: &GroupExpr,
    parent_req: &RequiredProps,
) -> Vec<RequiredProps> {
    match &expr.op {
        // Sort fully satisfies sort requirements; child needs none.
        Operator::Physical(PhysicalOp::Sort { .. }) => {
            vec![RequiredProps::default()]
        }

        // MergeJoin: both children must be sorted on the join keys.
        Operator::Physical(PhysicalOp::MergeJoin { on, .. }) => {
            let keys = extract_join_keys(on);
            let child_req = RequiredProps {
                sort_order: keys.into_iter().map(|k| (k, SortDirection::Asc)).collect(),
            };
            vec![child_req.clone(), child_req]
        }

        // Hash/NL joins destroy ordering.
        Operator::Physical(PhysicalOp::HashJoin { .. })
        | Operator::Physical(PhysicalOp::NestedLoopJoin { .. }) => {
            let cleared = RequiredProps {
                sort_order: vec![],
            };
            vec![cleared.clone(); expr.children.len()]
        }

        // Leaves.
        Operator::Physical(PhysicalOp::SeqScan { .. })
        | Operator::Physical(PhysicalOp::IndexScan { .. }) => vec![],

        // Default: pass down unchanged.
        _ => std::iter::repeat_with(|| parent_req.clone())
            .take(expr.children.len())
            .collect(),
    }
}

fn extract_join_keys(on: &ScalarExpr) -> Vec<String> {
    let mut keys = vec![];
    collect_eq_keys(on, &mut keys);
    keys
}

fn collect_eq_keys(expr: &ScalarExpr, keys: &mut Vec<String>) {
    match expr {
        ScalarExpr::Eq(left, right) => {
            if let ScalarExpr::Column(c) = left.as_ref() {
                keys.push(c.clone());
            }
            if let ScalarExpr::Column(c) = right.as_ref() {
                keys.push(c.clone());
            }
        }
        ScalarExpr::And(left, right) => {
            collect_eq_keys(left, keys);
            collect_eq_keys(right, keys);
        }
        _ => {}
    }
}

// ============================================================
// 9. TASKS & SCHEDULER (phase-aware)
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Task {
    ExploreGroup(GroupId),
    ImplementGroup(GroupId),
    OptimizeGroup(GroupId, RequiredProps),
    ApplyRules(ExprId, RulePhase),
    CostExpr(ExprId, RequiredProps),
    EnforceGroup(GroupId, RequiredProps),
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum RulePhase {
    Exploration,
    Implementation,
}

#[derive(Default)]
pub struct TaskQueue {
    q: VecDeque<Task>,
}

impl TaskQueue {
    pub fn push(&mut self, task: Task) {
        self.q.push_back(task);
    }
    pub fn pop(&mut self) -> Option<Task> {
        self.q.pop_front()
    }
}

// ============================================================
// 10. STATS & COST
// ============================================================

pub trait StatsProvider {
    fn cardinality(&self, group_id: GroupId) -> f64;
}

pub trait CostModel {
    fn cost(
        &self,
        expr: &GroupExpr,
        memo: &Memo,
        stats: &dyn StatsProvider,
        req: &RequiredProps,
    ) -> Cost;
}

pub struct SimpleCostModel;

impl CostModel for SimpleCostModel {
    fn cost(
        &self,
        expr: &GroupExpr,
        _memo: &Memo,
        stats: &dyn StatsProvider,
        _req: &RequiredProps,
    ) -> Cost {
        let child_rows: f64 = expr.children.iter().map(|g| stats.cardinality(*g)).sum();

        let total = match &expr.op {
            Operator::Physical(PhysicalOp::SeqScan { .. }) => child_rows + 100.0,
            Operator::Physical(PhysicalOp::IndexScan { .. }) => child_rows * 0.2 + 50.0,
            Operator::Physical(PhysicalOp::HashJoin { .. }) => child_rows * 1.5,
            Operator::Physical(PhysicalOp::MergeJoin { .. }) => child_rows * 1.2,
            Operator::Physical(PhysicalOp::NestedLoopJoin { .. }) => child_rows * 10.0,
            Operator::Physical(PhysicalOp::HashAgg { .. }) => child_rows * 0.8,
            Operator::Physical(PhysicalOp::Sort { keys }) => {
                let n = child_rows.max(1.0);
                n * n.log2() * keys.len() as f64
            }
            Operator::Logical(_) => f64::INFINITY,
        };

        Cost { total }
    }
}

pub fn update_winner(
    memo: &mut Memo,
    group_id: GroupId,
    props: RequiredProps,
    expr_id: ExprId,
    cost: Cost,
) {
    let group = memo.groups.get_mut(&group_id).unwrap();
    group
        .winners
        .entry(props)
        .and_modify(|w| {
            if cost.total < w.cost.total {
                *w = Winner {
                    expr_id,
                    cost: cost.clone(),
                };
            }
        })
        .or_insert(Winner { expr_id, cost });
}

// ============================================================
// 11. OPTIMIZER (Cascades with phase split & enforcers)
// ============================================================

pub struct Optimizer {
    pub memo: Memo,
    pub rules: Vec<Box<dyn Rule>>,
}

impl Optimizer {
    pub fn optimize(
        &mut self,
        root_group: GroupId,
        required: RequiredProps,
        coster: &dyn CostModel,
        stats: &dyn StatsProvider,
    ) -> Winner {
        let mut tasks = TaskQueue::default();

        // Schedule phases in order: explore → implement → optimize.
        tasks.push(Task::ExploreGroup(root_group));
        tasks.push(Task::ImplementGroup(root_group));
        tasks.push(Task::OptimizeGroup(root_group, required.clone()));

        while let Some(task) = tasks.pop() {
            match task {
                // ------------------------------------------------
                // EXPLORATION PHASE: saturate logical rewrites
                // ------------------------------------------------
                Task::ExploreGroup(group_id) => {
                    let group = &self.memo.groups[&group_id];
                    if group.explored {
                        continue;
                    }
                    for expr_id in group.logical_exprs.clone() {
                        tasks.push(Task::ApplyRules(expr_id, RulePhase::Exploration));
                    }
                }

                Task::ApplyRules(expr_id, RulePhase::Exploration) => {
                    let expr = self.memo.exprs.get(&expr_id).unwrap().clone();
                    if !matches!(expr.op, Operator::Logical(_)) || expr.explored {
                        continue;
                    }

                    let mut ctx = RuleContext {
                        memo: &mut self.memo,
                    };

                    for rule in &self.rules {
                        if rule.rule_type() != RuleType::Transform {
                            continue;
                        }
                        if rule.matches(&expr, ctx.memo) {
                            let new_exprs = rule.apply(expr_id, &mut ctx);
                            for new_expr in new_exprs {
                                let gid = ctx.memo.exprs[&new_expr].group_id;
                                tasks.push(Task::ApplyRules(
                                    new_expr,
                                    RulePhase::Exploration,
                                ));
                                tasks.push(Task::ExploreGroup(gid));
                            }
                        }
                    }

                    if let Some(e) = ctx.memo.exprs.get_mut(&expr_id) {
                        e.explored = true;
                    }
                    let group = &ctx.memo.groups[&expr.group_id];
                    let all_explored = group
                        .logical_exprs
                        .iter()
                        .all(|eid| ctx.memo.exprs[eid].explored);
                    if all_explored {
                        ctx.memo.groups.get_mut(&expr.group_id).unwrap().explored = true;
                    }
                }

                // ------------------------------------------------
                // IMPLEMENTATION PHASE: logical → physical
                // ------------------------------------------------
                Task::ImplementGroup(group_id) => {
                    let group = &self.memo.groups[&group_id];
                    if group.implemented {
                        continue;
                    }
                    if !group.explored {
                        // Ensure exploration finishes first.
                        tasks.push(Task::ExploreGroup(group_id));
                        tasks.push(Task::ImplementGroup(group_id));
                        continue;
                    }
                    for expr_id in group.logical_exprs.clone() {
                        tasks.push(Task::ApplyRules(expr_id, RulePhase::Implementation));
                    }
                }

                Task::ApplyRules(expr_id, RulePhase::Implementation) => {
                    let expr = self.memo.exprs.get(&expr_id).unwrap().clone();
                    if !matches!(expr.op, Operator::Logical(_)) || expr.implemented {
                        continue;
                    }

                    let mut ctx = RuleContext {
                        memo: &mut self.memo,
                    };

                    for rule in &self.rules {
                        if rule.rule_type() != RuleType::Implement {
                            continue;
                        }
                        if rule.matches(&expr, ctx.memo) {
                            let new_exprs = rule.apply(expr_id, &mut ctx);
                            for new_expr in new_exprs {
                                let gid = ctx.memo.exprs[&new_expr].group_id;
                                tasks.push(Task::CostExpr(
                                    new_expr,
                                    RequiredProps::default(),
                                ));
                                tasks.push(Task::OptimizeGroup(
                                    gid,
                                    RequiredProps::default(),
                                ));
                            }
                        }
                    }

                    if let Some(e) = ctx.memo.exprs.get_mut(&expr_id) {
                        e.implemented = true;
                    }
                    let group = &ctx.memo.groups[&expr.group_id];
                    let all_impl = group
                        .logical_exprs
                        .iter()
                        .all(|eid| ctx.memo.exprs[eid].implemented);
                    if all_impl {
                        ctx.memo.groups.get_mut(&expr.group_id).unwrap().implemented = true;
                    }
                }

                // ------------------------------------------------
                // OPTIMIZATION PHASE: cost & winner selection
                // ------------------------------------------------
                Task::OptimizeGroup(group_id, props) => {
                    let group = &self.memo.groups[&group_id];
                    if !group.implemented {
                        tasks.push(Task::ImplementGroup(group_id));
                        tasks.push(Task::OptimizeGroup(group_id, props));
                        continue;
                    }
                    if group.winners.contains_key(&props) {
                        continue;
                    }

                    // Cost every physical expression under these properties.
                    let phys_exprs = self.memo.groups[&group_id].physical_exprs.clone();
                    for expr_id in phys_exprs {
                        tasks.push(Task::CostExpr(expr_id, props.clone()));
                    }

                    // If requirements exist and no winner yet, consider enforcers.
                    if !props.is_empty() {
                        tasks.push(Task::EnforceGroup(group_id, props.clone()));
                    }
                }

                Task::EnforceGroup(group_id, props) => {
                    if self.memo.groups[&group_id].winners.contains_key(&props) {
                        continue;
                    }
                    if !props.sort_order.is_empty() {
                        let sort_keys: Vec<String> =
                            props.sort_order.iter().map(|(k, _)| k.clone()).collect();
                        let sort_op = Operator::Physical(PhysicalOp::Sort { keys: sort_keys });
                        // Enforcer lives in the same group and references itself as input.
                        let sort_expr_id =
                            self.memo.insert_expr(group_id, sort_op, vec![group_id]);
                        tasks.push(Task::CostExpr(sort_expr_id, props.clone()));
                    }
                }

                Task::CostExpr(expr_id, props) => {
                    let expr = self.memo.exprs[&expr_id].clone();

                    // Derive what each child must deliver.
                    let child_reqs = derive_required_child_props(&expr, &props);

                    // Ensure children have winners for their required props.
                    let mut child_total_cost = 0.0;
                    let mut all_ready = true;
                    for (child_gid, child_req) in expr.children.iter().zip(child_reqs.iter()) {
                        if let Some(winner) =
                            self.memo.groups[child_gid].winners.get(child_req)
                        {
                            child_total_cost += winner.cost.total;
                        } else {
                            tasks.push(Task::OptimizeGroup(*child_gid, child_req.clone()));
                            all_ready = false;
                        }
                    }

                    if !all_ready {
                        // Re-queue after children are optimized.
                        tasks.push(Task::CostExpr(expr_id, props));
                        continue;
                    }

                    // Local cost of this operator.
                    let local_cost = coster.cost(&expr, &self.memo, stats, &props);

                    // Total = local + sum of best child plans.
                    let mut total_cost = local_cost;
                    total_cost.total += child_total_cost;

                    update_winner(&mut self.memo, expr.group_id, props, expr_id, total_cost);
                }
            }
        }

        self.memo.groups[&root_group].winners[&required].clone()
    }
}