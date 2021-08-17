import rtmidi
import time
import re
from asciimatics.screen import Screen
from asciimatics.event import KeyboardEvent
from asciimatics.exceptions import ResizeScreenError
from pysinewave import SineWave


max_db = 5
min_db = -120
decibels_per_second = 200
pitch_max_delta = 1.05
pitch_per_second = 100
sleep = 0.001

# this is for KORG nanoKONTROL2:
num_controls = 8
slider_start = 0
knob_start = 16
state_starts = {'s': 32, 'm': 48, 'r': 64}
external_led_mode = True  # requires setting LED Mode to "External" in KORG KONTROL Editor

title = 'Pythotron'
max_knob_size = 21
notes = [0, 2, 4, 5, 7, 9, 11, 12]
in_port = 0
out_port = 1

fg_color = Screen.COLOUR_RED
bg_color = Screen.COLOUR_BLACK
solo_color = Screen.COLOUR_GREEN
record_color = Screen.COLOUR_MAGENTA
overlay_fg_color = Screen.COLOUR_YELLOW
overlay_attr = Screen.A_BOLD
overlay_bg_color = Screen.COLOUR_BLUE

help_text = '''
h  Help show/hide
q  Quit
i  Initialize
s  Solo on all tracks
a  solo off All tracks
d  solo exclusive mode toggle
m  Mute on all tracks
n  mute off all tracks
o  mute Override all tracks toggle
r  Record on all tracks
e  record off all tracks
t  record exclusive mode Toggle
u  solo/mute/record off all tracks
'''.strip().splitlines()

solo_exclusive_text = 'SOLO EXCL'
mute_override_text = 'MUTE OVER'
record_exclusive_text = 'REC. EXCL'
solo_exclusive_y = 0
mute_override_y = 1
record_exclusive_y = 2

midi_in = rtmidi.MidiIn()
midi_out = rtmidi.MidiOut()
print(midi_in.get_ports())
print(midi_out.get_ports())
midi_in.open_port(in_port)
midi_out.open_port(out_port)

assert len(notes) >= num_controls


def send_msg(state_name, k, v):
    midi_out.send_message([176, state_starts[state_name] + k, v * 127])


def toggle_all(state_names, v):
    global new_states
    if external_led_mode:
        for state_name in state_names:
            for k in range(num_controls):
                new_states[state_name][k] = v


sinewaves = []
def init():
    global mute_override, solo_exclusive, record_exclusive, show_help, volumes, controls, new_controls, states, new_states, sinewaves
    mute_override = False
    solo_exclusive = False
    record_exclusive = False
    show_help = False
    volumes = {k: min_db for k in range(num_controls)}
    controls = {}
    new_controls = {slider_start + k: 0 for k in range(num_controls)} | {knob_start + k: 64 for k in range(num_controls)}
    states = {state_name: {k: False for k in range(num_controls)} for state_name in state_starts}
    new_states = {state_name: {} for state_name in state_starts}
    toggle_all(''.join(list(state_starts)), False)
    for k in range(len(sinewaves))[::-1]:
        sinewaves[k].stop()
        del sinewaves[k]
    for k in range(num_controls):
        sinewaves.append(SineWave(pitch=notes[k], pitch_per_second=pitch_per_second, decibels=min_db, decibels_per_second=decibels_per_second))
        sinewaves[k].play()
init()


