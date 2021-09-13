from asciimatics.screen import Screen
from asciimatics.event import KeyboardEvent
from asciimatics.exceptions import ResizeScreenError
import copy
from functools import partial
from inspect import signature
import librosa
import numpy as np
import os
from pysinewave import SineWave  # note: using the customized https://github.com/eyaler/pysinewave
import re
import rtmidi
from synths import dsaw, chord, loop, paulstretch, get_slice_len, get_windowsize
import sys
import time
from types import SimpleNamespace


max_db = 0
min_db = -120
interp_hz_per_sec = 200
synth_max_bend_semitones = 16/15  # == 5/3 cent per step
sampler_max_bend_semitones = 3.2  # == 5 cent per step
interp_amp_per_sec = 200
samplerate = 44100
cutoff = 2000000000
notes = [[0, 2, 4, 5, 7, 9, 11, 12], [0, 2, 3, 5, 7, 8, 10, 12]]  # major scale, natural minor scale
C = SimpleNamespace(D=[0, 4, 7, 10], M=[0, 4, 7, 11], m=[0, 3, 7, 10], d=[0, 3, 6, 10])  # by default seventh=False and the last note is ignored
chord_notes = [[C.M, C.m, C.m, C.M, C.D, C.m, C.d], [C.m, C.d, C.M, C.m, C.m, C.M, C.D]]  # major scale, natural minor scale
asos_notes = [[2, 4, 4, 6, 7, 9, 11, 11]] * 2
asos_chords = [[C.M, C.m, C.M, C.M, C.M, C.M, C.m, C.M], [C.M, C.m, C.M, C.M, C.m, C.M, C.m, C.M]]
drawbar_notes = [-12, 7, 0, 12, 19, 24, 28, 31, 36]
drawbars = [None, '008080800', '868868446', '888']  # unsion, clarinet, full organ, jimmy smith
detune_semitones = 0.02
arpeggio_secs = 0.25
arpeggio_amp_step = 0.005
loop_slice_secs = 0.25
sampler_elongate_factor = 0.1
loop_max_scrub_secs = None
stretch_window_secs = 0.25
stretch_slice_secs = 0.5
stretch_max_scrub_secs = None
stretch_advance_factor = 0.1  # == 1 / stretch_factor
synths = [('sine', np.sin),
          ('chord', partial(chord, chord_notes=chord_notes, drawbars=drawbars, drawbar_notes=drawbar_notes)),
          ('ASOS-CV', partial(chord, chord_notes=asos_chords, drawbars=drawbars, drawbar_notes=drawbar_notes)),
          ('arpeggio-up7', partial(chord, chord_notes=chord_notes, drawbars=drawbars, drawbar_notes=drawbar_notes, seventh=True, arpeggio_order=1, arpeggio_secs=arpeggio_secs, arpeggio_amp_step=arpeggio_amp_step, samplerate=samplerate)),
          ('dsaw', dsaw(detune_semitones=detune_semitones)),
          ('dsaw-chord', partial(chord, waveform=dsaw(detune_semitones=detune_semitones), chord_notes=chord_notes, drawbars=drawbars, drawbar_notes=drawbar_notes)),
          ('smp:loop', partial(loop, max_bend_semitones=sampler_max_bend_semitones, slice_secs=loop_slice_secs, elongate_factor=sampler_elongate_factor, max_scrub_secs=loop_max_scrub_secs, extend_reversal=True, samplerate=samplerate)),
          ('smp:stretch+rev', partial(paulstretch, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, slice_secs=stretch_slice_secs, elongate_factor=sampler_elongate_factor, max_scrub_secs=stretch_max_scrub_secs, advance_factor=stretch_advance_factor, extend_reversal=True, samplerate=samplerate)),
          ('smp:stretch', partial(paulstretch, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, slice_secs=stretch_slice_secs, elongate_factor=sampler_elongate_factor, max_scrub_secs=stretch_max_scrub_secs, advance_factor=stretch_advance_factor, samplerate=samplerate)),
          ('smp:freeze', partial(paulstretch, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, max_scrub_secs=stretch_max_scrub_secs, samplerate=samplerate)),
          ]
