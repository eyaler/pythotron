from datetime import datetime
from psutil import process_iter
from signal import SIGTERM
import threading
from time import sleep

from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.dispatcher import Dispatcher
from rtmidi import MidiIn, MidiOut


# this is for KORG nanoKONTROL2:
num_controls = 8
knob_center = 64
slider_cc = 0
knob_cc = 16
state_cc = dict(s=32, m=48, r=64)
transport_cc = dict(play=41, stop=42, rew=43, ff=44, rec=45, cycle=46, track_rew=58, track_ff=59, set=60, marker_rew=61, marker_ff=62)
max_cc = 100
transport_led = ['play', 'stop', 'rew', 'ff', 'rec', 'cycle']
transport_toggle = ['play', 'rec', 'cycle', 'set']
cc2transport = {v: k for k, v in transport_cc.items()}
external_led_mode = True  # requires setting LED Mode to "External" in KORG KONTROL Editor
in_port_device = 'nanoKONTROL2 1'
out_port_device = 'nanoKONTROL2 1'

knob_modes = ['syn-pitch', 'smp-pitch', 'smp-scrub']
global_control_labels = dict(slider_up='SLIDER UP', solo_exclusive='SOLO EXCL', solo_defeats_mute='SOLO>MUTE', mute_override='MUTE OVER', rec_exclusive='REC. EXCL', osc='-= OSC =-')
ip = '0.0.0.0'
port = 1337


