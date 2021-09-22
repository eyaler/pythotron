from inspect import signature
import librosa
from numpy import allclose
import os
from pysinewave import SineWave  # note: using the customized https://github.com/eyaler/pysinewave
from synths import get_note_and_chord, get_windowsize, get_slice_len
import sys


max_db = 0
min_db = -120
interp_hz_per_sec = 200
interp_amp_per_sec = 200
clip_off = False
dither_off = False
samplerate = 44100
cutoff = 2000000000
mono = True
stereo_to_mono_tolerance = 1e-3


def load_sample(file):
    assert isinstance(file, str)
    try:
        sample = librosa.load(file, sr=samplerate, mono=mono)[0]
    except Exception as e:
        print(e)
        print('Error loading sample', file)
        sys.exit(1)
    if stereo_to_mono_tolerance is not None and len(sample.shape) == 2 and allclose(sample[0], sample[1], atol=stereo_to_mono_tolerance):
        sample = librosa.to_mono(sample)
    return sample


class Soundscape:
    def __init__(self, ctrl, synths, notes, chords, drawbar_notes, sample_folder, synth_max_bend_semitones):
        self.ctrl = ctrl
        self.synths = synths
        self.default_notes = notes
        self.default_chords = chords
        self.drawbar_notes = drawbar_notes
        self.sample_folder = sample_folder
        self.synth_max_bend_semitones = synth_max_bend_semitones
        self.notes = None
        self.chords = None
        self.tracks = []
        self.reset()

    def reset(self):
        self.sample_ind = None
        self.synth_ind = None
        self.kill_sound()
        self.volumes = {k: min_db for k in range(self.ctrl.num_controls)}

    def kill_sound(self):
        for k in range(len(self.tracks))[::-1]:
            self.tracks[k].stop()
            del self.tracks[k]

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
        elongate_steps = self.ctrl.track_register['smp']
        elongate_factor = self.get_default(func, 'elongate_factor')
        extend_reversal = self.get_default(func, 'extend_reversal')
        slice_len, new_elongate_steps = get_slice_len(sample, slice_secs, samplerate, windowsize=windowsize,
                                                      advance_factor=advance_factor, elongate_steps=elongate_steps,
                                                      elongate_factor=elongate_factor, extend_reversal=extend_reversal,
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
        drawbars = self.get_default(self.synths[self.synth_ind][1], 'drawbars')
        if not drawbars:
            return ''
        drawbar = drawbars[self.ctrl.transport_register['syn'] % len(drawbars)]
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

    def update_sample(self):
        if self.sample_ind == self.ctrl.transport_register['smp']:
            return
        files = librosa.util.find_files(self.sample_folder, recurse=False)
        folders = [os.path.join(self.sample_folder, f) for f in os.listdir(self.sample_folder)]
        folders = [f for f in folders if os.path.isdir(f) and librosa.util.find_files(f, recurse=False)]
        paths = sorted(files + folders)
        self.ctrl.transport_register['smp'] %= len(paths)
        self.sample_ind = self.ctrl.transport_register['smp']
        self.sample_path = paths[self.sample_ind]
        if os.path.isdir(self.sample_path):
            sample_paths = librosa.util.find_files(self.sample_path, recurse=False)
            self.sample = [load_sample(sample_paths[k % len(sample_paths)]) for k in range(self.ctrl.num_controls)]
            if len(sample_paths) == 1:
                self.sample_path = sample_paths[0]
            else:
                self.sample_path = self.sample_path.rstrip(
                    os.sep) + os.sep + f'[{min(len(sample_paths), self.ctrl.num_controls)} files]'
        else:
            self.sample = load_sample(self.sample_path)
        self.synth_ind = None

    def update_synth(self):
        synth_ind = self.ctrl.marker_register % len(self.synths)
        if self.synth_ind == synth_ind:
            return
        self.synth_ind = synth_ind
        self.get_set_elongation(no_roll=True)
        synth = self.synths[synth_ind]
        self.ctrl.toggle_knob_mode(synth[0].lower().startswith('smp'))
        new_notes = synth[2] if len(synth) > 2 else self.get_default(synth[1], 'notes', default=self.default_notes)
        new_chords = synth[3] if len(synth) > 3 else self.get_default(synth[1], 'chords', default=self.default_chords)
        if new_notes != self.notes or new_chords != self.chords:
            self.ctrl.track_register['syn'] = 0
        self.notes = new_notes
        self.chords = new_chords
        for k in range(self.ctrl.num_controls):
            waveform = synth[1]
            if self.hasattr_partial(waveform, 'is_func_factory'):
                waveform = waveform(track=k, ctrl=self.ctrl, sample=self.sample, samplerate=samplerate)
            if len(self.tracks) == k:
                self.tracks.append(SineWave(pitch=get_note_and_chord(self.ctrl, k, self.notes, fix_bins=True),
                                            pitch_per_second=interp_hz_per_sec, decibels=min_db,
                                            decibels_per_second=interp_amp_per_sec, channels=1 if mono else 2,
                                            samplerate=samplerate, clip_off=False, dither_off=False,
                                            waveform=waveform, cutoff=cutoff))
                self.tracks[k].play()
            else:
                self.tracks[k].set_waveform(waveform)

    def update_volume_pitch(self):
        for k in range(self.ctrl.num_controls):
            volume = min_db
            if not self.ctrl.is_effective_mute(k):
                volume += self.ctrl.controls[k] / 127 * (max_db - min_db)
            if volume != self.volumes[k]:
                self.tracks[k].set_volume(volume)
                self.volumes[k] = volume

        if not self.hasattr_partial(self.synths[self.synth_ind][1], 'skip_external_pitch_control'):
            for cc, v in self.ctrl.new_controls.items():
                k = cc - self.ctrl.knob_cc
                if 0 <= k < self.ctrl.num_controls:
                    self.tracks[k].set_pitch(
                        get_note_and_chord(self.ctrl, k, self.notes, fix_bins=True) + self.ctrl.norm_knob(v) * self.synth_max_bend_semitones)

    def update(self):
        self.update_sample()
        self.update_synth()
        self.update_volume_pitch()
