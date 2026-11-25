"""Use the real bearing board and confirm power-loss landing on two Horizon clients."""
import asyncio
import socket

from smoke_bearing_motion import ANCHOR, ARM, BEARING, MOTOR, STATE, click, observe, run, watch
from smoke_core import CONFIG, server, until
from smoke_encasing import move
from smoke_placement import coords, state_on
from smoke_windmill import change_motion_setting

DRIVE = f'setblock {coords(MOTOR)} create:creative_motor[facing=up]'
STOP = f'setblock {coords(MOTOR)} minecraft:air'


def stopped(observer, setting):
    return (observer.tags.get(BEARING, {}).get('ScrollValue') == setting
            and observer.tags.get(BEARING, {}).get('Speed') == 0
            and (observer.latest or {}).get('Speed') == 0)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'bearing-settings') as (send, _):
        async with watch(args, room, port, 'Builder') as builder, \
                   watch(args, room, port, 'Witness') as witness:
            peers = (builder, witness)
            log = (args.client_workspace or room) / 'Builder' / 'first-client.log'
            await asyncio.sleep(2)
            send('fill -269 77 -112 -261 77 -103 stone', 'fill -269 78 -112 -261 84 -103 air',
                 f'setblock {coords(BEARING)} {STATE}', DRIVE,
                 f'setblock {coords(ANCHOR)} minecraft:slime_block', f'setblock {coords(ARM)} minecraft:andesite')
            await state_on(witness[0], ARM, 'minecraft:andesite')
            await move(builder[0], send, (-265.5, 78, -104.5))
            await observe(peers, lambda o: o.tags.get(BEARING, {}).get('Speed') == 32, 'bearing powered')
            await click(builder)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 32, 'first assembly runs')
            await change_motion_setting(builder[0], log, 0, 1)
            await observe(peers, lambda o: o.tags.get(BEARING, {}).get('ScrollValue') == 1, 'both clients receive return-only mode')
            await until(lambda: 80 < (witness[1].latest or {}).get('Angle', -1) < 230, 'arm away from home', 8)
            send(STOP)
            await observe(peers, lambda o: stopped(o, 1), 'return-only mode stops away from home without landing')
            for call, _ in peers:
                await state_on(call, ANCHOR, 'minecraft:air')
            await change_motion_setting(builder[0], log, 1, 2)
            send(DRIVE)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 32 and
                          o.tags.get(BEARING, {}).get('ScrollValue') == 2, 'never-place mode resumes motion')
            send(STOP)
            await observe(peers, lambda o: stopped(o, 2), 'never-place mode retains the payload')

    async with server(args, room, port, 'bearing-settings-restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log') as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log') as witness:
            peers = (builder, witness)
            log = (args.client_workspace or room) / 'Builder' / 'restart-client.log'
            await observe(peers, lambda o: stopped(o, 2), 'both clients recover the stopped assembly and board mode')
            await asyncio.sleep(2)
            await move(builder[0], send, (-265.5, 78, -104.5))
            await change_motion_setting(builder[0], log, 2, 0)
            send(DRIVE)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 32 and
                          o.tags.get(BEARING, {}).get('ScrollValue') == 0, 'place-on-stop mode powered')
            send(STOP)
            await observe(peers, lambda o: o.latest == {} and o.tags.get(BEARING, {}).get('Running') == 0,
                          'actual power loss lands and releases the saved scene')
            around = ((ARM[0], ARM[1], ARM[2]), (ANCHOR[0] - 1, ANCHOR[1], ANCHOR[2]),
                      (ANCHOR[0], ANCHOR[1], ANCHOR[2] - 1), (ANCHOR[0], ANCHOR[1], ANCHOR[2] + 1))
            paints = []
            for call, _ in peers:
                await state_on(call, ANCHOR, 'minecraft:slime_block')
                parts = [p for p in around if (await call(f'block {coords(p)}')).get('state') == 'minecraft:andesite']
                assert len(parts) == 1, parts
                paints.append(parts[0])
            assert paints[0] == paints[1], paints
    print('PASS: identical landed payload, no duplicate cargo, mode survives restart', flush=True)


if __name__ == '__main__':
    run(test, __doc__)
