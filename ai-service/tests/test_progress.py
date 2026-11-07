import asyncio

from app.services.progress import Progress


def collect(progress, sid, heartbeat=1.0):
    async def run():
        return [e async for e in progress.follow(sid, heartbeat)]
    return run()


def test_a_late_follower_gets_the_past_then_live_events_until_the_end():
    async def scenario():
        p = Progress()
        p.start(1)
        p.publish(1, "route", {"target": "orders"})
        follower = asyncio.create_task(collect(p, 1))
        await asyncio.sleep(0)            # follower subscribed
        p.publish(1, "step", {"step": 1})
        p.finish(1)
        return await follower

    events = asyncio.run(scenario())
    assert [(e, {k: v for k, v in d.items() if k != "at"}) for e, d in events] == [
        ("route", {"target": "orders"}), ("step", {"step": 1})]
    # Each event carries when it happened, so a late follower can show durations
    assert all("at" in d for _, d in events)


def test_following_a_run_that_is_not_here_ends_at_once():
    assert asyncio.run(collect(Progress(), 9)) == []


def test_a_quiet_run_yields_heartbeats():
    async def scenario():
        p = Progress()
        p.start(1)
        follower = asyncio.create_task(collect(p, 1, heartbeat=0.02))
        await asyncio.sleep(0.07)
        p.finish(1)
        return await follower

    events = asyncio.run(scenario())
    assert events and all(e is None for e in events)
