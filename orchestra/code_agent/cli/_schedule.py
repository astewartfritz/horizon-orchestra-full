"""CLI commands — schedule."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def schedule():
    """Manage scheduled agent tasks."""


@schedule.command("add")
@click.argument("name")
@click.argument("task")
@click.option("--interval", default=3600, type=int, help="Interval in seconds")
@click.option("--cron", default="", help="Cron expression (5-field), overrides --interval")
@click.option("--profile", default="minimal", help="Agent profile to use")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--max-retries", default=3, type=int, help="Max retry attempts on failure")
@click.option("--timeout", default=300, type=float, help="Task timeout in seconds")
@click.option("--provider", default="ollama", help="LLM provider to use (ollama, openai, anthropic)")
def schedule_add(name, task, interval, cron, profile, tags, max_retries, timeout, provider):
    """Add a scheduled task. Supports cron expressions or interval."""
    from orchestra.code_agent.scheduler.base import ScheduledTask, RetryPolicy
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    st = ScheduledTask(
        name=name, task=task, cron=cron, interval_seconds=interval,
        profile=profile, tags=tag_list,
        retry_policy=RetryPolicy(max_retries=max_retries),
        timeout_seconds=timeout, provider=provider,
    )
    st.compute_next_run()
    engine.add_task(st)
    sched_str = f"cron '{cron}'" if cron else f"every {interval}s"
    safe_echo(f"Scheduled: {name} ({sched_str}, profile={profile}, provider={provider})")


@schedule.command("list")
def schedule_list():
    """List scheduled tasks with status and next run."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    tasks = engine.list_tasks()
    if not tasks:
        safe_echo("No scheduled tasks.")
        return
    import time
    safe_echo(f"{'Name':25} {'Status':12} {'Schedule':20} {'Next Run':22} {'Runs':6} {'Fails':6}")
    safe_echo("-" * 90)
    for t in tasks:
        status_str = f"[{t.status.value.upper()}]" if t.enabled else "[PAUSED]"
        sched_str = f"cron '{t.cron}'" if t.cron else f"every {t.interval_seconds}s"
        next_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(t.next_run)) if t.next_run else "?"
        safe_echo(f"{t.name:25} {status_str:12} {sched_str:20} {next_str:22} {t.run_count:<6} {t.failure_count:<6}")


@schedule.command("remove")
@click.argument("name")
def schedule_remove(name):
    """Remove a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    if engine.remove_task(name):
        safe_echo(f"Removed: {name}")
    else:
        safe_echo(f"Not found: {name}")


@schedule.command("pause")
@click.argument("name")
def schedule_pause(name):
    """Pause a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    if engine.pause_task(name):
        safe_echo(f"Paused: {name}")
    else:
        safe_echo(f"Not found: {name}")


@schedule.command("resume")
@click.argument("name")
def schedule_resume(name):
    """Resume a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    if engine.resume_task(name):
        safe_echo(f"Resumed: {name}")
    else:
        safe_echo(f"Not found: {name}")


@schedule.command("status")
@click.argument("name")
def schedule_status(name):
    """Show detailed status of a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    import time
    engine = SchedulerEngine()
    task = engine.get_task(name)
    if not task:
        safe_echo(f"Task not found: {name}")
        return
    safe_echo(f"Name:      {task.name}")
    safe_echo(f"Task:      {task.task}")
    safe_echo(f"Status:    {task.status.value}")
    safe_echo(f"Enabled:   {task.enabled}")
    safe_echo(f"Provider:  {task.provider}")
    if task.cron:
        safe_echo(f"Schedule:  cron '{task.cron}'")
    else:
        safe_echo(f"Interval:  every {task.interval_seconds}s")
    safe_echo(f"Profile:   {task.profile}")
    safe_echo(f"Next Run:  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task.next_run)) if task.next_run else '?'}")
    safe_echo(f"Last Run:  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task.last_run)) if task.last_run else 'never'}")
    safe_echo(f"Runs:      {task.run_count} (ok={task.success_count}, fail={task.failure_count})")
    safe_echo(f"Timeout:   {task.timeout_seconds}s")
    if task.retry_policy:
        rp = task.retry_policy
        safe_echo(f"Retries:   {rp.max_retries} (backoff {rp.base_delay_seconds}s * {rp.backoff_multiplier}^n, max {rp.max_delay_seconds}s)")
    if task.last_error:
        safe_echo(f"Last err:  {task.last_error[:200]}")
    if task.tags:
        safe_echo(f"Tags:      {', '.join(task.tags)}")


@schedule.command("history")
@click.argument("name", required=False, default="")
@click.option("--limit", default=20, type=int, help="Number of entries")
def schedule_history(name, limit):
    """Show execution history for tasks."""
    from orchestra.code_agent.scheduler.store import SchedulerStore
    import time
    store = SchedulerStore()
    entries = store.load_history(task_name=name if name else None, limit=limit)
    if not entries:
        safe_echo("No history entries.")
        return
    safe_echo(f"{'Task':25} {'Status':12} {'Duration':10} {'Attempt':8} {'Error':30}")
    safe_echo("-" * 85)
    for e in entries:
        dur = f"{e['duration_ms']:.0f}ms"
        err = (e.get("error", "") or "")[:30]
        safe_echo(f"{e['task_name']:25} {e['status']:12} {dur:10} {e.get('attempt', 1):<8} {err:30}")


@schedule.command("run")
@click.argument("name")
def schedule_run(name):
    """Execute a scheduled task immediately."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    import asyncio
    engine = SchedulerEngine()
    if engine.run_now(name):
        safe_echo(f"Triggered: {name}")
    else:
        safe_echo(f"Task not found: {name}")


@schedule.command("dep")
@click.argument("task_name")
@click.argument("depends_on")
def schedule_dep(task_name, depends_on):
    """Add a dependency: task_name depends on depends_on."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    engine.add_dependency(task_name, depends_on)
    safe_echo(f"Dependency added: {task_name} depends on {depends_on}")


@schedule.command("stats")
@click.argument("name")
def schedule_stats(name):
    """Show execution statistics for a task."""
    from orchestra.code_agent.scheduler.store import SchedulerStore
    store = SchedulerStore()
    stats = store.task_stats(name)
    safe_echo(f"Task:      {name}")
    safe_echo(f"Total:     {stats['total']}")
    safe_echo(f"Completed: {stats['completed']}")
    safe_echo(f"Failed:    {stats['failed']}")
    safe_echo(f"Avg time:  {stats['avg_dur']:.0f}ms" if stats.get("avg_dur") else "Avg time:  N/A")


@schedule.command("health")
@click.option("--interval", default=60, type=int, help="Health check interval in seconds")
@click.option("--timeout", default=10.0, type=float, help="Health check probe timeout")
def schedule_health(interval, timeout):
    """Run scheduler with provider health checking. Tasks are skipped when their provider is unhealthy."""
    try:
        from orchestra.code_agent.serving.health import ModelHealthChecker
        from orchestra.code_agent.scheduler.engine import SchedulerEngine
        import asyncio
    except ImportError:
        safe_echo("Health checker not available (serving module required)")
        return
    hc = ModelHealthChecker()
    hc.register("ollama", "ollama", interval=interval, timeout=timeout)
    engine = SchedulerEngine(health_checker=hc)
    hc.start()
    engine.start()
    safe_echo("Scheduler running with health checking (Ctrl+C to stop)")
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        asyncio.get_event_loop().run_until_complete(hc.stop())
        safe_echo("Scheduler stopped")