def loop(screen):
    global mute_override, solo_exclusive, record_exclusive, show_help, new_controls, new_states
    slider_size = screen.height // 2
    knob_size = min(screen.height // 2, max_knob_size)
    if knob_size % 2 == 0:
        knob_size += 1
    screen.clear()
    screen.set_title(title)
    while True:
        if screen.has_resized():
            raise ResizeScreenError('Screen resized')
        last_solo_on = None
        last_record_on = None
        while msg := midi_in.get_message():
            msg = msg[0][1:]
            k = int(msg[0])
            v = int(msg[1])
            if 0 <= k - slider_start < num_controls or 0 <= k - knob_start < num_controls:
                new_controls[k] = v
            else:
                for state_name in states:
                    knorm = k - state_starts[state_name]
                    if 0 <= knorm < num_controls:
                        new_states[state_name][knorm] = not states[state_name][knorm] if external_led_mode else v > 0
                        if new_states[state_name][knorm]:
                            if state_name == 's':
                                last_solo_on = knorm
                            elif state_name == 'r':
                                last_record_on = knorm
                        break

        for k, v in new_controls.items():
            if 0 <= k - knob_start < num_controls:
                sinewaves[k - knob_start].set_pitch(notes[k - knob_start] + (v * 2 / 127 - 1) * pitch_max_delta)
        controls.update(new_controls)

        if last_solo_on and solo_exclusive:
            toggle_all('s', False)
            new_states['s'][last_solo_on] = True

        if last_record_on and record_exclusive:
            toggle_all('r', False)
            new_states['r'][last_record_on] = True

        for state_name in new_states:
            for k, v in new_states[state_name].items():
                new_controls[slider_start + k] = controls[slider_start + k]
                new_controls[knob_start + k] = controls[knob_start + k]
                if external_led_mode:
                    send_msg(state_name, k, v)
            states[state_name].update(new_states[state_name])
        new_states = {state_name: {} for state_name in states}

        for k in range(num_controls):
            volume = min_db
            if (not any(states['s'].values()) or states['s'][k]) and not states['m'][k] and not mute_override:
                volume += controls[k] / 127 * (max_db - min_db)
            if volume != volumes[k]:
                sinewaves[k].set_volume(volume)
                volumes[k] = volume

        for k, v in new_controls.items():
            control_size = slider_size if 0 <= k - slider_start < num_controls else knob_size
            val_j = int(min(v, 126) / 127 * control_size)
            for j in range(control_size):
                text = '   '
                bg = bg_color
                knorm = k - slider_start
                if 0 <= knorm < num_controls:
                    if j == val_j:
                        text = '%3d' % v
                        if states['r'][knorm]:
                            bg = record_color
                    elif j < val_j:
                        text = '...'
                        if states['r'][knorm]:
                            bg = record_color
                else:
                    knorm = k - knob_start
                    if j == val_j:
                        if states['r'][knorm]:
                            bg = record_color
                        text = ('%2d' % (v - 64))
                        if v > 64:
                            text += '+'
                        elif len(text) < 3:
                            text += ' '
                    elif knob_size / 2 - 1 < j < val_j:
                        if states['r'][knorm]:
                            bg = record_color
                        if j == knob_size // 2:
                            text = ' + '
                        else:
                            text = '  +'
                    elif knob_size / 2 > j > val_j:
                        if states['r'][knorm]:
                            bg = record_color
                        if j == knob_size // 2:
                            text = ' - '
                        else:
                            text = '-  '
                screen.print_at(text,
                    int((knorm + 0.5) * screen.width / num_controls - 1 + 2 * (j - (knob_size - 1) / 2 + (1 if j < (knob_size - 1) / 2 else -1) * (abs(abs(j - ((knob_size - 1) / 2)) - (knob_size - 1) / 4 - 1) * 2 + 1) * (abs(j - ((knob_size - 1) / 2)) >= (knob_size - 1) / 4 + 1)) * (0 <= k - knob_start < num_controls)),
                    int(((slider_size / 2 - j) if 0 <= k - slider_start < num_controls else (abs(j - ((knob_size - 1) / 2)) - knob_size / 4)) + ((0 <= k - slider_start < num_controls) + 0.5) * screen.height / 2 - (0 <= k - slider_start < num_controls and slider_size / 2 >= screen.height / 4)),
                    colour=solo_color if states['s'][knorm] else fg_color,
                    attr=Screen.A_NORMAL if states['m'][knorm] else Screen.A_BOLD,
                    bg=bg)

        if solo_exclusive:
            screen.print_at(solo_exclusive_text, screen.width - len(solo_exclusive_text), solo_exclusive_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if mute_override:
            screen.print_at(mute_override_text, screen.width - len(mute_override_text), mute_override_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if record_exclusive:
            screen.print_at(record_exclusive_text, screen.width - len(record_exclusive_text), record_exclusive_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        help_x = max(0, (screen.width - len(max(help_text, key=len))) // 2)
        help_y = max(0, (screen.height - len(help_text)) // 2)
        if show_help:
            for i, line in enumerate(help_text):
                screen.print_at(line, help_x, help_y + i, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        need_screen_refresh = bool(new_controls) or mute_override or solo_exclusive or record_exclusive or show_help
        new_controls = {}
        ev = screen.get_event()
        if isinstance(ev, KeyboardEvent):  # note: Hebrew keys assume SI 1452-2 / 1452-3 layout
            c = None
            try:
                c = chr(ev.key_code).lower()
            except Exception:
                pass
            if c in ['h', 'י']:  # Help show/hide
                show_help = not show_help
                if not show_help:
                    need_screen_refresh = True
                    for k in range(num_controls):
                        new_controls[slider_start + k] = controls[slider_start + k]
                        new_controls[knob_start + k] = controls[knob_start + k]
                    for i, line in enumerate(help_text):
                        screen.print_at(re.sub(r'\S', ' ', line), help_x, help_y + i, bg=bg_color)
            elif c in ['q', 'ץ']:  # Quit
                return
            elif c in ['i', 'ת']:  # Initialize
                init()
            elif c in ['s', 'ד']:  # Solo on all tracks
                toggle_all('s', True)
            elif c in ['a', 'ש']:  # solo off All tracks
                toggle_all('s', False)
            elif c in ['d', 'ג'] and external_led_mode:  # solo exclusive mode toggle
                solo_exclusive = not solo_exclusive
                if not solo_exclusive:
                    need_screen_refresh = True
                    screen.print_at(' ' * len(solo_exclusive_text), screen.width - len(solo_exclusive_text),
                                    solo_exclusive_y, bg=bg_color)
            elif c in ['m', 'צ']:  # Mute on all tracks
                toggle_all('m', True)
            elif c in ['n', 'מ']:  # mute off all tracks
                toggle_all('m', False)
            elif c in ['o', 'ם']:  # mute Override all tracks toggle (software level)
                mute_override = not mute_override
                if not mute_override:
                    need_screen_refresh = True
                    screen.print_at(' ' * len(mute_override_text), screen.width - len(mute_override_text),
                                    mute_override_y, bg=bg_color)
            elif c in ['r', 'ר']:  # Record on all tracks
                toggle_all('r', True)
            elif c in ['e', 'ק']:  # record off all tracks
                toggle_all('r', False)
            elif c in ['t', 'א'] and external_led_mode:  # record exclusive mode toggle
                record_exclusive = not record_exclusive
                if not record_exclusive:
                    need_screen_refresh = True
                    screen.print_at(' ' * len(record_exclusive_text), screen.width - len(record_exclusive_text),
                                    record_exclusive_y, bg=bg_color)
            elif c in ['u', 'ו']:  # solo/mute/record off all tracks
                toggle_all('msr', False)

        if need_screen_refresh:
            screen.refresh()
        time.sleep(sleep)


while True:
    try:
        Screen.wrapper(loop)
        break
    except ResizeScreenError:
        new_controls.update(controls)
