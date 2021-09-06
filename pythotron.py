from asciimatics.screen import Screen
from asciimatics.event import KeyboardEvent
from asciimatics.exceptions import ResizeScreenError
from functools import partial
import librosa
import numpy as np
import os
from pysinewave import SineWave  # note: using the customized https://github.com/eyaler/pysinewave
import re
import rtmidi
from synths import dsaw, chord, loop, paulstretch
import sys
import time


max_db = 5
min_db = -120
interp_hz_per_sec = 200
synth_max_shift_semitones = 1.05
interp_amp_per_sec = 100
samplerate = 44100
cutoff = 2000000000
chord_notes = [[0, 4, 7], [0, 3, 7], [0, 3, 7], [0, 4, 7], [0, 4, 7], [0, 3, 7], [0, 3, 6]]
chord_notes7 = [[0, 4, 7, 11], [0, 3, 7, 10], [0, 3, 7, 10], [0, 4, 7, 11], [0, 4, 7, 10], [0, 3, 7, 10], [0, 3, 6, 10]]
detune_semitones = 0.02
arpeggio_secs = 0.25
arpeggio_amp_step = 0.005
loop_slice_secs = 0.25
loop_max_scrub_secs = None
stretch_window_secs = 0.25
stretch_slice_secs = 0.5
stretch_max_scrub_secs = None
stretch_advance_factor = 0.1  # == 1 / stretch_factor
synths = [('sine', np.sin),
          ('chord', partial(chord, chord_notes=chord_notes)),
          ('arpeggio-up7', partial(chord, chord_notes=chord_notes7, arpeggio_secs=arpeggio_secs, arpeggio_amp_step=arpeggio_amp_step, samplerate=samplerate)),
          ('dsaw', dsaw(detune_semitones=detune_semitones)),
          ('dsaw-chord', partial(chord, waveform=dsaw(detune_semitones=detune_semitones))),
          ('smp:loop', partial(loop, slice_secs=loop_slice_secs, max_scrub_secs=loop_max_scrub_secs, extend_reversal=True, samplerate=samplerate)),
          ('smp:stretch+rev', partial(paulstretch, windowsize_secs=stretch_window_secs, slice_secs=stretch_slice_secs, max_scrub_secs=stretch_max_scrub_secs, advance_factor=stretch_advance_factor, extend_reversal=True, samplerate=samplerate)),
          ('smp:stretch', partial(paulstretch, windowsize_secs=stretch_window_secs, slice_secs=stretch_slice_secs, max_scrub_secs=stretch_max_scrub_secs, advance_factor=stretch_advance_factor, samplerate=samplerate)),
          ('smp:freeze', partial(paulstretch, windowsize_secs=stretch_window_secs, max_scrub_secs=stretch_max_scrub_secs, samplerate=samplerate)),
          ]
mono = True
stereo_to_mono_tolerance = 1e-3
sleep = 0.0001

# this is for KORG nanoKONTROL2:
num_controls = 8
knob_center = 64
slider_cc = 0
knob_cc = 16
state_cc = {'s': 32, 'm': 48, 'r': 64}
transport_cc = {'play': 41, 'stop': 42, 'rewind': 43, 'forward': 44, 'record': 45, 'cycle': 46, 'track_rewind': 58, 'track_forward': 59, 'set': 60, 'marker_rewind': 61, 'marker_forward': 62}
transport_led = ['play', 'stop', 'rewind', 'forward', 'record', 'cycle']
cc2trans = {v: k for k, v in transport_cc.items()}
external_led_mode = True  # requires setting LED Mode to "External" in KORG KONTROL Editor
in_port_device = 'nanoKONTROL2 1'
out_port_device = 'nanoKONTROL2 1'

title = 'Pythotron'
max_knob_size = 21
notes = [0, 2, 4, 5, 7, 9, 11, 12]
sample_folder = 'samples'

fg_color = Screen.COLOUR_RED
bg_color = Screen.COLOUR_BLACK
solo_color = Screen.COLOUR_GREEN
record_color = Screen.COLOUR_MAGENTA
overlay_fg_color = Screen.COLOUR_YELLOW
overlay_attr = Screen.A_BOLD
overlay_bg_color = Screen.COLOUR_BLUE