knob_modes = ['syn-pitch', 'smp-pitch', 'smp-scrub']
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
max_cc = 100
transport_led = ['play', 'stop', 'rewind', 'forward', 'record', 'cycle']
cc2trans = {v: k for k, v in transport_cc.items()}
external_led_mode = True  # requires setting LED Mode to "External" in KORG KONTROL Editor
in_port_device = 'nanoKONTROL2 1'
out_port_device = 'nanoKONTROL2 1'

title = 'Pythotron'
max_knob_size = 21
sample_folder = 'samples'

fg_color = Screen.COLOUR_RED
bg_color = Screen.COLOUR_BLACK
solo_color = Screen.COLOUR_GREEN
record_color = Screen.COLOUR_MAGENTA
overlay_fg_color = Screen.COLOUR_YELLOW
overlay_attr = Screen.A_BOLD
overlay_bg_color = Screen.COLOUR_BLUE
drawbar_bg_colors = [Screen.COLOUR_RED, Screen.COLOUR_RED, Screen.COLOUR_WHITE, Screen.COLOUR_WHITE, Screen.COLOUR_BLACK, Screen.COLOUR_WHITE, Screen.COLOUR_BLACK, Screen.COLOUR_BLACK, Screen.COLOUR_WHITE]


help_text = '''
h    Help show/hide
q    Quit
i    Initialize
p    reset midi Ports
k    reset Knobs (for the active knob mode)
l    reset sliders
s    Solo on all tracks
a    solo off All tracks
d    solo exclusive mode toggle
f    solo deFeats mute toggle
m    Mute on all tracks
n    mute off all tracks
o    mute Override all tracks toggle
r    Record-arm on all tracks
t    record-arm off all tracks
e    record-arm Exclusive mode Toggle
u    solo/mute/record-arm off all tracks
1-0  choose synth

cycle                    toggle knob mode: pitch bend <-> pitch lock (synths) / temporal scrub (samplers)
track rewind/forward     change scale maj->min->maj+1/2->min+1/2->... (synths) / slice duration and reversal (samplers)
marker rewind/forward    change synths and samplers
rewind/forward           change drawbar harmonizer preset (synths) / sample file (samplers)
'''

solo_exclusive_text = 'SOLO EXCL'
solo_defeats_mute_text = 'SOLO>MUTE'
mute_override_text = 'MUTE OVER'
record_exclusive_text = 'REC. EXCL'
solo_exclusive_y = 0
solo_defeats_mute_y = 1
mute_override_y = 2
record_exclusive_y = 3

note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
note_names += [x.lower() for x in note_names]
chord2quality = {tuple(v[:3]): k for k, v in C.__dict__.items()}

if not isinstance(notes[0], (list, tuple)):
    notes = [notes]
assert all(len(n) >= num_controls for n in notes), ([len(n) for n in notes], num_controls)

if not isinstance(chord_notes[0], (list, tuple)):
    chord_notes = [chord_notes]
if not isinstance(chord_notes[0][0], (list, tuple)):
    chord_notes = [chord_notes]
assert len(notes) >= len(chord_notes) and not len(notes) % len(chord_notes), (len(notes), len(chord_notes))

if not isinstance(drawbars, (list, tuple)) or not hasattr(drawbars[-1], '__len__'):
    drawbars = [drawbars]

synth_names, synth_funcs = zip(*synths)
assert len(synth_names) == len(set(synth_names)), sorted(x for x in synth_names if synth_names.count(x) > 1)
assert len(synth_funcs) == len(set(synth_funcs)), sorted(x for x in synth_funcs if synth_funcs.count(x) > 1)

help_text = [line.strip() for line in help_text.strip().splitlines()]
help_keys = [line[0].lower() for line in help_text if len(line) > 1 and line[1] in (' ', '\t')]
assert len(help_keys) == len(set(help_keys)), sorted(x for x in help_keys if help_keys.count(x) > 1)


def hasattr_partial(f, attr):
    return hasattr(f, attr) or hasattr(f, 'func') and hasattr(f.func, attr)