class Controller:
    def __init__(self, initial_knob_mode):
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
        self.osc_server = None
        #self.start_osc()

    def start_osc(self):
        for proc in process_iter():
            for conns in proc.connections():
                if conns.laddr.port == port:
                    proc.send_signal(SIGTERM)
                    sleep(1)
                    break

        def handler(address, *args):
            print(f'{datetime.now()} {address}: {args}')
            address = address[1:].lower()
            if args:
                self.osc_dict[address] = args[0]

        self.osc_dict = {}
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(handler)
        self.osc_server = ThreadingOSCUDPServer((ip, port), dispatcher)
        thread = threading.Thread(target=self.osc_server.serve_forever)
        thread.daemon = True
        thread.start()

    def refresh_for_display(self):
        self.new_controls.update(self.controls)

    def refresh_sliders_of_knobs(self):
        for k in range(self.num_controls):
            if k + self.knob_cc in self.new_controls:
                self.new_controls[k + self.slider_cc] = self.controls[k + self.slider_cc]

    def reset(self):
        self.global_controls = dict.fromkeys(self.global_control_labels, False)
        self.controls = {}
        self.new_controls = {}
        self.knob_mode = self.knob_modes[self.initial_knob_mode]
        self.reset_sliders()
        self.reset_knobs()
        self.states = {state_name: dict.fromkeys(range(self.num_controls), False) for state_name in state_cc}
        self.transport = dict.fromkeys(transport_cc, False)
        self.track_register = dict(syn=0, smp=0)
        self.marker_register = 0
        self.transport_register = dict(syn=0, smp=0)
        self.reset_midi()
        self.blink_leds()
        self.stopped = True

    def reset_midi(self):
        self.midi_in.close_port()
        self.midi_out.close_port()
        in_names = self.midi_in.get_ports()
        out_names = self.midi_out.get_ports()
        in_ports = [i for i, name in enumerate(in_names) if name.lower().startswith(in_port_device.lower())]
        out_ports = [i for i, name in enumerate(out_names) if name.lower().startswith(out_port_device.lower())]
        print('In MIDI ports:', in_names, f'[{in_ports[0]}] = {in_names[in_ports[0]]}' if in_ports else '')
        print('Out MIDI ports:', out_names, f'[{out_ports[0]}] = {out_names[out_ports[0]]}' if out_ports else '')
        # for debugging use: http://www.tobias-erichsen.de/software/loopmidi.html
        assert in_ports, ('Could not find in MIDI port', in_port_device)
        assert out_ports, ('Could not find out MIDI port', out_port_device)
        self.midi_in.open_port(in_ports[0])
        self.midi_out.open_port(out_ports[0])
        self.new_states = {state_name: self.states[state_name].copy() for state_name in self.states}
        self.new_transport = self.transport.copy()

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
        for k in range(self.num_controls):
            cc = k + self.slider_cc
            self.controls[cc] = 0
            self.new_controls[cc] = 0

    def reset_knobs(self):
        for k in range(self.num_controls):
            cc = k + self.knob_cc
            self.controls[cc] = self.knob_center
            self.new_controls[cc] = self.knob_center
        self.knob_memory = {knob_mode: [self.knob_center] * self.num_controls for knob_mode in self.knob_modes}

    def toggle_knob_mode(self, is_sampler=None, track=None):
        mode = 'syn-pitch'
        if is_sampler or is_sampler is None and self.knob_mode.startswith('smp'):
            mode = 'smp-scrub' if self.transport.get('cycle') else 'smp-pitch'
        if mode != self.knob_mode:
            for k in range(self.num_controls) if track is None else [track]:
                cc = k + self.knob_cc
                self.knob_memory[self.knob_mode][k] = self.controls[cc]
                self.controls[cc] = self.knob_memory[mode][k]
                self.new_controls[cc] = self.controls[cc]
            self.knob_mode = mode

    def norm_knob(self, v):
        return min(v/self.knob_center - 1, 1)

    def get_knob(self, k, mode=None):
        if k is None:
            return 0
        mode_controls = self.controls
        i = k + knob_cc
        if i not in self.controls:
            return 0
        if mode != self.knob_mode and mode in self.knob_memory:
            mode_controls = self.knob_memory[mode]
            i = k
        return self.norm_knob(mode_controls[i])

    def get_slider(self, k):
        if k is None:
            return 0
        cc = k + slider_cc
        if cc in self.controls:
            return self.controls[cc] / 127
        return 0

    def relative_track(self, k):
        if k is None:
            return 0
        return k / max(self.num_controls - 1, 1)

    def toggle_all(self, state_names, val):
        if external_led_mode:
            for state_name in state_names:
                if state_name in state_cc:
                    self.new_states[state_name] = dict.fromkeys(range(self.num_controls), val)

    def update_single(self, cc, val):
        cc = int(cc)
        val = int(val)
        if 0 <= cc - self.slider_cc < self.num_controls or 0 <= cc - self.knob_cc < self.num_controls and (self.knob_mode.startswith('smp') or not self.transport.get('cycle')):
            self.new_controls[cc] = val
        elif cc in cc2transport:
            trans = cc2transport[cc]
            self.new_transport[trans] = not self.transport[trans] if external_led_mode and trans in transport_toggle else val > 0
        else:
            for state_name in self.states:
                k = cc - state_cc[state_name]
                if 0 <= k < self.num_controls:
                    self.new_states[state_name][k] = not self.states[state_name][k] if external_led_mode else val > 0
                    break

    def update_all(self):
        if self.global_controls['slider_up'] and 's' in state_cc:
            for cc in self.new_controls:
                k = cc - self.slider_cc
                if 0 <= k < self.num_controls and self.new_controls[cc] > self.controls[cc] > 0:
                    self.new_states['s'][k] = True

        if self.global_controls['solo_exclusive'] or self.global_controls['rec_exclusive']:
            for k in range(self.num_controls):
                if self.global_controls['solo_exclusive'] and 's' in state_cc and any(self.new_states['s'].values()) and self.states['s'][k] and k not in self.new_states['s']:
                    self.new_states['s'][k] = False
                if self.global_controls['rec_exclusive'] and 'r' in state_cc and any(self.new_states['r'].values()) and self.states['r'][k] and k not in self.new_states['r']:
                    self.new_states['r'][k] = False

        self.controls.update(self.new_controls)
        for state_name in self.new_states:
            for k, v in self.new_states[state_name].items():
                self.new_controls[k + self.slider_cc] = self.controls[k + self.slider_cc]
                self.new_controls[k + self.knob_cc] = self.controls[k + self.knob_cc]
                if external_led_mode:
                    self.send_msg(state_cc[state_name] + k, v)
            self.states[state_name].update(self.new_states[state_name])
        self.new_states = {state_name: {} for state_name in self.states}

        if self.transport.get('stop') and not self.new_transport.get('stop', True):  # works on release
            if self.transport.get('rec'):
                self.new_transport['rec'] = False
            self.stopped = True

        refresh_knobs = False
        for trans, v in self.new_transport.items():
            if not v and self.transport.get(trans):  # works on release
                if trans == 'rew':
                    self.transport_register[self.knob_mode[:3]] -= 1
                elif trans == 'ff':
                    self.transport_register[self.knob_mode[:3]] += 1
                elif trans == 'track_rew':
                    self.track_register['syn' if self.transport.get('set') else self.knob_mode[:3]] -= 1
                    refresh_knobs = True
                elif trans == 'track_ff':
                    self.track_register['syn' if self.transport.get('set') else self.knob_mode[:3]] += 1
                    refresh_knobs = True
                elif trans == 'marker_rew':
                    self.marker_register -= 1
                    refresh_knobs = True
                elif trans == 'marker_ff':
                    self.marker_register += 1
                    refresh_knobs = True
            if trans == 'set' and self.knob_mode.startswith('smp'):
                refresh_knobs = True
            if external_led_mode and trans in transport_led:
                self.send_msg(transport_cc[trans], v)
        if refresh_knobs:
            for k in range(self.num_controls):
                self.new_controls[k + self.knob_cc] = self.controls[k + self.knob_cc]
        self.transport.update(self.new_transport)
        if 'cycle' in self.new_transport:
            self.toggle_knob_mode()
        self.new_transport = {}

    def is_effective_mute(self, k):
        return self.global_controls['mute_override'] or k < self.num_controls and (not self.global_controls['solo_defeats_mute'] and 'm' in self.states and self.states['m'].get(k) or 's' in self.states and not self.states['s'].get(k) and any(self.states['s'].values()))
