"""CLI commands — skill."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def skill():
    """Manage the skill library (retrieval, distillation, credit)."""


@skill.command("list")
def skill_list():
    """List all skills in the library."""
    from orchestra.code_agent.skills.base import SkillLibrary
    lib = SkillLibrary()
    skills = lib.list_all()
    if not skills:
        safe_echo("Skill library is empty.")
        return
    safe_echo(f"Skill library ({len(skills)} skills):")
    for s in skills:
        safe_echo(f"  [{s.id}] {s.body[:80]} (used {s.usage_count}x, reward={s.avg_reward:.2f})")


@skill.command("show")
@click.argument("skill_id", type=int)
def skill_show(skill_id):
    """Show a skill by ID."""
    from orchestra.code_agent.skills.base import SkillLibrary
    s = SkillLibrary().get(skill_id)
    if not s:
        safe_echo(f"Skill #{skill_id} not found.")
        return
    safe_echo(f"ID: {s.id}")
    safe_echo(f"Body: {s.body}")
    safe_echo(f"Tags: {', '.join(s.tags)}")
    safe_echo(f"Usage count: {s.usage_count}")
    safe_echo(f"Avg reward: {s.avg_reward:.2f}")
    safe_echo(f"Success rate: {s.success_rate:.0%}")


@skill.command("search")
@click.argument("query")
@click.option("--top-k", default=5, help="Number of results")
def skill_search(query, top_k):
    """Search skills by semantic similarity."""
    from orchestra.code_agent.skills.base import SkillLibrary
    from orchestra.code_agent.skills.manager import SkillManager, Embedder
    mgr = SkillManager(SkillLibrary(), Embedder())
    results = asyncio.run(mgr.retrieve(query, top_k=top_k))
    if not results:
        safe_echo("No matching skills found.")
        return
    safe_echo(f"Top {len(results)} skills for: {query}")
    for s in results:
        safe_echo(f"  [{s.id}] {s.body[:80]} (reward={s.avg_reward:.2f})")


@skill.command("remove")
@click.argument("skill_id", type=int)
def skill_remove(skill_id):
    """Remove a skill by ID."""
    from orchestra.code_agent.skills.base import SkillLibrary
    ok = SkillLibrary().remove(skill_id)
    if ok:
        safe_echo(f"Removed skill #{skill_id}.")
    else:
        safe_echo(f"Skill #{skill_id} not found.")


@skill.command("add")
@click.option("--body", required=True, help="Skill body/procedure")
@click.option("--tags", default="", help="Comma-separated tags")
def skill_add(body, tags):
    """Add a skill manually."""
    from orchestra.code_agent.skills.base import Skill, SkillLibrary
    from orchestra.code_agent.skills.manager import Embedder
    skill = Skill(body=body, tags=[t.strip() for t in tags.split(",") if t.strip()])
    embedder = Embedder()
    skill.embedding = embedder.embed(body)
    skill.id = SkillLibrary().add(skill)
    safe_echo(f"Added skill #{skill.id}")


@skill.command("credit")
def skill_credit():
    """Show credit assignment signals for the last session."""
    from orchestra.code_agent.skills.base import SkillLibrary
    from orchestra.code_agent.skills.manager import SkillManager, Embedder
    mgr = SkillManager(SkillLibrary(), Embedder())
    credit = mgr.compute_credit()
    safe_echo("Credit signals:")
    safe_echo(f"  Selection:    {credit.selection:.3f}")
    safe_echo(f"  Utilization:  {credit.utilization:.3f}")
    safe_echo(f"  Distillation: {credit.distillation:.3f}")


@skill.command("seed")
@click.option("--clear", is_flag=True, help="Clear existing skills first")
def skill_seed(clear):
    """Seed the library with 20+ predefined coding skills."""
    from orchestra.code_agent.skills.seed import seed_library
    count = seed_library(clear=clear)
    safe_echo(f"Seeded {count} skills to the library.")


@main.group()
def skillv2():
    """Skill1-style meta-policy with 4-mode lifecycle (query, rerank, act, distill)."""


@skillv2.command("episode")
@click.argument("instruction")
@click.option("--difficulty", default=0.5, help="Task difficulty 0-1")
@click.option("--seed", type=int, default=None, help="Random seed")
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="LLM model")
def skillv2_episode(instruction, difficulty, seed, provider, model):
    """Run one full Skill1 episode: query → rerank → rollout → distill."""
    from orchestra.code_agent.llm.base import LLM
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    llm = LLM(provider=provider, model=model, timeout=120)
    mgr = SkillManagerV2(llm=llm)
    result = asyncio.run(mgr.run_episode(instruction, difficulty=difficulty, seed=seed))
    safe_echo(f"Episode {result['episode_id']}")
    safe_echo(f"  Task: {result['task']}")
    safe_echo(f"  Query: {result.get('query', '')}")
    safe_echo(f"  Selected skill: #{result.get('selected_skill_id', 'none')}")
    safe_echo(f"  Steps: {result.get('steps', 0)}")
    safe_echo(f"  Final reward: {result.get('final_reward', 0.0):.2f}")
    safe_echo(f"  Success: {result.get('success', False)}")
    safe_echo(f"  New skill distilled: #{result.get('new_skill_id', 'none')}")
    credit = result.get("credit", {})
    safe_echo(f"  Credit — selection: {credit.get('selection', 0):.3f}, utilization: {credit.get('utilization', 0):.3f}, distillation: {credit.get('distillation', 0):.3f}")


@skillv2.command("train")
@click.argument("num_episodes", type=int, default=5)
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="LLM model")
def skillv2_train(num_episodes, provider, model):
    """Run multiple training episodes with credit-based RL updates."""
    from orchestra.code_agent.llm.base import LLM
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    llm = LLM(provider=provider, model=model, timeout=120)
    mgr = SkillManagerV2(llm=llm)
    safe_echo(f"Training for {num_episodes} episodes...")
    results = asyncio.run(mgr.train(num_episodes=num_episodes))
    successes = sum(1 for r in results if r.get("success"))
    rewards = [r.get("final_reward", 0.0) for r in results]
    safe_echo(f"Completed {len(results)} episodes. Successes: {successes}/{len(results)}")
    safe_echo(f"Avg reward: {sum(rewards)/len(rewards):.2f}")
    safe_echo(f"Skills in library: {mgr.library.count()}")
    stats = mgr.trainer.stats()
    safe_echo(f"RL params: {stats.get('params', {})}")


@skillv2.command("evaluate")
@click.argument("skill_id", type=int)
def skillv2_evaluate(skill_id):
    """Evaluate a skill against held-out tasks."""
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    from orchestra.code_agent.skills.v2.evaluation import SkillEvaluator, EvalStore
    from orchestra.code_agent.skills.v2.environment import WebShopEnv
    mgr = SkillManagerV2()
    ev = EvalStore()
    env = WebShopEnv()
    evaluator = SkillEvaluator(mgr.library, env, ev)
    tasks = [
        "Buy a monitor under $300",
        "Find a red dress size M",
        "Buy a premium electronics product",
        "Find a sports item under $100",
    ]
    safe_echo(f"Evaluating skill #{skill_id} on {len(tasks)} tasks...")
    results = asyncio.run(evaluator.evaluate_skill(skill_id, tasks))
    if not results:
        safe_echo("Skill not found or no results.")
        return
    rewards = [r.reward for r in results]
    successes = sum(1 for r in results if r.success)
    safe_echo(f"Avg reward: {sum(rewards)/len(rewards):.2f}  Success: {successes}/{len(results)}")
    for r in results:
        safe_echo(f"  {r.task_instruction[:50]:50s} reward={r.reward:+.2f} success={r.success} steps={r.steps}")


@skillv2.command("benchmark")
def skillv2_benchmark():
    """Benchmark all skills against held-out tasks (comparison)."""
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    from orchestra.code_agent.skills.v2.evaluation import EvalStore
    ev = EvalStore()
    comp = ev.comparison()
    if not comp:
        safe_echo("No evaluation data. Run 'skillv2 evaluate' first.")
        return
    safe_echo("Skill comparison:")
    for s in comp:
        safe_echo(f"  [{s['skill_id']}] rate={s['success_rate']*100:.0f}% reward={s['avg_reward']:.2f} n={s['count']}  {s['skill_body']}")


@skillv2.command("credit")
def skillv2_credit():
    """Show persistent credit signal history."""
    from orchestra.code_agent.skills.v2 import CreditStore
    cs = CreditStore()
    hist = cs.history(limit=20)
    if not hist:
        safe_echo("No credit history yet.")
        return
    safe_echo("Credit history (last 20):")
    safe_echo("  step  outcome  sel     util    dist")
    for r in hist[-10:]:
        safe_echo(f"  {r.step:4d}  {r.outcome:+.2f}   {r.selection:.3f}  {r.utilization:.3f}  {r.distillation:.3f}")
    safe_echo(f"Latest: sel={hist[-1].selection:.3f} util={hist[-1].utilization:.3f} dist={hist[-1].distillation:.3f}")


@skillv2.command("library")
def skillv2_library():
    """Show v2 skill library stats."""
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    mgr = SkillManagerV2()
    stats = mgr.stats()
    safe_echo("Skill Library v2 stats:")
    safe_echo(f"  Skills: {stats['library'].get('count', 0)}")
    safe_echo(f"  Avg reward: {stats['library'].get('avg_reward', 0):.3f}")
    safe_echo(f"  Avg success rate: {stats['library'].get('avg_success_rate', 0):.3f}")
    safe_echo(f"  Total usage: {stats['library'].get('total_usage', 0)}")

    lib_skills = mgr.library.list_all(limit=20)
    if lib_skills:
        safe_echo("\nTop skills by usage:")
        for s in lib_skills[:10]:
            safe_echo(f"  [{s.id}] usage={s.usage_count} reward={s.avg_reward:.2f} rate={s.success_rate:.2f}")
            safe_echo(f"       {s.body[:100]}")


# ═══════════════════════════════════════════════════════════════
# Interactive Chat
# ═══════════════════════════════════════════════════════════════