def get_default(f, arg):
    if arg in f.keywords:
        return f.keywords[arg]
    params = signature(f).parameters
    if arg in params:
        return params[arg].default
    return None


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
        synth = synths[self.synth][1]
        slice_secs_str = ''
        if hasattr(synth, 'keywords'):
            samplerate = get_default(synth, 'samplerate')
            windowsize_secs = get_default(synth, 'windowsize_secs')
            windowsize = None if not windowsize_secs else get_windowsize(windowsize_secs, samplerate)
            slice_len = get_slice_len(get_default(synth, 'slice_secs'), self.ctrl.track_register['smp'], get_default(synth, 'elongate_factor'), samplerate, self.sample, windowsize=windowsize, advance_factor=get_default(synth, 'advance_factor'))
            slice_secs_str = f'\n{slice_len / samplerate:.3f}'
            slice_secs_str = slice_secs_str[:-2] + slice_secs_str[-2:].rstrip('0')
        return self.sample_path.split(sample_folder + os.sep, 1)[-1] + slice_secs_str

    @property
    def drawbar_disp(self):
        synth = synths[self.synth][1]
        if not hasattr(synth, 'keywords') or 'drawbars' not in synth.keywords:
            return ''
        drawbars = synth.keywords['drawbars']
        drawbar = drawbars[self.ctrl.transport_register['syn'] % len(drawbars)]
        if drawbar is None:
            return ''
        if not isinstance(drawbar, str):
            drawbar = ''.join(drawbar).ljust(len(drawbar_notes), '0')
        drawbar = drawbar[:2] + ' ' + drawbar[2:7] + ' ' + drawbar[7:]
        return drawbar

    @property
    def second_disp(self):
        return self.sample_disp if synths[self.synth][0].lower().startswith('smp') else self.drawbar_disp

    def get_note(self, k, ret_quality=False):
        active_notes = notes
        active_chords = chord_notes
        if synths[self.synth][0].lower().startswith('asos'):
            active_notes = asos_notes
            active_chords = asos_chords
        scale_quality = self.ctrl.track_register['syn'] % len(active_notes)
        note = active_notes[scale_quality][k] + self.ctrl.track_register['syn'] // len(active_notes)
        if ret_quality:
            return note, chord2quality.get(tuple(active_chords[scale_quality][k % len(active_chords[scale_quality])][:3]), ' ')
        return note

    def instantiate_waveform(self, synth, track=None):
        waveform = synths[synth][1]
        if hasattr_partial(waveform, 'is_func_factory'):
            waveform = waveform(track=track, ctrl=self.ctrl, sample=self.sample)
        return waveform

    def load_sample(self, sample_ind=None):
        if sample_ind is not None:
            self.sample_ind = sample_ind
        files = librosa.util.find_files(sample_folder)
        self.sample_path = files[sample_ind % (len(files))]
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
            self.tracks.append(SineWave(pitch=self.get_note(k), pitch_per_second=interp_hz_per_sec, decibels=min_db,
                                        decibels_per_second=interp_amp_per_sec, channels=1 if mono else 2,
                                        samplerate=samplerate, waveform=self.instantiate_waveform(self.synth, track=k), cutoff=cutoff))
            self.tracks[k].play()

    def update(self):
        if self.sample_ind != self.ctrl.transport_register['smp']:
            self.load_sample(self.ctrl.transport_register['smp'])
        synth = self.ctrl.marker_register % len(synths)
        self.ctrl.toggle_knob_mode(synths[synth][0].lower().startswith('smp'))
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

        if not hasattr_partial(synths[synth][1], 'skip_external_pitch_control'):
            for cc, v in self.ctrl.new_controls.items():
                k = cc - knob_cc
                if 0 <= k < num_controls:
                    self.tracks[k].set_pitch(self.get_note(k) + self.ctrl.norm_knob(v) * synth_max_bend_semitones)


