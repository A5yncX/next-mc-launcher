"""Two real Horizon clients verify the clockwork hands, time modes and atomic recovery."""
import asyncio
import json
import os
import socket

from smoke_bearing_motion import ANCHOR, BEARING, MOTOR, BearingObserver, click, observe, run, watch
from smoke_core import CONFIG, server
from smoke_encasing import move
from smoke_placement import coords, state_on
from smoke_windmill import change_motion_setting

CLOCK = 'create:clockwork_bearing[facing=up]'
MINUTE = (ANCHOR[0], ANCHOR[1] + 1, ANCHOR[2])
ARM = (MINUTE[0] + 1, MINUTE[1], MINUTE[2])
HANDS = [
    (ANCHOR, {(0, 0, 0): 'minecraft:honey_block'}),
    (MINUTE, {(0, 0, 0): 'minecraft:slime_block', (1, 0, 0): 'minecraft:andesite'}),
]
PAYLOAD = {ANCHOR: 'minecraft:honey_block', MINUTE: 'minecraft:slime_block', ARM: 'minecraft:andesite'}


class ClockObserver(BearingObserver):
    states = {BEARING: CLOCK}

    def records(self, geo, pose):
        assert len(geo) == len(pose) in (0, 2), (geo, pose)
        self.latest = {}
        for hand, ((pos, blocks), geometry, state) in enumerate(zip(HANDS, geo, pose)):
            assert geometry['Controller'] == state['Controller'] == ('I', list(BEARING))
            assert geometry['ClockHand'] == state['ClockHand'] == ('b', hand)
            assert geometry['ReturnHome'] == ('b', 1)
            assert geometry['Anchor'] == ('I', list(pos)) and geometry['Axis'] == 1
            assert {tuple(b['Pos'][1]): b['State']['id'] for b in geometry['Blocks']} == blocks
            self.latest[hand] = {key: state[key][1] for key in ('Angle', 'PreviousAngle', 'Speed', 'Stalled')}


def at_angles(observer, mode, hour, minute):
    tag = observer.tags.get(BEARING, {})
    return (tag.get('Running') == 1 and tag.get('ScrollValue') == mode
            and observer.latest and all(
                abs((observer.latest[i]['Angle'] - target + 180) % 360 - 180) < .01
                and observer.latest[i]['Speed'] == 32
                for i, target in enumerate((hour, minute))))


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'clockwork') as (send, _):
        async with watch(args, room, port, 'Builder', observer=ClockObserver) as builder, \
                   watch(args, room, port, 'Witness', observer=ClockObserver) as witness:
            peers = (builder, witness)
            log = (args.client_workspace or room) / 'Builder' / 'first-client.log'
            await asyncio.sleep(2)
            send('fill -269 77 -112 -261 77 -103 stone', 'fill -269 78 -112 -261 84 -103 air',
                 f'setblock {coords(BEARING)} {CLOCK}', f'setblock {coords(MOTOR)} create:creative_motor[facing=up]',
                 *(f'setblock {coords(pos)} {block}' for pos, block in PAYLOAD.items()),
                 'gamerule minecraft:advance_time false', 'time set 7250', 'gamemode survival Builder')
            await state_on(builder[0], BEARING, CLOCK)
            await state_on(witness[0], ARM, PAYLOAD[ARM])
            await move(builder[0], send, (-265.5, 78, -104.5))
            await move(witness[0], send, (-267.5, 78, -104.5), player='Witness')
            await witness[0]('look-at -265.5 81 -107.5')
            await observe(peers, lambda o: o.tags.get(BEARING, {}).get('Speed') == 32, 'powered clockwork on both clients')
            await click(builder)
            await observe(peers, lambda o: at_angles(o, 0, -30, -90), 'hour and minute have distinct time targets')
            for call, _ in peers:
                for pos in PAYLOAD:
                    await state_on(call, pos, 'minecraft:air')
            if os.environ.get('CREATE_TRACE_CONTRAPTION_FRAMES'):
                await asyncio.sleep(.8)
            await change_motion_setting(builder[0], log, 0, 1)
            await observe(peers, lambda o: at_angles(o, 1, -90, -30), 'real board swaps the clockwork dials')
            await change_motion_setting(builder[0], log, 1, 2)
            await observe(peers, lambda o: at_angles(o, 2, -195, -90), '24-hour dial uses all 24 hours')
            send('time set 8000')
            await observe(peers, lambda o: at_angles(o, 2, -210, 0), 'both hands react to changed world time')
            send(f'setblock {coords(MINUTE)} minecraft:granite')
            await state_on(witness[0], MINUTE, 'minecraft:granite')
            await click(builder)
            await observe(peers, lambda o: o.latest and all(hand['Stalled'] for hand in o.latest.values()),
                          'obstruction at the minute pivot retains both hands')
            await state_on(witness[0], ANCHOR, 'minecraft:air')

    async with server(args, room, port, 'clockwork-restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log', ClockObserver) as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log', ClockObserver) as witness:
            peers = (builder, witness)
            await observe(peers, lambda o: o.latest and all(hand['Stalled'] for hand in o.latest.values())
                          and o.tags.get(BEARING, {}).get('ScrollValue') == 2, 'paired hands and mode recover after restart')
            await asyncio.sleep(2)
            await move(builder[0], send, (-265.5, 78, -104.5))
            send(f'setblock {coords(MINUTE)} minecraft:air')
            await state_on(witness[0], MINUTE, 'minecraft:air')
            await click(builder)
            await observe(peers, lambda o: o.latest == {} and o.tags.get(BEARING, {}).get('Running') == 0,
                          'unblocked home landing releases both records')
            for call, _ in peers:
                for pos, block in PAYLOAD.items():
                    await state_on(call, pos, block)
    if os.environ.get('CREATE_TRACE_CONTRAPTION_FRAMES'):
        marker = 'Create contraption frame: '
        for name in ('Builder', 'Witness'):
            path = (args.client_workspace or room) / name / 'first-client.log'
            frames = [json.loads(line.split(marker, 1)[1]) for line in path.read_text(errors='replace').splitlines() if marker in line]
            pairs = {(tuple(frame['origin']), frame['current_angle']) for frame in frames
                     if frame['controller'] == list(BEARING) and frame['rpm'] == 32}
            for anchor, target in [(ANCHOR, -30), (MINUTE, -90)]:
                assert any(origin == anchor and abs((angle - target + 180) % 360 - 180) < .01 for origin, angle in pairs), (name, anchor)
        print('PASS: both Horizon renderers drew separate clockwork poses', flush=True)
    print('PASS: both clockwork hands restore their exact original states in one operation', flush=True)


if __name__ == '__main__':
    run(test, __doc__)
