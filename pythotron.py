import rtmidi
import time
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

# this is for my Korg nanokontrol2:
num_controls = 8
slider_start = 0
knob_start = 16
state_starts = {'s': 32, 'm': 48, 'r': 64}

title = 'Pythotron'
max_knob_size = 21
notes = [0, 2, 4, 5, 7, 9, 11, 12]
in_port = 0
out_port = 1

fg_color = Screen.COLOUR_RED
bg_color = Screen.COLOUR_BLACK
global_fg_color = Screen.COLOUR_YELLOW
global_attr = Screen.A_BOLD
global_bg_color = Screen.COLOUR_BLUE
solo_color = Screen.COLOUR_GREEN
record_color = Screen.COLOUR_MAGENTA

midi_in = rtmidi.MidiIn()
midi_out = rtmidi.MidiOut()
print(midi_in.get_ports())
print(midi_out.get_ports())
midi_in.open_port(in_port)
midi_out.open_port(out_port)

assert len(notes) >= num_controls


sinewaves = []
def init():
    global global_silent, volumes, controls, new_controls, states, sinewaves
    global_silent = False
    volumes = {k: min_db for k in range(num_controls)}
    controls = {}
    new_controls = {slider_start + k: 0 for k in range(num_controls)} | {knob_start + k: 64 for k in range(num_controls)}
    states = {state: {k: 0 for k in range(num_controls)} for state in state_starts}
    for k in range(len(sinewaves))[::-1]:
        sinewaves[k].stop()
        del sinewaves[k]
    for k in range(num_controls):
        sinewaves.append(SineWave(pitch=notes[k], pitch_per_second=pitch_per_second, decibels=min_db, decibels_per_second=decibels_per_second))
        sinewaves[k].play()
init()


def loop(screen):
    global global_silent, new_controls
    slider_size = screen.height // 2
    knob_size = min(screen.height // 2, max_knob_size)
    if knob_size % 2 == 0:
        knob_size += 1
    screen.clear()
    screen.set_title(title)
    while True:
        if screen.has_resized():
            raise ResizeScreenError('Screen resized')
        touch = set()
        while msg := midi_in.get_message():
            msg = msg[0][1:]
            k = int(msg[0])
            v = int(msg[1])
            if 0 <= k - slider_start < num_controls or 0 <= k - knob_start < num_controls:
                new_controls[k] = v
            else:
                for state in states:
                    if 0 <= k - state_starts[state] < num_controls:
                        states[state][k - state_starts[state]] = v > 0
                        touch.add(k - state_starts[state])
                        break

        controls.update(new_controls)

        for k, v in new_controls.items():
            if 0 <= k - knob_start < num_controls:
                sinewaves[k - knob_start].set_pitch(notes[k - knob_start] + (v * 2 / 127 - 1) * pitch_max_delta)

        for k in range(num_controls):
            if k in touch:
                new_controls[slider_start + k] = controls[slider_start + k]
                new_controls[knob_start + k] = controls[knob_start + k]
            volume = min_db
            if (not any(states['s'].values()) or states['s'][k]) and not states['m'][k] and not global_silent:
                volume += controls[k] / 127 * (max_db - min_db)
            if volume != volumes[k]:
                sinewaves[k].set_volume(volume)
                volumes[k] = volume

        for k, v in new_controls.items():
            control_size = slider_size if 0 <= k - slider_start < num_controls else knob_size
            for j in range(control_size):
                text = '   '
                bg = bg_color
                val_j = int(min(v, 126) / 127 * control_size)
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
                    elif control_size / 2 - 1 < j < val_j:
                        if states['r'][knorm]:
                            bg = record_color
                        if j == control_size // 2:
                            text = ' + '
                        else:
                            text = '  +'
                    elif control_size / 2 > j > val_j:
                        if states['r'][knorm]:
                            bg = record_color
                        if j == control_size // 2:
                            text = ' - '
                        else:
                            text = '-  '
                screen.print_at(text,
                    int((knorm + 0.5) * screen.width / num_controls - 1 + 2 * (j - (control_size - 1) / 2 + (1 if j < (control_size - 1) / 2 else -1) * (abs(abs(j - ((control_size - 1) / 2)) - (control_size - 1) / 4 - 1) * 2 + 1) * (abs(j - ((control_size - 1) / 2)) >= (control_size - 1) / 4 + 1)) * (0 <= k - knob_start < num_controls)),
                    int(((control_size / 2 - j) if 0 <= k - slider_start < num_controls else (abs(j - ((control_size - 1) / 2)) - control_size / 4)) + ((0 <= k - slider_start < num_controls) + 0.5) * screen.height / 2 - (0 <= k - slider_start < num_controls and control_size / 2 >= screen.height / 4)),
                    colour=solo_color if states['s'][knorm] else fg_color,
                    attr=Screen.A_NORMAL if states['m'][knorm] else Screen.A_BOLD,
                    bg=bg)
        need_refresh = bool(new_controls)
        new_controls = {}
        ev = screen.get_event()
        if isinstance(ev, KeyboardEvent): # note: Hebrew keys assume SI 1452-2 / 1452-3 layout
            c = None
            try:
                c = chr(ev.key_code).lower()
            except Exception:
                pass
            if c in ['q', 'ץ']: # Quit
                return
            if c in ['i', 'ת']: # Initialize
                init()
            if c in ['a', 'ש']: # send un-solo All tracks
                pass # tbd
            if c in ['n', 'מ']: # send uN-mute all tracks
                pass # tbd
            if c in ['m', 'צ']: # send Mute all tracks
                pass # tbd
            if c in ['r', 'ר']: # send aRm-Record all tracks
                pass # tbd
            if c in ['d', 'ג']: # send Disarm-record all tracks
                pass # tbd
            if c in ['u', 'ו']: # send Un-solo + Un-mute + disarm-record all tracks
                pass # tbd; call on init
            if c in ['h', 'י']:  # keymap Help overlay
                pass # tbd
            if c in ['s', 'ד']: # Software-level Silent / un-Silent
                global_silent = not global_silent
                need_refresh = True
                if global_silent:
                    screen.print_at('S', 0, 0,
                        colour=global_fg_color,
                        attr=global_attr,
                        bg=global_bg_color)
                else:
                    screen.print_at(' ', 0, 0,
                        bg=bg_color)

        if need_refresh:
            screen.refresh()
        time.sleep(sleep)


while True:
    try:
        Screen.wrapper(loop)
        break
    except ResizeScreenError:
        new_controls.update(controls)
