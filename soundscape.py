from functools import partial
from inspect import signature
import os
import sys

import librosa
import numpy as np
from pysinewave import SineWave  # note: using the customized https://github.com/eyaler/pysinewave

from synths import get_note_and_chord, get_windowsize, get_slice_len, looper


max_db = 0
min_db = -100
interp_hz_per_sec = 200
interp_amp_per_sec = 200
clip_off = False
dither_off = False
samplerate = 44100
phase_cutoff = 2000000000
mono = True
stereo_to_mono_tolerance = 1e-3
exit_on_error = True


class Soundscape:
    def __init__(self, ctrl, synths, default_notes, sample_folder, synth_max_bend_semitones, sampler_max_bend_semitones):
        self.ctrl = ctrl
        self.synths = synths
        self.default_notes = default_notes
        self.sample_folder = sample_folder
        self.synth_max_bend_semitones = synth_max_bend_semitones
        self.sampler_max_bend_semitones = sampler_max_bend_semitones
        self.notes = None
        self.chords = None
        self.drawbars = None
        self.drawbar_notes = None
        self.tracks = []
        self.reset()

    def reset(self):
        self.sample_ind = None
        self.synth_ind = None
        self.kill_sound()
        self.volumes = {k: min_db for k in range(self.ctrl.num_controls + 1)}  # +1 for live-looper play button
        self.record_buffer_cache = None
        self.is_recording = False
        self.is_track_live_looping = [False] * (self.ctrl.num_controls+1)  # +1 for live-looper play button

    def kill_sound(self):
        for k in reversed(range(len(self.tracks))):
            self.tracks[k].stop()
            del self.tracks[k]

    @staticmethod
    def load_sample(file):
        assert isinstance(file, str)
        try:
            sample = librosa.load(file, sr=samplerate, mono=mono)[0]
        except Exception as e:
            print(e)
            print('Error loading sample', file)
            if exit_on_error:
                sys.exit(1)
            return None
        if stereo_to_mono_tolerance is not None and len(sample.shape) == 2 and np.allclose(sample[0], sample[1], rtol=0,
                                                                                           atol=stereo_to_mono_tolerance):
            sample = librosa.to_mono(sample)
        scale = abs(sample).max()
        if scale > 1:
            sample /= scale
        return sample

    @staticmethod
    def hasattr_partial(f, attr):
        return hasattr(f, attr) or hasattr(f, 'func') and hasattr(f.func, attr)

    @staticmethod
    def get_default(f, arg, default=None):
        if hasattr(f, 'keywords') and arg in f.keywords:
            return f.keywords[arg]
        try:
            params = signature(f).parameters
            if arg in params:
                return params[arg].default
        except ValueError:
            pass
        return default

    def get_set_elongation(self, no_roll=False):
        func = self.synths[self.synth_ind][1]
        if not hasattr(func, 'keywords'):
            return ''
        sample = self.sample
        smart_skipping = True
        slice_secs = self.get_default(func, 'slice_secs')
        if isinstance(sample, list):
            lengths = [s.shape[-1] for s in sample]
            sample = sample[lengths.index(max(lengths))]
            smart_skipping = all(length == self.sample[0].shape[-1] for length in lengths[1:])
            slice_secs = None
        windowsize_secs = self.get_default(func, 'windowsize_secs')
        windowsize = None if not windowsize_secs else get_windowsize(windowsize_secs, samplerate)
        advance_factor = self.get_default(func, 'advance_factor')
        loop_mode = self.get_default(func, 'loop_mode')
        elongate_steps = self.ctrl.track_register['smp']
        elongate_factor = self.get_default(func, 'elongate_factor')
        slice_len, new_elongate_steps = get_slice_len(sample, slice_secs, samplerate, windowsize=windowsize,
                                                      advance_factor=advance_factor, loop_mode=loop_mode,
                                                      elongate_steps=elongate_steps, elongate_factor=elongate_factor,
                                                      smart_skipping=smart_skipping, no_roll=no_roll,
                                                      return_elongate_steps=True)
        if new_elongate_steps is not None:
            self.ctrl.track_register['smp'] = new_elongate_steps
        slice_str = '\nslice='
        if smart_skipping or windowsize_secs and not advance_factor:
            slice_str += str(round(slice_len / samplerate * 1000)) + 'ms'
        else:
            slice_str += str(round(slice_len / sample.shape[-1] * 100)) + '%'
        return slice_str

    @property
    def synth_disp(self):
        return f'{self.synth_ind + 1}.' + self.synths[self.synth_ind][0]

    @property
    def sample_disp(self):
        return self.sample_path.split(self.sample_folder + os.sep, 1)[-1] + self.get_set_elongation()

    @property
    def drawbar_disp(self):
        if not self.get_default(self.synths[self.synth_ind][1], 'drawbars'):
            return ''
        drawbar = self.drawbars[self.ctrl.transport_register['syn'] % len(self.drawbars)]
        if drawbar is None:
            return ''
        if not isinstance(drawbar, str):
            drawbar = ''.join(drawbar)
        drawbar = drawbar.ljust(len(self.drawbar_notes), '0')
        drawbar = drawbar[:2] + ' ' + drawbar[2:7] + ' ' + drawbar[7:]
        return drawbar

    @property
    def second_disp(self):
        return self.sample_disp if self.synths[self.synth_ind][0].lower().startswith('smp') else self.drawbar_disp

    @property
    def record_buffer(self):
        if self.record_buffer_cache is None:
            buffers = [np.hstack(self.tracks[k].record_buffer) for k in range(self.ctrl.num_controls) if
                       self.tracks[k].record_buffer]
            lengths_set = {buffer.shape[-1] for buffer in buffers}
            if len(lengths_set) > 1:
                min_length = min(lengths_set)
                buffers = [buffer[..., :min_length] for buffer in buffers]
            channels_set = {len(buffer.shape) for buffer in buffers}
            if len(channels_set) > 1:
                buffers = [np.tile(buffer, reps=(2, 1)) if len(buffer.shape) == 1 else buffer for buffer in buffers]
            self.record_buffer_cache = np.sum(buffers, axis=0)
        return self.record_buffer_cache

    def update_record(self):
        if 'rec' in self.ctrl.transport:
            if self.ctrl.transport['rec'] != self.is_recording:
                for k in range(self.ctrl.num_controls):
                    self.tracks[k].record(start=not self.is_recording, clear=self.ctrl.stopped and not self.is_recording)
                self.is_recording = self.ctrl.transport['rec']
                if self.is_recording:
                    self.ctrl.stopped = False

        if self.ctrl.transport.get('play'):
            if not self.is_track_live_looping[self.ctrl.num_controls]:
                if self.record_buffer.shape[-1]:
                    self.is_track_live_looping[self.ctrl.num_controls] = True
                    waveform = looper(ctrl=self.ctrl, sample=np.copy(self.record_buffer), samplerate=samplerate)
                    self.tracks[self.ctrl.num_controls].set_waveform(waveform)
                else:
                    self.ctrl.new_transport['play'] = False
        else:
            self.is_track_live_looping[self.ctrl.num_controls] = False

        if 'r' in self.ctrl.states:
            for k, should_live_loop in self.ctrl.states['r'].items():
                if should_live_loop != self.is_track_live_looping[k]:
                    if should_live_loop:
                        if not self.record_buffer.shape[-1]:
                            self.ctrl.new_states['r'][k] = False
                            continue
                        self.is_track_live_looping[k] = True
                        waveform = partial(looper, notes=self.notes, max_bend_semitones=self.sampler_max_bend_semitones)
                        sample = np.copy(self.record_buffer)
                    else:
                        self.is_track_live_looping[k] = False
                        waveform = self.synths[self.synth_ind][1]
                        sample = self.sample
                    if self.hasattr_partial(waveform, 'is_func_factory'):
                        waveform = waveform(track=k, ctrl=self.ctrl, sample=sample, samplerate=samplerate)
                    self.tracks[k].set_waveform(waveform)

        if self.is_recording:
            self.record_buffer_cache = None

    def update_sample(self, name_or_num=None):
        ind = self.ctrl.transport_register['smp']
        if self.sample_ind == ind and name_or_num is None:
            return
        files = librosa.util.find_files(self.sample_folder, recurse=False)
        folders = [os.path.join(self.sample_folder, f) for f in os.listdir(self.sample_folder)]
        folders = [f for f in folders if os.path.isdir(f) and librosa.util.find_files(f, recurse=False)]
        paths = sorted(files + folders)
        if name_or_num is not None:
            try:
                inds = [int(name_or_num) - 1]
            except ValueError:
                name_or_num = str(name_or_num)
                inds = [i for i, path in enumerate(paths) if path.rstrip(os.sep) == os.path.join(self.sample_folder, name_or_num).rstrip(os.sep)]
            if not inds:
                print('Missing sample', name_or_num)
                if exit_on_error:
                    sys.exit(1)
                return
            ind = inds[0]
        direction = 1 if self.sample_ind is None or ind >= self.sample_ind else -1
        ind %= len(paths)
        path = paths[ind]
        if os.path.isdir(path):
            sample_paths = librosa.util.find_files(path, recurse=False)
            sample = []
            k = 0
            while len(sample) < self.ctrl.num_controls and k < len(sample_paths) * self.ctrl.num_controls:
                track_sample = self.load_sample(sample_paths[k % len(sample_paths)])
                if track_sample is not None:
                    sample.append(track_sample)
                k += 1
            if len(sample_paths) == 1:
                path = sample_paths[0]
            else:
                path = path.rstrip(os.sep) + os.sep + f'[{min(len(sample_paths), self.ctrl.num_controls)} files]'
        else:
            sample = self.load_sample(path)
        if sample is None:
            if name_or_num is not None:
                return
            self.ctrl.transport_register['smp'] = ind + direction
            return self.update_sample()
        self.ctrl.transport_register['smp'] = ind
        self.sample_ind = ind
        self.sample_path = path
        self.sample = sample
        self.synth_ind = None

    def update_synth(self, name_or_num=None):
        if name_or_num is not None:
            try:
                inds = [int(name_or_num) - 1]
            except ValueError:
                name_or_num = str(name_or_num)
                inds = [i for i, synth in enumerate(self.synths) if synth[0].lower() == name_or_num.lower()]
            if not inds:
                print('Missing synth', name_or_num)
                if exit_on_error:
                    sys.exit(1)
                return
            self.ctrl.marker_register = inds[0]
        synth_ind = self.ctrl.marker_register % len(self.synths)
        if self.synth_ind == synth_ind:
            return
        self.synth_ind = synth_ind
        self.get_set_elongation(no_roll=True)
        synth = self.synths[synth_ind]
        self.ctrl.toggle_knob_mode(is_sampler=synth[0].lower().startswith('smp'))
        new_notes = synth[2] if len(synth) > 2 else self.get_default(synth[1], 'notes', default=self.default_notes)
        new_chords = self.get_default(synth[1], 'chords')
        new_drawbars = self.get_default(synth[1], 'drawbars')
        new_drawbar_notes = self.get_default(synth[1], 'drawbar_notes')
        if new_notes != self.notes or new_chords is not None and new_chords != self.chords:
            if new_notes != self.notes or self.chords is not None:
                self.ctrl.track_register['syn'] = 0
            self.notes = new_notes
            self.chords = new_chords
        if new_drawbars is not None and new_drawbars != self.drawbars or new_drawbar_notes is not None and new_drawbar_notes != self.drawbar_notes:
            self.ctrl.transport_register['syn'] = 0
            self.drawbars = new_drawbars
            self.drawbar_notes = new_drawbar_notes
        for k in range(self.ctrl.num_controls + 1):  # +1 for live-looper play button
            waveform = synth[1]
            safe_track = k % self.ctrl.num_controls
            if self.hasattr_partial(waveform, 'is_func_factory'):
                waveform = waveform(track=safe_track, ctrl=self.ctrl, sample=self.sample, samplerate=samplerate)
            if len(self.tracks) == k:
                self.tracks.append(SineWave(pitch=get_note_and_chord(self.ctrl, safe_track, self.notes, fix_bins=True),
                                            pitch_per_second=interp_hz_per_sec, decibels=min_db,
                                            decibels_per_second=interp_amp_per_sec, channels=1 if mono else 2,
                                            samplerate=samplerate, clip_off=False, dither_off=False,
                                            waveform=waveform, phase_cutoff=phase_cutoff, db_cutoff=min_db))
                self.tracks[k].play()
            elif k < self.ctrl.num_controls and ('r' not in self.ctrl.states or not self.ctrl.states['r'][k]):
                self.tracks[k].set_waveform(waveform)

    def update_volume_pitch(self):
        for k in range(len(self.volumes)):
            volume = min_db
            if not self.ctrl.is_effective_mute(k):
                if k < self.ctrl.num_controls:
                    volume += self.ctrl.controls[k + self.ctrl.slider_cc] / 127 * (max_db-min_db)
                elif self.is_track_live_looping[k]:
                    volume = max_db
            if volume != self.volumes[k]:
                self.tracks[k].set_volume(volume)
                self.volumes[k] = volume

        if not self.hasattr_partial(self.synths[self.synth_ind][1], 'skip_external_pitch_control'):
            for cc, v in self.ctrl.new_controls.items():
                k = cc - self.ctrl.knob_cc
                if 0 <= k < self.ctrl.num_controls:
                    self.tracks[k].set_pitch(
                        get_note_and_chord(self.ctrl, k, self.notes, fix_bins=True) + self.ctrl.norm_knob(v)*self.synth_max_bend_semitones)

    def update(self):
        self.update_record()
        self.update_sample()
        self.update_synth()
        self.update_volume_pitch()
