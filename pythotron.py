from asciimatics.screen import Screen
from asciimatics.event import KeyboardEvent
from asciimatics.exceptions import ResizeScreenError
from controller import Controller
from functools import partial
import numpy as np
import re
from soundscape import Soundscape
from synths import dsaw, chord_arp, loop, paulstretch, C, hammond_drawbar_notes, fix_notes_chords, get_note_and_chord
from time import sleep


synth_max_bend_semitones = 16/15  # == 5/3 cent per step
sampler_max_bend_semitones = 3.2  # == 5 cent per step
notes = [[0, 2, 4, 5, 7, 9, 11, 12], [0, 2, 3, 5, 7, 8, 10, 12]]  # major scale, natural minor scale
chords = [[C.M, C.m, C.m, C.M, C.D, C.m, C.o], [C.m, C.o, C.M, C.m, C.m, C.M, C.D]]  # major scale, natural minor scale
asos_notes = [[2, 4, 4, 6, 7, 9, 6, 11], [2, 4, 4, 11, 7, 9, 7, 11]]
asos_chords = [[C.M_add8_no3_add10, C.m_add8_no3_add10, C.M_add8, C.M_add8, C.M_add8, C.M, C.m1, C.m], [C.M_add8_no3_add10, C.m_add8_no3_add10, C.M_add8, C.M, C.M_add8, C.M, C.m1, C.m]]
drawbar_notes = hammond_drawbar_notes
drawbars = [None, '008080800', '868868446', '888']  # unsion, clarinet, full organ, jimmy smith
detune_semitones = 0.02
arpeggio_secs = 0.25
arpeggio_amp_step = 0.005
loop_slice_secs = 0.25
sampler_elongate_factor = 0.05
loop_max_scrub_secs = None
stretch_window_secs = 0.25
stretch_slice_secs = 0.5
stretch_max_scrub_secs = None
stretch_advance_factor = 0.1  # == 1 / stretch_factor

notes, chords, drawbars = fix_notes_chords(notes, chords, drawbars)
asos_notes, asos_chords, _ = fix_notes_chords(asos_notes, asos_chords)

synths = [('sine', np.sin),
          ('chord', partial(chord_arp, chords=chords, drawbars=drawbars, drawbar_notes=drawbar_notes)),
          ('arpeggio-up7', partial(chord_arp, chords=chords, drawbars=drawbars, drawbar_notes=drawbar_notes, seventh=True, arpeggio_order=1, arpeggio_secs=arpeggio_secs, arpeggio_amp_step=arpeggio_amp_step)),
          ('dsaw', dsaw(detune_semitones=detune_semitones)),
          ('dsaw-chord', partial(chord_arp, waveform=dsaw(detune_semitones=detune_semitones), chords=chords, drawbars=drawbars, drawbar_notes=drawbar_notes)),
          ('smp:loop', partial(loop, notes=notes, max_bend_semitones=sampler_max_bend_semitones, slice_secs=loop_slice_secs, elongate_factor=sampler_elongate_factor, max_scrub_secs=loop_max_scrub_secs, extend_reversal=True)),
          ('smp:stretch+rev', partial(paulstretch, notes=notes, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, slice_secs=stretch_slice_secs, elongate_factor=sampler_elongate_factor, max_scrub_secs=stretch_max_scrub_secs, advance_factor=stretch_advance_factor, extend_reversal=True)),
          ('smp:stretch', partial(paulstretch, notes=notes, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, slice_secs=stretch_slice_secs, elongate_factor=sampler_elongate_factor, max_scrub_secs=stretch_max_scrub_secs, advance_factor=stretch_advance_factor)),
          ('smp:freeze', partial(paulstretch, notes=notes, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, max_scrub_secs=stretch_max_scrub_secs)),
          ('smp:ASOS-CV', partial(paulstretch, notes=asos_notes, max_bend_semitones=sampler_max_bend_semitones, windowsize_secs=stretch_window_secs, max_scrub_secs=stretch_max_scrub_secs)),
          ('ASOS-CV', partial(chord_arp, chords=asos_chords, drawbars=drawbars, drawbar_notes=drawbar_notes), asos_notes),
          ]