help_text = '''
h    Help show/hide
q    Quit
i    Initialize
k    reset Knobs 
l    reset sliders
s    Solo on all tracks
a    solo off All tracks
d    solo exclusive mode toggle
f    solo deFeats mute toggle
m    Mute on all tracks
n    mute off all tracks
o    mute Override all tracks toggle
r    Record-arm on all tracks
e    record-arm off all tracks
t    record-arm exclusive mode Toggle
u    solo/mute/record-arm off all tracks
1-0  choose synth
track rewind/forward     semitone scale shift
marker rewind/forward    change synths and samplers
rewind/forward           change sample file
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
in_ports = midi_in.get_ports()
out_ports = midi_out.get_ports()
print('In MIDI ports:', in_ports)
print('Out MIDI ports:', out_ports)
in_port = [i for i, name in enumerate(in_ports) if name.lower().startswith(in_port_device.lower())][0]
out_port = [i for i, name in enumerate(out_ports) if name.lower().startswith(in_port_device.lower())][0]
midi_in.open_port()
midi_out.open_port()

synth_names, synth_funcs = zip(*synths)
assert len(synth_names) == len(set(synth_names)), sorted(x for x in synth_names if synth_names.count(x) > 1)
assert len(synth_funcs) == len(set(synth_funcs)), sorted(x for x in synth_funcs if synth_funcs.count(x) > 1)
assert len(notes) >= num_controls, (notes, num_controls)
help_keys = [line[0].lower() for line in help_text if line[1] in (' ', '\t')]
assert len(help_keys) == len(set(help_keys)), sorted(x for x in help_keys if help_keys.count(x) > 1)

note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
note_names += [x.lower() for x in note_names]


def send_msg(cc, val):
    midi_out.send_message([176, cc, val * 127])


def hasattr_partial(f, attr):
    return hasattr(f, attr) or hasattr(f, 'func') and hasattr(f.func, attr)


class Soundscape:
    def __init__(self, ctrl):
        self.tracks = []
        self.ctrl = ctrl
        self.reset()

    @property
    def synth_disp(self):
        return f'{self.synth + 1}.' + synths[self.synth][0]

    @property
    def sample_disp(self):
        return self.sample_path.split(sample_folder + os.sep, 1)[-1]

    def instantiate_waveform(self, synth, track=None):
        waveform = synths[synth][1]
        if hasattr_partial(waveform, 'is_func_factory'):
            waveform = waveform(track=track, ctrl=self.ctrl, sample=self.sample)
        return waveform

    def load_sample(self, sample_num=None):
        if sample_num is not None:
            self.sample_num = sample_num
        files = librosa.util.find_files(sample_folder)
        self.sample_path = files[sample_num % (len(files))]
        try:
            self.sample, _ = librosa.load(self.sample_path, sr=samplerate, mono=mono)
        except Exception as e:
            print(e)
            print('Error loading sample', self.sample_path)
            sys.exit(1)
        if len(self.sample.shape) == 2 and np.allclose(self.sample[0], self.sample[1], atol=stereo_to_mono_tolerance):
            self.sample = librosa.to_mono(self.sample)
        self.synth = None

    def reset(self):
        self.load_sample(0)
        self.synth = 0
        self.volumes = {k: min_db for k in range(num_controls)}
        for k in range(len(self.tracks))[::-1]:
            self.tracks[k].stop()
            del self.tracks[k]
        for k in range(num_controls):
            self.tracks.append(SineWave(pitch=notes[k], pitch_per_second=interp_hz_per_sec, decibels=min_db,
                                        decibels_per_second=interp_amp_per_sec, channels=1 if mono else 2,
                                        samplerate=samplerate, waveform=self.instantiate_waveform(self.synth, track=k), cutoff=cutoff))
            self.tracks[k].play()

    def update(self):
        if self.sample_num != self.ctrl.sample_num:
            self.load_sample(self.ctrl.sample_num)
        synth = self.ctrl.marker % len(synths)
        for k in range(num_controls):
            if self.synth != synth:
                self.tracks[k].set_waveform(self.instantiate_waveform(synth, track=k))
            volume = min_db
            if not self.ctrl.is_effective_mute(k):
                volume += self.ctrl.controls[k] / 127 * (max_db - min_db)
            if volume != self.volumes[k]:
                self.tracks[k].set_volume(volume)
                self.volumes[k] = volume
        self.synth = synth

        if not hasattr_partial(synths[synth][1], 'skip_pitch_control'):
            for cc, v in self.ctrl.new_controls.items():
                k = cc - knob_cc
                if 0 <= k < num_controls:
                    self.tracks[k].set_pitch(notes[k] + self.ctrl.track + self.ctrl.norm_knob(v) * synth_max_shift_semitones)


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
        self.new_controls = {}
        self.controls_memory = {}
        self.reset_sliders()
        self.reset_knobs()
        self.new_states = {state_name: {k: False for k in range(num_controls)} for state_name in state_cc}
        self.states = dict(self.new_states)
        self.new_transport = {k: False for k in transport_cc}
        self.transport = dict(self.new_transport)
        self.track = 0
        self.marker = 0
        self.sample_num = 0

    def reset_sliders(self):
        for k in range(num_controls):
            self.controls[k + slider_cc] = 0
            self.new_controls[k + slider_cc] = 0
            self.controls_memory[k + slider_cc] = 0

    def reset_knobs(self):
        for k in range(num_controls):
            self.controls[k + knob_cc] = knob_center
            self.new_controls[k + knob_cc] = knob_center
            self.controls_memory[k + knob_cc] = knob_center

    def toggle_knobs_mode(self):
        for k in range(num_controls):
            self.new_controls[k + knob_cc] = self.controls_memory[k + knob_cc]
            self.controls_memory[k + knob_cc] = self.controls[k + knob_cc]
            self.controls[k + knob_cc] = self.new_controls[k + knob_cc]

    @staticmethod
    def norm_knob(v):
        return min(v / knob_center - 1, 1)

    def get_knob(self, k):
        if k + knob_cc in self.controls:
            return self.norm_knob(self.controls[k + knob_cc])
        return 0

    def get_slider(self, k):
        if k + slider_cc in self.controls:
            return self.controls[k + slider_cc] / 127
        return 0

    @staticmethod
    def relative_track(k):
        return k / max(num_controls - 1, 1)

    def toggle_all(self, state_names, val):
        if external_led_mode:
            for state_name in state_names:
                if state_name in state_cc:
                    for k in range(num_controls):
                        self.new_states[state_name][k] = val

    def update_single(self, cc, val):
        cc = int(cc)
        val = int(val)
        if 0 <= cc - slider_cc < num_controls or 0 <= cc - knob_cc < num_controls:
            self.new_controls[cc] = val
        elif cc in cc2trans:
            trans = cc2trans[cc]
            self.new_transport[trans] = not self.transport[trans] if external_led_mode else val > 0
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
                if self.solo_exclusive and 's' in state_cc and (self.new_states['s'].values()) and self.states['s'][k] and k not in self.new_states['s']:
                    self.new_states['s'][k] = False
                if self.record_exclusive and 'r' in state_cc and any(self.new_states['r'].values()) and self.states['r'][k] and k not in self.new_states['r']:
                    self.new_states['r'][k] = False

        for state_name in self.new_states:
            for k, v in self.new_states[state_name].items():
                self.new_controls[slider_cc + k] = self.controls[slider_cc + k]
                self.new_controls[knob_cc + k] = self.controls[knob_cc + k]
                if external_led_mode:
                    send_msg(state_cc[state_name] + k, v)
            self.states[state_name].update(self.new_states[state_name])
        self.new_states = {state_name: {} for state_name in self.states}

        if 'stop' in self.new_transport and not self.new_transport['stop']:
            if 'play' in self.transport and self.transport['play']:
                self.new_transport['play'] = False
            if 'record' in self.transport and self.transport['record']:
                self.new_transport['record'] = False

        refresh_knobs = False
        for trans, v in self.new_transport.items():
            if v:
                if trans == 'track_rewind':
                    self.track -= 1
                    refresh_knobs = True
                elif trans == 'track_forward':
                    self.track += 1
                    refresh_knobs = True
                elif trans == 'marker_rewind':
                    self.marker -= 1
                elif trans == 'marker_forward':
                    self.marker += 1
                elif trans == 'rewind':
                    self.sample_num -= 1
                elif trans == 'forward':
                    self.sample_num += 1
            if external_led_mode and trans in transport_led:
                send_msg(transport_cc[trans], v)
        if refresh_knobs:
            for k in range(num_controls):
                self.new_controls[knob_cc + k] = self.controls[knob_cc + k]
        self.transport.update(self.new_transport)
        self.new_transport = {}

    def is_effective_mute(self, k):
        return self.mute_override or not self.solo_defeats_mute and 'm' in self.states and self.states['m'][k] or 's' in self.states and not self.states['s'][k] and any(self.states['s'].values())


def main_loop(screen, ctrl, sound):
    slider_size = screen.height // 2
    knob_size = min(screen.height // 2, max_knob_size)
    if knob_size % 2 == 0:
        knob_size += 1
    screen.clear()
    screen.set_title(title)
    synth_disp = None
    sample_disp = None

    while True:
        if screen.has_resized():
            raise ResizeScreenError('Screen resized')

        msg = midi_in.get_message()
        while msg:
            ctrl.update_single(*msg[0][1:])
            msg = midi_in.get_message()

        ctrl.update_all()
        sound.update()

        screen_refresh = bool(ctrl.new_controls)

        if sample_disp != sound.sample_disp or synth_disp != sound.synth_disp:
            screen_refresh = True
            if sample_disp:
                screen.print_at(' ' * len(sample_disp), screen.width - len(sample_disp), screen.height - 1, bg=bg_color)
            sample_disp = sound.sample_disp
            if synths[sound.synth][0].lower().startswith('smp'):
                screen.print_at(sample_disp, screen.width - len(sample_disp), screen.height - 1,
                                colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

            if synth_disp != sound.synth_disp:
                if synth_disp:
                    screen.print_at(' ' * len(synth_disp), screen.width - len(synth_disp), screen.height - 2, bg=bg_color)
                    if synth_disp.startswith('smp') != synths[sound.synth][0].lower().startswith('smp'):
                        ctrl.toggle_knobs_mode()
                synth_disp = sound.synth_disp
                screen.print_at(synth_disp, screen.width - len(synth_disp), screen.height - 2,
                                colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        for cc, v in ctrl.new_controls.items():
            k = cc - slider_cc
            is_slider = 0 <= k < num_controls
            if is_slider:
                control_size = slider_size
            else:
                k = cc - knob_cc
                control_size = knob_size
                if hasattr_partial(synths[sound.synth][1], 'show_track_numbers'):
                    label = str(k+1)[::-1]
                else:
                    label = note_names[(notes[k] + ctrl.track) % len(note_names)]

                for i, char in enumerate(label.ljust(2)):
                    screen.print_at(char,
                                    int((k + 0.5) * screen.width / num_controls),
                                    int(int((knob_size - 1) / 4 + 1) - knob_size / 4 - i + screen.height / 4),
                                    colour=solo_color if 's' in ctrl.states and ctrl.states['s'][k] else fg_color,
                                    attr=Screen.A_REVERSE if char != ' ' else Screen.A_NORMAL,
                                    bg=record_color if 'r' in ctrl.states and ctrl.states['r'][k] and char != ' ' else bg_color)
            val_j = int(min(v, 126) / 127 * control_size)
            for j in range(control_size):
                text = '   '
                hidden = False
                if is_slider:
                    if j == val_j:
                        text = f'{v:3}'
                    elif j < val_j:
                        text = '...'
                    else:
                        hidden = True
                else:
                    if j == val_j:
                        text = f'{v - knob_center:2}'
                        if v > knob_center:
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
                                colour=solo_color if 's' in ctrl.states and ctrl.states['s'][k] else fg_color,
                                attr=Screen.A_NORMAL if 'm' in ctrl.states and ctrl.states['m'][k] else Screen.A_BOLD,
                                bg=record_color if 'r' in ctrl.states and ctrl.states['r'][k] and not hidden else bg_color)

        if ctrl.solo_exclusive:
            screen_refresh = True
            screen.print_at(solo_exclusive_text, screen.width - len(solo_exclusive_text), solo_exclusive_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if ctrl.solo_defeats_mute:
            screen_refresh = True
            screen.print_at(solo_defeats_mute_text, screen.width - len(solo_defeats_mute_text), solo_defeats_mute_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if ctrl.mute_override:
            screen_refresh = True
            screen.print_at(mute_override_text, screen.width - len(mute_override_text), mute_override_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        if ctrl.record_exclusive:
            screen_refresh = True
            screen.print_at(record_exclusive_text, screen.width - len(record_exclusive_text), record_exclusive_y, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        help_x = max(0, (screen.width - len(max(help_text, key=len))) // 2)
        help_y = max(0, (screen.height - len(help_text)) // 2)
        if ctrl.show_help:
            screen_refresh = True
            for i, line in enumerate(help_text):
                screen.print_at(line, help_x, help_y + i, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

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
            elif c in ['k', 'ל']:  # reset Knobs
                ctrl.reset_knobs()
            elif c in ['l', 'ך']:  # reset sliders
                ctrl.reset_sliders()
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
            elif c and '0' <= c <= '9':
                num = (int(c) - 1) % 10
                if num < len(synths):
                    ctrl.marker = num

        if screen_refresh:
            screen.refresh()
        time.sleep(sleep)


controller = Controller()
soundscape = Soundscape(controller)
while True:
    try:
        Screen.wrapper(main_loop, arguments=[controller, soundscape])
        break
    except ResizeScreenError:
        controller.new_controls.update(controller.controls)
