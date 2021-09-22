from copy import deepcopy
from rtmidi import MidiIn, MidiOut
from time import sleep


# this is for KORG nanoKONTROL2:
num_controls = 8
knob_center = 64
slider_cc = 0
knob_cc = 16
state_cc = {'s': 32, 'm': 48, 'r': 64}
transport_cc = {'play': 41, 'stop': 42, 'rewind': 43, 'forward': 44, 'record': 45, 'cycle': 46, 'track_rewind': 58, 'track_forward': 59, 'set': 60, 'marker_rewind': 61, 'marker_forward': 62}
max_cc = 100
transport_led = ['play', 'stop', 'rewind', 'forward', 'record', 'cycle']
transport_toggle = ['play', 'record', 'cycle', 'set']
cc2transport = {v: k for k, v in transport_cc.items()}
external_led_mode = True  # requires setting LED Mode to "External" in KORG KONTROL Editor
in_port_device = 'nanoKONTROL2 1'
out_port_device = 'nanoKONTROL2 1'


class Controller:
    def __init__(self, global_control_labels, knob_modes, initial_knob_mode):
        self.num_controls = num_controls
        self.slider_cc = slider_cc
        self.knob_cc = knob_cc
        self.knob_center = knob_center
        self.global_control_labels = global_control_labels
        self.knob_modes = knob_modes
        self.initial_knob_mode = initial_knob_mode
        self.midi_in = MidiIn()
        self.midi_out = MidiOut()
        self.reset()

    def reset(self):
        self.global_controls = {k: False for k in self.global_control_labels}
        self.show_help = False
        self.controls = {}
        self.new_controls = {}
        self.knobs_memory = {knob_mode: {k: knob_center for k in range(num_controls)} for knob_mode in self.knob_modes}
        self.knob_mode = self.knob_modes[self.initial_knob_mode]
        self.reset_sliders()
        self.reset_knobs()
        self.new_states = {state_name: {k: False for k in range(num_controls)} for state_name in state_cc}
        self.states = deepcopy(self.new_states)
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
            sleep(blink_leds_delay)
            for cc in range(max_cc):
                self.send_msg(cc, True)
            sleep(blink_leds_delay)
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
        elif cc in cc2transport:
            trans = cc2transport[cc]
            self.new_transport[trans] = not self.transport[trans] if external_led_mode and trans in transport_toggle else val > 0
        else:
            for state_name in self.states:
                k = cc - state_cc[state_name]
                if 0 <= k < num_controls:
                    self.new_states[state_name][k] = not self.states[state_name][k] if external_led_mode else val > 0
                    break

    def update_all(self):
        if self.global_controls['slider_up'] and 's' in state_cc:
            for cc in self.new_controls:
                k = cc - slider_cc
                if 0 <= k < num_controls and self.new_controls[cc] > self.controls[cc] > 0:
                    self.new_states['s'][k] = True

        if self.global_controls['solo_exclusive'] or self.global_controls['record_exclusive']:
            for k in range(num_controls):
                if self.global_controls['solo_exclusive'] and 's' in state_cc and (self.new_states['s'].values()) and self.states['s'][k] and k not in self.new_states['s']:
                    self.new_states['s'][k] = False
                if self.global_controls['record_exclusive'] and 'r' in state_cc and any(self.new_states['r'].values()) and self.states['r'][k] and k not in self.new_states['r']:
                    self.new_states['r'][k] = False

        self.controls.update(self.new_controls)
        for state_name in self.new_states:
            for k, v in self.new_states[state_name].items():
                self.new_controls[k + slider_cc] = self.controls[k + slider_cc]
                self.new_controls[k + knob_cc] = self.controls[k + knob_cc]
                if external_led_mode:
                    self.send_msg(state_cc[state_name] + k, v)
            self.states[state_name].update(self.new_states[state_name])
        self.new_states = {state_name: {} for state_name in self.states}

        if not self.new_transport.get('stop', True):  # works on release
            if self.transport.get('play'):
                self.new_transport['play'] = False
            if self.transport.get('record'):
                self.new_transport['record'] = False

        if 'cycle' in self.new_transport:
            self.toggle_knob_mode()

        refresh_knobs = False
        for trans, v in self.new_transport.items():
            if not v and self.transport.get(trans):  # works on release
                if trans == 'rewind':
                    self.transport_register[self.knob_mode[:3]] -= 1
                elif trans == 'forward':
                    self.transport_register[self.knob_mode[:3]] += 1
                elif trans == 'track_rewind':
                    self.track_register['syn' if self.transport.get('set') else self.knob_mode[:3]] -= 1
                    refresh_knobs = True
                elif trans == 'track_forward':
                    self.track_register['syn' if self.transport.get('set') else self.knob_mode[:3]] += 1
                    refresh_knobs = True
                elif trans == 'marker_rewind':
                    self.marker_register -= 1
                    refresh_knobs = True
                elif trans == 'marker_forward':
                    self.marker_register += 1
                    refresh_knobs = True
            if 'set' in self.new_transport and self.knob_mode.startswith('smp'):
                refresh_knobs = True
            if external_led_mode and trans in transport_led:
                self.send_msg(transport_cc[trans], v)
        if refresh_knobs:
            for k in range(num_controls):
                self.new_controls[k + knob_cc] = self.controls[k + knob_cc]
        self.transport.update(self.new_transport)
        self.new_transport = {}

    def is_effective_mute(self, k):
        return self.global_controls['mute_override'] or not self.global_controls['solo_defeats_mute'] and 'm' in self.states and self.states['m'][k] or 's' in self.states and not self.states['s'][k] and any(self.states['s'].values())
