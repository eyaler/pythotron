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
m  Mute on all tracks
n  mute off all tracks
r  Record on all tracks
e  record off all tracks
u  solo/mute/record off all tracks
g  Global mute on/off all tracks
'''.strip().splitlines()

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
    global global_mute, show_help, volumes, controls, new_controls, states, new_states, sinewaves
    global_mute = False
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
    global global_mute, show_help, new_controls, new_states
    slider_size = screen.height // 2
    knob_size = min(screen.height // 2, max_knob_size)
    if knob_size % 2 == 0:
        knob_size += 1
    screen.clear()
    screen.set_title(title)
    while True:
        if screen.has_resized():
            raise ResizeScreenError('Screen resized')
        while msg := midi_in.get_message():
            msg = msg[0][1:]
            k = int(msg[0])
            v = int(msg[1])
            if 0 <= k - slider_start < num_controls or 0 <= k - knob_start < num_controls:
                new_controls[k] = v
            else:
                for state_name in states:
                    if 0 <= k - state_starts[state_name] < num_controls:
                        new_states[state_name][k - state_starts[state_name]] = not states[state_name][k - state_starts[state_name]] if external_led_mode else v > 0
                        break

        for k, v in new_controls.items():
            if 0 <= k - knob_start < num_controls:
                sinewaves[k - knob_start].set_pitch(notes[k - knob_start] + (v * 2 / 127 - 1) * pitch_max_delta)
        controls.update(new_controls)

        for state_name in new_states:
            states[state_name].update(new_states[state_name])
            for k, v in new_states[state_name].items():
                new_controls[slider_start + k] = controls[slider_start + k]
                new_controls[knob_start + k] = controls[knob_start + k]
                if external_led_mode:
                    send_msg(state_name, k, v)
        new_states = {state_name: {} for state_name in states}

        for k in range(num_controls):
            volume = min_db
            if (not any(states['s'].values()) or states['s'][k]) and not states['m'][k] and not global_mute:
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

        if global_mute:
            screen.print_at('MUTE', screen.width - 4, 0, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        help_x = max(0, (screen.width - len(max(help_text, key=len))) // 2)
        help_y = max(0, (screen.height - len(help_text)) // 2)
        if show_help:
            for i, line in enumerate(help_text):
                screen.print_at(line, help_x, help_y + i, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        need_screen_refresh = bool(new_controls) or global_mute or show_help
        new_controls = {}
        ev = screen.get_event()
        if isinstance(ev, KeyboardEvent):  # note: Hebrew keys assume SI 1452-2 / 1452-3 layout
            c = None
            try:
                c = chr(ev.key_code).lower()
            except Exception:
                pass
            if c in ['q', 'ץ']:  # Quit
                return
            elif c in ['i', 'ת']:  # Initialize
                init()
            elif c in ['s', 'ד']:  # Solo on all tracks
                toggle_all('s', True)
            elif c in ['a', 'ש']:  # Solo off All tracks
                toggle_all('s', False)
            elif c in ['m', 'צ']:  # Mute on all tracks
                toggle_all('m', True)
            elif c in ['n', 'מ']:  # Mute off all tracks
                toggle_all('m', False)
            elif c in ['r', 'ר']:  # Record on all tracks
                toggle_all('r', True)
            elif c in ['e', 'ק']:  # Record off all tracks
                toggle_all('r', False)
            elif c in ['u', 'ו']:  # solo/mute/record off all tracks
                toggle_all('msr', False)
            elif c in ['g', 'ג']:  # Global mute on/off all tracks (software level)
                global_mute = not global_mute
                if not global_mute:
                    need_screen_refresh = True
                    screen.print_at('    ', screen.width - 4, 0, bg=bg_color)
            elif c in ['h', 'י']:  # Help show/hide
                show_help = not show_help
                if not show_help:
                    need_screen_refresh = True
                    for k in range(num_controls):
                        new_controls[slider_start + k] = controls[slider_start + k]
                        new_controls[knob_start + k] = controls[knob_start + k]
                    for i, line in enumerate(help_text):
                        screen.print_at(re.sub(r'\S', ' ', line), help_x, help_y + i, bg=bg_color)

        if need_screen_refresh:
            screen.refresh()
        time.sleep(sleep)


while True:
    try:
        Screen.wrapper(loop)
        break
    except ResizeScreenError:
        new_controls.update(controls)