class Controller:
    def __init__(self):
        self.midi_in = rtmidi.MidiIn()
        self.midi_out = rtmidi.MidiOut()
        self.reset()

    def reset(self):
        self.mute_override = False
        self.solo_exclusive = False
        self.solo_defeats_mute = False
        self.record_exclusive = False
        self.show_help = False
        self.controls = {}
        self.new_controls = {}
        self.knobs_memory = {knob_mode: {k: knob_center for k in range(num_controls)} for knob_mode in knob_modes}
        self.knob_mode = knob_modes[synths[0][0].lower().startswith('smp')]
        self.reset_sliders()
        self.reset_knobs()
        self.new_states = {state_name: {k: False for k in range(num_controls)} for state_name in state_cc}
        self.states = copy.deepcopy(self.new_states)
        self.new_transport = {k: False for k in transport_cc}
        self.transport = self.new_transport.copy()
        self.track_register = {'syn': 0, 'smp': 0}
        self.marker_register = 0
        self.transport_register = {'syn': 0, 'smp': 0}
        self.reset_midi()
        self.blink_leds()

    def reset_midi(self):
        self.midi_in.close_port()
        self.midi_out.close_port()
        in_ports = self.midi_in.get_ports()
        out_ports = self.midi_out.get_ports()
        in_port = [i for i, name in enumerate(in_ports) if name.lower().startswith(in_port_device.lower())][0]
        out_port = [i for i, name in enumerate(out_ports) if name.lower().startswith(out_port_device.lower())][0]
        print('In MIDI ports:', in_ports, in_port)
        print('Out MIDI ports:', out_ports, out_port)
        self.midi_in.open_port(in_port)
        self.midi_out.open_port(out_port)
        for state_name in self.states:
            self.new_states[state_name].update(self.states[state_name])
        self.new_transport.update(self.transport)

    def send_msg(self, cc, val):
        self.midi_out.send_message([176, cc, val * 127])

    def blink_leds(self, blink_leds_delay=0.2):
        if external_led_mode:
            for cc in range(max_cc):
                self.send_msg(cc, False)
            time.sleep(blink_leds_delay)
            for cc in range(max_cc):
                self.send_msg(cc, True)
            time.sleep(blink_leds_delay)
            for cc in range(max_cc):
                self.send_msg(cc, False)

    def reset_sliders(self):
        for k in range(num_controls):
            cc = k + slider_cc
            self.controls[cc] = 0
            self.new_controls[cc] = 0

    def reset_knobs(self):
        for k in range(num_controls):
            cc = k + knob_cc
            self.controls[cc] = knob_center
            self.new_controls[cc] = knob_center
            self.knobs_memory[self.knob_mode][k] = 0

    def toggle_knob_mode(self, is_sampler=None):
        mode = 'syn-pitch'
        if is_sampler or is_sampler is None and self.knob_mode.startswith('smp'):
            mode = 'smp-scrub' if self.transport.get('cycle') else 'smp-pitch'
        if mode != self.knob_mode:
            for k in range(num_controls):
                cc = k + knob_cc
                self.knobs_memory[self.knob_mode][k] = self.controls[cc]
                self.controls[cc] = self.knobs_memory[mode][k]
                self.new_controls[cc] = self.controls[cc]
            self.knob_mode = mode

    @staticmethod
    def norm_knob(v):
        return min(v / knob_center - 1, 1)

    def get_knob(self, k, mode=None):
        mode_controls = self.controls
        i = k + knob_cc
        if mode != self.knob_mode and mode in self.knobs_memory:
            mode_controls = self.knobs_memory[mode]
            i = k
        if i in mode_controls:
            return self.norm_knob(mode_controls[i])
        return 0

    def get_slider(self, k):
        cc = k + slider_cc
        if cc in self.controls:
            return self.controls[cc] / 127
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
        if 0 <= cc - slider_cc < num_controls or 0 <= cc - knob_cc < num_controls and (self.knob_mode.startswith('smp') or not self.transport.get('cycle')):
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
                    self.send_msg(state_cc[state_name] + k, v)
            self.states[state_name].update(self.new_states[state_name])
        self.new_states = {state_name: {} for state_name in self.states}

        if not self.new_transport.get('stop', True):
            if self.transport.get('play'):
                self.new_transport['play'] = False
            if self.transport.get('record'):
                self.new_transport['record'] = False

        if 'cycle' in self.new_transport:
            self.toggle_knob_mode()

        refresh_knobs = False
        for trans, v in self.new_transport.items():
            if v:
                if trans == 'track_rewind':
                    self.track_register[self.knob_mode[:3]] -= 1
                    refresh_knobs = True
                elif trans == 'track_forward':
                    self.track_register[self.knob_mode[:3]] += 1
                    refresh_knobs = True
                elif trans == 'marker_rewind':
                    self.marker_register -= 1
                    refresh_knobs = True
                elif trans == 'marker_forward':
                    self.marker_register += 1
                    refresh_knobs = True
                elif trans == 'rewind':
                    self.transport_register[self.knob_mode[:3]] -= 1
                elif trans == 'forward':
                    self.transport_register[self.knob_mode[:3]] += 1
            if external_led_mode and trans in transport_led:
                self.send_msg(transport_cc[trans], v)
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
    second_disp = None

    while True:
        if screen.has_resized():
            raise ResizeScreenError('Screen resized')

        msg = ctrl.midi_in.get_message()
        while msg:
            ctrl.update_single(*msg[0][1:])
            msg = ctrl.midi_in.get_message()

        ctrl.update_all()
        sound.update()

        screen_refresh = bool(ctrl.new_controls)

        if second_disp != sound.second_disp or synth_disp != sound.synth_disp:
            screen_refresh = True
            if second_disp:
                for i, line in enumerate(second_disp.splitlines()):
                    screen.print_at(' ' * len(line), 0, 1 + i, bg=bg_color)
            second_disp = sound.second_disp
            if synths[sound.synth][0].lower().startswith('smp'):
                for i, line in enumerate(second_disp.splitlines()):
                    screen.print_at(line, 0, 1 + i, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)
            else:
                i = 0
                for x, c in enumerate(second_disp):
                    if c != ' ':
                        screen.print_at(c, x, 1, colour=overlay_fg_color, attr=overlay_attr, bg=drawbar_bg_colors[i])
                        i += 1

            if synth_disp != sound.synth_disp:
                if synth_disp:
                    screen.print_at(' ' * len(synth_disp), 0, 0, bg=bg_color)
                synth_disp = sound.synth_disp
                screen.print_at(synth_disp, 0, 0, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        for cc, v in ctrl.new_controls.items():
            k = cc - slider_cc
            is_slider = 0 <= k < num_controls
            if is_slider:
                control_size = slider_size
            else:
                k = cc - knob_cc
                control_size = knob_size
                if hasattr_partial(synths[sound.synth][1], 'show_track_numbers'):
                    label = ' ' + str(k+1)[::-1]
                else:
                    note, quality = sound.get_note(k, ret_quality=True)
                    if 'chord' not in str(synths[sound.synth][1]):
                        quality = ' '
                    label = quality + note_names[note % len(note_names)]

                for i, char in enumerate(label.ljust(3)):
                    screen.print_at(char,
                                    int((k + 0.5) * screen.width / num_controls),
                                    int(int((knob_size - 1) / 4 + 1) - knob_size / 4 + 1 - i + screen.height / 4),
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
                screen.clear()
                ctrl.reset()
                sound.reset()
            elif c in ['p', 'פ']:  # reset midi Ports
                ctrl.reset_midi()
            elif c in ['k', 'ל']:  # reset Knobs (for the active knob mode)
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
            elif c in ['t', 'א']:  # record-arm off all tracks
                ctrl.toggle_all('r', False)
            elif c in ['e', 'ק'] and external_led_mode:  # record-arm Exclusive mode toggle
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
                    ctrl.marker_register = num

        if screen_refresh:
            screen.refresh()
        time.sleep(sleep)


controller = Controller()
soundscape = Soundscape(controller)
with controller.midi_in, controller.midi_out:
    while True:
        try:
            Screen.wrapper(main_loop, arguments=[controller, soundscape])
            break
        except ResizeScreenError:
            controller.new_controls.update(controller.controls)