knob_modes = ['syn-pitch', 'smp-pitch', 'smp-scrub']
main_loop_delay = 0.0001
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

# unused: y, g, j, z, c, v, b, n
# avoid: ENTER, ESC if running in pycharm terminal
help_text = '''
h    Help show/hide
i    Initialize
p    reset midi Ports
k    reset Knobs (for the active knob mode)
l    reset sliders
s    Solo on all tracks
a    solo off All tracks (play All)
f    slider up solo exclusive "one-Finger" mode toggle
x    solo eXclusive mode toggle
w    solo defeats mute toggle (otherwise mute has precedence)
m    Mute on all tracks
u    mute off all tracks (Unmute)
q    mute override all tracks toggle (Quiet)
r    Record-arm on all tracks
d    record-arm off all tracks (Disarm)
e    record-arm Exclusive mode toggle
o    solo/mute/record-arm Off all tracks

1 to 9 and 0           choose synth
- =  or MARKER-REW/FF  change synth
← →  or REW/FF         change drawbar harmonizer preset (synths) / sample file (samplers)
↓ ↑  or TRACK-REW/FF   change scale M->m->M+1/2->... (synths) / slice duration and reversal (samplers)
/    or SET            sampler autotune to scale toggle
CYCLE                  knob mode toggle: pitch bend <-> pitch lock (synths) / temporal scrub (samplers)
CTRL-Q                 Quit
'''

