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
slider_cc = 0
knob_cc = 16
state_cc = {'s': 32, 'm': 48, 'r': 64}
transport_cc = {41: 'play', 42: 'stop', 43: 'rewind', 44: 'fastforward', 45: 'record', 46: 'cycle', 58: 'track_rewind', 59: 'track_fastforward', 60: 'set', 61: 'marker_rewind', 62: 'marker_fastforward'}
transport_led = ['play', 'stop', 'rewind', 'fastforward', 'record', 'cycle']
external_led_mode = True  # requires setting LED Mode to "External" in KORG KONTROL Editor

title = 'Pythotron'
max_knob_size = 21
notes = [0, 2, 4, 5, 7, 9, 11, 12]
show_notes = True
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
f  solo deFeats mute toggle
m  Mute on all tracks
n  mute off all tracks
o  mute Override all tracks toggle
r  Record-arm on all tracks
e  record-arm off all tracks
t  record-arm exclusive mode Toggle
u  solo/mute/record-arm off all tracks
'''.strip().splitlines()

solo_exclusive_text = 'SOLO EXCL'
solo_defeats_mute_text = 'SOLO>MUTE'
mute_override_text = 'MUTE OVER'
record_exclusive_text = 'REC. EXCL'
solo_exclusive_y = 0
solo_defeats_mute_y = 1
mute_override_y = 2
record_exclusive_y = 3

midi_in = rtmidi.MidiIn()
midi_out = rtmidi.MidiOut()
print(midi_in.get_ports())
print(midi_out.get_ports())
midi_in.open_port(in_port)
midi_out.open_port(out_port)

assert len(notes) >= num_controls
assert len({line[0] for line in help_text}) == len(help_text)

note_names = {0: 'C', 1: 'C#', 2: 'D', 3: 'D#', 4: 'E', 5: 'F', 6: 'F#', 7: 'G', 8: 'G#', 9: 'A', 10: 'A#', 11: 'B'}
note_names.update({k+12: v.lower() for k, v in note_names.items()})


def send_msg(cc, val):
    midi_out.send_message([176, cc, val * 127])


class Soundscape:
    def __init__(self):
        self.sinewaves = []
        self.reset()

    def reset(self):
        self.volumes = {k: min_db for k in range(num_controls)}
        for k in range(len(self.sinewaves))[::-1]:
            self.sinewaves[k].stop()
            del self.sinewaves[k]
        for k in range(num_controls):
            self.sinewaves.append(SineWave(pitch=notes[k], pitch_per_second=pitch_per_second, decibels=min_db, decibels_per_second=decibels_per_second))
            self.sinewaves[k].play()

    def update_pitch(self, new_controls, track):
        for k, v in new_controls.items():
            if 0 <= k - knob_cc < num_controls:
                self.sinewaves[k - knob_cc].set_pitch(notes[k - knob_cc] + track + (v * 2 / 127 - 1) * pitch_max_delta)

    def update_volume(self, is_effective_mute, controls):
        for k in range(num_controls):
            volume = min_db
            if not is_effective_mute(k):
                volume += controls[k] / 127 * (max_db - min_db)
            if volume != self.volumes[k]:
                self.sinewaves[k].set_volume(volume)
                self.volumes[k] = volume


class Controller:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mute_override = False
        self.solo_exclusive = False
        self.solo_defeats_mute = False
        self.record_exclusive = False
        self.show_help = False
        self.controls = {}
        self.new_controls = {slider_cc + k: 0 for k in range(num_controls)} | {knob_cc + k: 64 for k in
                                                                               range(num_controls)}
        self.new_states = {state_name: {k: False for k in range(num_controls)} for state_name in state_cc}
        self.states = dict(self.new_states)
        self.new_transport = {k: False for k in transport_cc}
        self.transport = dict(self.new_transport)
        self.track = 0

    def toggle_all(self, state_names, val):
        if external_led_mode:
            for state_name in state_names:
                for k in range(num_controls):
                    self.new_states[state_name][k] = val

    def update_single(self, cc, val):
        cc = int(cc)
        val = int(val)
        if 0 <= cc - slider_cc < num_controls or 0 <= cc - knob_cc < num_controls:
            self.new_controls[cc] = val
        elif cc in transport_cc:
            self.new_transport[cc] = not self.transport[cc] if external_led_mode else v > 0
        else:
            for state_name in self.states:
                k = cc - state_cc[state_name]
                if 0 <= k < num_controls:
                    self.new_states[state_name][k] = not self.states[state_name][k] if external_led_mode else val > 0
                    break

    def update_all(self):
        self.controls.update(self.new_controls)

        if self.solo_exclusive or self.record_exclusive:
            for k in range(num_controls):
                if self.solo_exclusive and any(self.new_states['s'].values()) and self.states['s'][k] and k not in self.new_states['s']:
                    self.new_states['s'][k] = False
                if self.record_exclusive and any(self.new_states['r'].values()) and self.states['r'][k] and k not in self.new_states['r']:
                    self.new_states['r'][k] = False

        for state_name in self.new_states:
            for k, v in self.new_states[state_name].items():
                self.new_controls[slider_cc + k] = self.controls[slider_cc + k]
                self.new_controls[knob_cc + k] = self.controls[knob_cc + k]
                if external_led_mode:
                    send_msg(state_cc[state_name] + k, v)
            self.states[state_name].update(self.new_states[state_name])
        self.new_states = {state_name: {} for state_name in self.states}

        refresh_knobs = False
        for cc, v in self.new_transport.items():
            if transport_cc[cc] == 'track_rewind' and v:
                self.track -= 1
                refresh_knobs = show_notes
            elif transport_cc[cc] == 'track_fastforward' and v:
                self.track += 1
                refresh_knobs = show_notes
            if external_led_mode and transport_cc[cc] in transport_led:
                send_msg(cc, v)
        if refresh_knobs:
            for k in range(num_controls):
                self.new_controls[knob_cc + k] = self.controls[knob_cc + k]
        self.transport.update(self.new_transport)
        self.new_transport = {}

    def is_effective_mute(self, k):
        return self.mute_override or not self.solo_defeats_mute and self.states['m'][k] or not self.states['s'][k] and any(self.states['s'].values())


def loop(screen, ctrl, sound):
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
            ctrl.update_single(*msg[0][1:])
        ctrl.update_all()
        sound.update_volume(ctrl.is_effective_mute, ctrl.controls)
        sound.update_pitch(ctrl.new_controls, ctrl.track)

        for cc, v in ctrl.new_controls.items():
            k = cc - slider_cc
            is_slider = 0 <= k < num_controls
            if is_slider:
                control_size = slider_size
            else:
                k = cc - knob_cc
                control_size = knob_size
                if show_notes:
                    for i, label in enumerate(note_names[(notes[k] + ctrl.track) % len(note_names)].ljust(2)):
                        screen.print_at(label,
                                        int((k + 0.5) * screen.width / num_controls),
                                        int(int((knob_size - 1) / 4 + 1) - knob_size / 4 - i + screen.height / 4),
                                        colour=solo_color if ctrl.states['s'][k] else fg_color,
                                        attr=Screen.A_NORMAL if ctrl.states['m'][k] else Screen.A_BOLD,
                                        bg=record_color if ctrl.states['r'][k] else bg_color)
            val_j = int(min(v, 126) / 127 * control_size)
            for j in range(control_size):
                text = '   '
                hidden = False
                if is_slider:
                    if j == val_j:
                        text = '%3d' % v
                    elif j < val_j:
                        text = '...'
                    else:
                        hidden = True
                else:
                    if j == val_j:
                        text = '%2d' % (v - 64)
                        if v > 64:
                            text += '+'
                        elif len(text) < 3:
                            text += ' '
                    elif knob_size / 2 - 1 < j < val_j:
                        if j == knob_size // 2:
                            text = ' + '
                        else:
                            text = '  +'
                    elif knob_size / 2 > j > val_j:
                        if j == knob_size // 2:
                            text = ' - '
                        else:
                            text = '-  '
                    else:
                        hidden = True

                screen.print_at(text,
                                int((k + 0.5) * screen.width / num_controls - 1 + 2 * (j - (knob_size - 1) / 2 + (1 if j < (knob_size - 1) / 2 else -1) * (abs(abs(j - (knob_size - 1) / 2) - (knob_size - 1) / 4 - 1) * 2 + 1) * (abs(j - ((knob_size - 1) / 2)) >= (knob_size - 1) / 4 + 1)) * (not is_slider)),
                                int(((slider_size / 2 - j) if is_slider else (abs(j - (knob_size - 1) / 2) - knob_size / 4)) + (is_slider + 0.5) * screen.height / 2 - (is_slider and slider_size / 2 >= screen.height / 4)),
                                colour=solo_color if ctrl.states['s'][k] else fg_color,
                                attr=Screen.A_NORMAL if ctrl.states['m'][k] else Screen.A_BOLD,
                                bg=record_color if ctrl.states['r'][k] and not hidden else bg_color)

        if ctrl.solo_exclusive:
            screen.print_at(solo_exclusive_text, screen.width - len(solo_exclusive_text), solo_exclusive_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if ctrl.solo_defeats_mute:
            screen.print_at(solo_defeats_mute_text, screen.width - len(solo_defeats_mute_text), solo_defeats_mute_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if ctrl.mute_override:
            screen.print_at(mute_override_text, screen.width - len(mute_override_text), mute_override_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if ctrl.record_exclusive:
            screen.print_at(record_exclusive_text, screen.width - len(record_exclusive_text), record_exclusive_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        help_x = max(0, (screen.width - len(max(help_text, key=len))) // 2)
        help_y = max(0, (screen.height - len(help_text)) // 2)
        if ctrl.show_help:
            for i, line in enumerate(help_text):
                screen.print_at(line, help_x, help_y + i, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        screen_refresh = bool(ctrl.new_controls) or ctrl.mute_override or ctrl.solo_exclusive or ctrl.solo_defeats_mute or ctrl.record_exclusive or ctrl.show_help
        ctrl.new_controls = {}
        ev = screen.get_event()
        if isinstance(ev, KeyboardEvent):  # note: Hebrew keys assume SI 1452-2 / 1452-3 layout
            c = None
            try:
                c = chr(ev.key_code).lower()
            except Exception:
                pass
            if c in ['h', 'י']:  # Help show/hide
                ctrl.show_help = not ctrl.show_help
                if not ctrl.show_help:
                    screen_refresh = True
                    for k in range(num_controls):
                        ctrl.new_controls[slider_cc + k] = ctrl.controls[slider_cc + k]
                        ctrl.new_controls[knob_cc + k] = ctrl.controls[knob_cc + k]
                    for i, line in enumerate(help_text):
                        screen.print_at(re.sub(r'\S', ' ', line), help_x, help_y + i, bg=bg_color)
            elif c in ['q', 'ץ']:  # Quit
                return
            elif c in ['i', 'ת']:  # Initialize
                ctrl.reset()
                sound.reset()
            elif c in ['s', 'ד']:  # Solo on all tracks
                ctrl.toggle_all('s', True)
            elif c in ['a', 'ש']:  # solo off All tracks
                ctrl.toggle_all('s', False)
            elif c in ['d', 'ג'] and external_led_mode:  # solo exclusive mode toggle
                ctrl.solo_exclusive = not ctrl.solo_exclusive
                if not ctrl.solo_exclusive:
                    screen_refresh = True
                    screen.print_at(' ' * len(solo_exclusive_text), screen.width - len(solo_exclusive_text),
                                    solo_exclusive_y, bg=bg_color)
            elif c in ['f', 'כ']:  # solo deFeats mute toggle
                ctrl.solo_defeats_mute = not ctrl.solo_defeats_mute
                if not ctrl.solo_defeats_mute:
                    screen_refresh = True
                    screen.print_at(' ' * len(solo_defeats_mute_text), screen.width - len(solo_defeats_mute_text),
                                    solo_defeats_mute_y, bg=bg_color)
            elif c in ['m', 'צ']:  # Mute on all tracks
                ctrl.toggle_all('m', True)
            elif c in ['n', 'מ']:  # mute off all tracks
                ctrl.toggle_all('m', False)
            elif c in ['o', 'ם']:  # mute Override all tracks toggle (software level)
                ctrl.mute_override = not ctrl.mute_override
                if not ctrl.mute_override:
                    screen_refresh = True
                    screen.print_at(' ' * len(mute_override_text), screen.width - len(mute_override_text),
                                    mute_override_y, bg=bg_color)
            elif c in ['r', 'ר']:  # Record-arm on all tracks
                ctrl.toggle_all('r', True)
            elif c in ['e', 'ק']:  # record-arm off all tracks
                ctrl.toggle_all('r', False)
            elif c in ['t', 'א'] and external_led_mode:  # record-arm exclusive mode toggle
                ctrl.record_exclusive = not ctrl.record_exclusive
                if not ctrl.record_exclusive:
                    screen_refresh = True
                    screen.print_at(' ' * len(record_exclusive_text), screen.width - len(record_exclusive_text),
                                    record_exclusive_y, bg=bg_color)
            elif c in ['u', 'ו']:  # solo/mute/record-arm off all tracks
                ctrl.toggle_all('msr', False)

        if screen_refresh:
            screen.refresh()
        time.sleep(sleep)


controller = Controller()
soundscape = Soundscape()
while True:
    try:
        Screen.wrapper(loop, arguments=[controller, soundscape])
        break
    except ResizeScreenError:
        controller.new_controls.update(controller.controls)
