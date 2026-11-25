"""Two real Horizon clients verify the windmill threshold, generation and safe restoration."""
import asyncio
import json
import socket

from smoke_bearing_motion import ANCHOR, BEARING, MOTOR, BearingObserver, click, observe, run, watch
from smoke_core import CONFIG, server, until
from smoke_encasing import move
from smoke_placement import aim, coords, state_on

WINDMILL = 'create:windmill_bearing[facing=up]'
SHAFT = 'create:shaft[axis=y,waterlogged=false]'
GAUGE = (-266, 77, -108)
STRESSOMETER = 'create:stressometer[axis_along_first=false,facing=north]'
SAILS = ('create:sail_frame[facing=north]', 'create:red_sail[facing=south]',
         *('create:blue_sail[facing=north]',) * 6)


def sail_pos(i):
    return (ANCHOR[0] + i, ANCHOR[1], ANCHOR[2])


class WindmillObserver(BearingObserver):
    states = {BEARING: WINDMILL, MOTOR: SHAFT, GAUGE: STRESSOMETER}

    def geometry(self, tag):
        assert tag['ReturnHome'] == ('b', 1)
        assert tag['WindmillSails'] == 8
        expected = {}
        for i, state in enumerate(SAILS):
            name, _, prop = state.partition('[facing=')
            expected[(i, 0, 0)] = {'id': name} | ({'properties': {'facing': prop[:-1]}} if prop else {})
        assert {tuple(block['Pos'][1]): block['State'] for block in tag['Blocks']} == expected


def generates(observer, rpm=1):
    tag = observer.tags.get(BEARING, {})
    return (tag.get('Running') == 1 and tag.get('LastGenerated') == rpm
            and tag.get('ScrollValue') == int(rpm < 0)
            and observer.tags.get(MOTOR, {}).get('Speed') == rpm
            and observer.tags.get(GAUGE, {}).get('Capacity') == 512
            and (observer.latest or {}).get('Speed') == rpm and len(observer.angles) >= 4)


async def change_motion_setting(call, log, old, value):
    def board():
        marker = 'Create bearing board: '
        rows = [line.split(marker, 1)[1] for line in log.read_text(errors='replace').splitlines() if marker in line]
        return json.loads(rows[-1]) if rows else {}

    hit = await aim(call, (-265.5, 79.38, -107.03), BEARING)
    assert hit['face'] == 'south', hit
    await call('mouse right down')
    await call('wait 14')
    await until(lambda: board().get('pos') == list(BEARING) and board()['value'] == old,
                'motion settings board opens with saved value', 12)
    x, y = board()['origin']
    x += 5.5 + 10 * value
    await call(f'scroll-at {x} {y + 5} 0')
    await until(lambda: board().get('value') == value, 'motion settings board selects requested option', 8)
    await call(f'click-at {x} {y + 5} right')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))

    async with server(args, room, port, 'windmill') as (send, _):
        async with watch(args, room, port, 'Builder', observer=WindmillObserver) as builder, \
                   watch(args, room, port, 'Witness', observer=WindmillObserver) as witness:
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('fill -269 77 -112 -256 77 -103 stone', 'fill -269 78 -112 -256 84 -103 air',
                 f'setblock {coords(MOTOR)} {SHAFT}', f'setblock {coords(GAUGE)} {STRESSOMETER}',
                 f'setblock {coords(BEARING)} {WINDMILL}', 'gamemode survival Builder',
                 *(f'setblock {coords(sail_pos(i))} {state}' for i, state in enumerate(SAILS[:-1])))
            await state_on(builder[0], BEARING, WINDMILL)
            await state_on(witness[0], sail_pos(6), SAILS[6])
            await move(builder[0], send, (-265.5, 78, -104.5))
            await click(builder)
            assert all(o.latest is None for _, o in peers), 'seven sails assembled'
            for i, state in enumerate(SAILS[:-1]):
                await state_on(witness[0], sail_pos(i), state)
            send(f'setblock {coords(sail_pos(7))} {SAILS[7]}')
            await state_on(builder[0], sail_pos(7), SAILS[7])
            await click(builder)
            await observe(peers, generates, 'eight sails drive both clients at 1 RPM and 512 capacity')
            for call, _ in peers:
                for i in range(len(SAILS)):
                    await state_on(call, sail_pos(i), 'minecraft:air')
            print('PASS: seven sails rejected; eight sail blocks produce 1 RPM and 512 SU on both clients', flush=True)
            await change_motion_setting(builder[0], (args.client_workspace or room) / 'Builder' / 'first-client.log', 0, 1)
            await observe(peers, lambda o: generates(o, -1), 'live board reverses both clients to -1 RPM')

    async with server(args, room, port, 'windmill-restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log', WindmillObserver) as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log', WindmillObserver) as witness:
            peers = (builder, witness)
            await observe(peers, lambda o: generates(o, -1), 'negative generation and direction recover after restart')
            await asyncio.sleep(2)
            await move(builder[0], send, (-265.5, 78, -104.5))
            await click(builder)
            await observe(peers, lambda o: o.latest == {} and o.tags.get(BEARING, {}).get('Running') == 0
                          and o.tags.get(MOTOR, {}).get('Speed') == 0, 'home landing stops generation in both clients')
            for call, _ in peers:
                for i, state in enumerate(SAILS):
                    await state_on(call, sail_pos(i), state)
    print('PASS: restart retains windmill; disassembly restores all eight exact states at home', flush=True)


if __name__ == '__main__':
    run(test, __doc__)