global_control_labels = {'slider_up': 'SLIDER UP', 'solo_exclusive': 'SOLO EXCL', 'solo_defeats_mute': 'SOLO>MUTE', 'mute_override': 'MUTE OVER', 'record_exclusive': 'REC. EXCL'}
note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def main_loop(screen, ctrl, sound):
    slider_size = screen.height // 2
    knob_size = min(screen.height // 2, max_knob_size)
    if knob_size % 2 == 0:
        knob_size += 1
    screen.set_title(title)

    def reset_disp():
        nonlocal synth_disp, second_disp, next_key_code
        screen.clear()
        synth_disp = None
        second_disp = None
        next_key_code = None

    reset_disp()

    def reset():
        reset_disp()
        ctrl.reset()
        sound.reset()

    def display_global_controls(control=None):
        nonlocal screen_refresh
        if control and ctrl.global_controls[control]:
            return
        screen_refresh = True
        for y, (k, v) in enumerate(ctrl.global_controls.items()):
            x = screen.width - len(global_control_labels[k])
            if k == control:
                screen.print_at(' ' * len(global_control_labels[k]), x, y, bg=bg_color)
                break
            elif control is None and v:
                screen.print_at(global_control_labels[k], x, y, colour=overlay_fg_color, attr=overlay_attr,
                                bg=overlay_bg_color)

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
            if synths[sound.synth_ind][0].lower().startswith('smp'):
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

        for cc, v in reversed(ctrl.new_controls.items()):
            k = cc - ctrl.slider_cc
            is_slider = 0 <= k < ctrl.num_controls
            if is_slider:
                control_size = slider_size
            else:
                k = cc - ctrl.knob_cc
                control_size = knob_size
                if sound.hasattr_partial(synths[sound.synth_ind][1], 'show_track_numbers') and not ctrl.transport.get('set'):
                    label = str(k+1).rjust(2)
                else:
                    quality = ''
                    base_str = ''
                    if 'chord' in str(synths[sound.synth_ind][1]):
                        note, quality, base = get_note_and_chord(ctrl, k, sound.notes, sound.chords)
                        if base:
                            base_str = '/' + note_names[base % len(note_names)]
                    else:
                        note = get_note_and_chord(ctrl, k, sound.notes)
                    label = note_names[note % len(note_names)].ljust(2)[::-1] + quality + base_str

                for i, char in enumerate(label.ljust(6)):
                    screen.print_at(char,
                                    int((k + 0.5) * screen.width / ctrl.num_controls),
                                    int(int((knob_size - 1) / 4 + 1) - knob_size / 4 + i - 1 + screen.height / 4),
                                    colour=solo_color if 's' in ctrl.states and ctrl.states['s'][k] else fg_color,
                                    attr=Screen.A_REVERSE if char != ' ' else Screen.A_NORMAL,
                                    bg=record_color if 'r' in ctrl.states and ctrl.states['r'][k] and char != ' ' else bg_color)
            val_j = int(min(v, 126) / 127 * control_size)
            for j in range(control_size):
                text = ' '*3
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
                        text = f'{v - ctrl.knob_center:2}'
                        if v > ctrl.knob_center:
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
                                int((k + 0.5) * screen.width / ctrl.num_controls - 1 + 2 * (j - (knob_size - 1) / 2 + (1 if j < (knob_size - 1) / 2 else -1) * (abs(abs(j - (knob_size - 1) / 2) - (knob_size - 1) / 4 - 1) * 2 + 1) * (abs(j - ((knob_size - 1) / 2)) >= (knob_size - 1) / 4 + 1)) * (not is_slider)),
                                int(((slider_size / 2 - j) if is_slider else (abs(j - (knob_size - 1) / 2) - knob_size / 4)) + (is_slider + 0.5) * screen.height / 2 - (is_slider and slider_size / 2 >= screen.height / 4)),
                                colour=solo_color if 's' in ctrl.states and ctrl.states['s'][k] else fg_color,
                                attr=Screen.A_NORMAL if 'm' in ctrl.states and ctrl.states['m'][k] else Screen.A_BOLD,
                                bg=record_color if 'r' in ctrl.states and ctrl.states['r'][k] and not hidden else bg_color)

        display_global_controls()

        help_x = max(0, (screen.width - len(max(help_text, key=len))) // 2)
        help_y = max(0, (screen.height - len(help_text)) // 2)
        if ctrl.show_help:
            screen_refresh = True
            for i, line in enumerate(help_text):
                screen.print_at(line, help_x, help_y + i, colour=overlay_fg_color, attr=overlay_attr, bg=overlay_bg_color)

        ctrl.new_controls = {}

        if next_key_code is not None:
            ev = KeyboardEvent(next_key_code)
            next_key_code = None
        else:
            ev = screen.get_event()
        if isinstance(ev, KeyboardEvent):  # note: Hebrew keys assume SI 1452-2 / 1452-3 layout
            c = None
            try:
                c = chr(ev.key_code).lower()
            except ValueError:
                pass
            if c in ['h', 'י']:
                ctrl.show_help = not ctrl.show_help
                if not ctrl.show_help:
                    screen_refresh = True
                    for k in range(ctrl.num_controls):
                        ctrl.new_controls[k + ctrl.slider_cc] = ctrl.controls[k + ctrl.slider_cc]
                        ctrl.new_controls[k + ctrl.knob_cc] = ctrl.controls[k + ctrl.knob_cc]
                    for i, line in enumerate(help_text):
                        screen.print_at(re.sub(r'\S', ' ', line), help_x, help_y + i, bg=bg_color)
            elif c in ['i', 'ת']:
                reset()
            elif c in ['p', 'פ']:
                ctrl.reset_midi()
            elif c in ['k', 'ל']:
                ctrl.reset_knobs()
            elif c in ['l', 'ך']:
                ctrl.reset_sliders()
            elif c in ['s', 'ד']:
                ctrl.toggle_all('s', True)
            elif c in ['a', 'ש']:
                ctrl.toggle_all('s', False)
            elif c in ['f', 'x', 'כ', 'ס']:
                if c in ['f', 'כ']:
                    ctrl.global_controls['slider_up'] = not ctrl.global_controls['slider_up']
                    ctrl.global_controls['solo_exclusive'] = ctrl.global_controls['slider_up']
                elif c in ['x', 'ס']:
                    ctrl.global_controls['solo_exclusive'] = not ctrl.global_controls['solo_exclusive']
                    if not ctrl.global_controls['solo_exclusive']:
                        ctrl.global_controls['slider_up'] = False
                display_global_controls('solo_exclusive')
                display_global_controls('slider_up')
            elif c in ['w', 'ן']:
                ctrl.global_controls['solo_defeats_mute'] = not ctrl.global_controls['solo_defeats_mute']
                display_global_controls('solo_defeats_mute')
            elif c in ['m', 'צ']:
                ctrl.toggle_all('m', True)
            elif c in ['u', 'ו']:
                ctrl.toggle_all('m', False)
            elif c in ['q', 'ץ']:
                ctrl.global_controls['mute_override'] = not ctrl.global_controls['mute_override']
                display_global_controls('mute_override')
            elif c in ['r', 'ר']:
                ctrl.toggle_all('r', True)
            elif c in ['d', 'ג']:
                ctrl.toggle_all('r', False)
            elif c in ['e', 'ק']:
                ctrl.global_controls['record_exclusive'] = not ctrl.global_controls['record_exclusive']
                display_global_controls('record_exclusive')
            elif c in ['o', 'ם']:
                ctrl.toggle_all('msr', False)
            elif c and '0' <= c <= '9':
                num = (int(c) - 1) % 10
                if num < len(synths):
                    ctrl.marker_register = num
            elif c == '-':
                ctrl.transport['marker_rewind'] = True
                ctrl.new_transport['marker_rewind'] = False
            elif c in ['+', '=']:
                ctrl.transport['marker_forward'] = True
                ctrl.new_transport['marker_forward'] = False
            elif ev.key_code == Screen.KEY_LEFT:
                ctrl.transport['rewind'] = True
                ctrl.new_transport['rewind'] = False
            elif ev.key_code == Screen.KEY_RIGHT:
                ctrl.transport['forward'] = True
                ctrl.new_transport['forward'] = False
            elif ev.key_code == Screen.KEY_DOWN:
                ctrl.transport['track_rewind'] = True
                ctrl.new_transport['track_rewind'] = False
            elif ev.key_code == Screen.KEY_UP:
                ctrl.transport['track_forward'] = True
                ctrl.new_transport['track_forward'] = False
            elif c == '/':
                ctrl.new_transport['set'] = not ctrl.transport['set']
            elif ev.key_code == Screen.ctrl('q'):
                return
            elif ev.key_code == Screen.ctrl('p'):
                reset()
                ctrl.marker_register = -1
                ctrl.transport_register['syn'] = 1
                ctrl.transport_register['smp'] = 4 - 1
                ctrl.new_transport['set'] = True
                ctrl.global_controls['slider_up'] = True
                ctrl.global_controls['solo_exclusive'] = True
                next_key_code = Screen.KEY_UP

        if screen_refresh:
            screen.refresh()
        sleep(main_loop_delay)


note_names += [x.lower() for x in note_names]

help_text = [line.strip() for line in help_text.strip().splitlines()]
help_keys = [line[0].lower() for line in help_text if len(line) > 1 and line[1] in (' ', '\t')]
synth_names = [synth[0] for synth in synths]
synth_funcs = [str(synth[1:]) for synth in synths]
for validate in synth_names, synth_funcs, help_keys:
    assert len(validate) == len(set(validate)), sorted(x for x in validate if validate.count(x) > 1)

initial_knob_mode = synths[0][0].lower().startswith('smp')
controller = Controller(global_control_labels, knob_modes, initial_knob_mode)
soundscape = Soundscape(controller, synths, notes, chords, drawbar_notes, sample_folder, synth_max_bend_semitones)

for validate in [notes, asos_notes]:
    assert all(len(n) >= controller.num_controls for n in validate), (validate, [len(n) for n in validate], controller.num_controls)

with controller.midi_in, controller.midi_out:
    while True:
        try:
            Screen.wrapper(main_loop, arguments=[controller, soundscape])
            break
        except ResizeScreenError:
            controller.new_controls.update(controller.controls)
        except BaseException:
            soundscape.kill_sound()
            raise
