import librosa
from numba import jit
import numpy as np
from pysinewave.utilities import MIDDLE_C_FREQUENCY
from time import time
from types import SimpleNamespace

rng = np.random  # .Generator(np.random.MT19937())  # Mersenne Twister

gain_normalization_exponent = 1
# controls the tradeoff between clipping artifacts and volume limiting when having multiple harmonics (chords, drawbars) per synth track
# 0   == no normalization (louder with more harmonics, expect clipping)
# 0.5 == normalize to RMS (average volume stays similar with more harmonics, expect clipping for high volume)
# 1   == limiter (volume is lower with more harmonics and generally does not utilize the full dynamic range but no clipping)

BASE_C_FREQUENCY = MIDDLE_C_FREQUENCY

bins_per_octave = 12

hammond_drawbar_notes = (-12, 7, 0, 12, 19, 24, 28, 31, 36)

C = SimpleNamespace(M=[0, 4, 7, 11], m=[0, 3, 7, 10], D=[0, 4, 7, 10], o=[0, 3, 6, 9], A=[0, 4, 8, 10])  # usually seventh=False and the 4th note is ignored; M must come before D


def add_chord_inversions(chord_namespace):
    copy_of_namespace = chord_namespace.__dict__.copy()
    for i in range(1, 4):
        for k, v in copy_of_namespace.items():
            chord_namespace.__dict__[k + str(i)] = v[i:] + [n + bins_per_octave for n in v[:i]]

    for k, v in copy_of_namespace.items():
        chord_namespace.__dict__[k + '_add8'] = v[:1] + chord_namespace.__dict__[k + '1']
        chord_namespace.__dict__[k + '_add8_no3_add10'] = v[:1] + chord_namespace.__dict__[k + '2']


add_chord_inversions(C)


def fix_chords(chords, drawbars):
    if not isinstance(chords[0], (list, tuple)):
        chords = [chords]
    if not isinstance(chords[0][0], (list, tuple)):
        chords = [chords]
    if not isinstance(drawbars, (list, tuple)) or not hasattr(drawbars[-1], '__len__'):
        drawbars = [drawbars]
    return chords, drawbars


def fix_notes_chords(notes, chords, drawbars=None):
    if not isinstance(notes[0], (list, tuple)):
        notes = [notes]
    chords, drawbars = fix_chords(chords, drawbars)
    assert len(notes) >= len(chords) and not len(notes) % len(chords), (len(notes), len(chords))
    return notes, chords, drawbars


def trim_chord(chord, seventh=False):
    return tuple(n for n in chord if seventh or not 8 < n % bins_per_octave < bins_per_octave)


def norm_chord(chord, seventh=False):
    bass = min(chord)
    return tuple(sorted(set(bass + (n - bass) % bins_per_octave for n in trim_chord(chord, seventh=seventh))))


chord2quality = {norm_chord(v): k for k, v in reversed(C.__dict__.items())}
assert chord2quality == {(12, 16, 20): 'A3', (12, 15, 18): 'o3', (12, 16, 19): 'M3', (12, 15, 19): 'm3', (8, 12, 16): 'A2', (6, 12, 15): 'o2', (7, 12, 16): 'M2', (7, 12, 15): 'm2', (4, 8, 12): 'A1', (3, 6, 12): 'o1', (4, 7, 12): 'M1', (3, 7, 12): 'm1', (0, 4, 8): 'A', (0, 3, 6): 'o', (0, 4, 7): 'M', (0, 3, 7): 'm'}


def get_note_and_chord(ctrl, k, notes, chords=None, fix_bins=False):
    scale_quality = ctrl.track_register['syn'] % len(notes)
    note = notes[scale_quality][k] + ctrl.track_register['syn'] // len(notes)
    if fix_bins:
        note *= 12 / bins_per_octave
    if chords:
        chord = norm_chord((chords[scale_quality][k % len(chords[scale_quality])]))
        quality = chord2quality.get(chord, '*')[:1].replace('M', '').replace('A', '+')
        base = 0
        if chord[0]:
            base = note + chord[0]
            note += bins_per_octave
        return note, quality, base
    return note


def sawtooth(x):  # 15x faster than scipy.signal.sawtooth which was too slow for fast transitions
    return x / np.pi % 2 - 1


def dsaw(detune_semitones=0):
    def func(x):
        output = sawtooth(x * 2 ** (-detune_semitones / 2 / bins_per_octave))
        if detune_semitones:
            output = (output + sawtooth(x * 2 ** (detune_semitones / 2 / bins_per_octave))) / 2 ** gain_normalization_exponent
        return output
    return func


def harmonizer(waveform, x, drawbar, drawbar_notes=hammond_drawbar_notes):
    if drawbar is None:
        return waveform(x)
    if isinstance(drawbar, str):
        drawbar = [int(c) for c in drawbar]
    return np.sum([v * waveform(x * 2 ** (n / bins_per_octave)) for v, n in zip(drawbar, drawbar_notes) if v], axis=0) / sum(drawbar) ** gain_normalization_exponent


@jit(cache=True)
def get_arpeggio_frames(x, lcn, t, samplerate, arpeggio_secs, save_steps, arpeggio_amp_step):
    frames = np.empty((lcn, *x.shape))
    for j in range(len(x)):
        ind = int((t + j / samplerate) / arpeggio_secs % lcn)
        for i in range(lcn):
            prev = save_steps[i] if j == 0 else frames[i, j - 1]
            frames[i, j] = min(prev + arpeggio_amp_step, 1) if i == ind else max(prev - arpeggio_amp_step, 0)
    return frames


def chord_arp(waveform=np.sin, chords=(0,), seventh=False, drawbars=None, drawbar_notes=hammond_drawbar_notes, arpeggio_order=1, arpeggio_secs=None, arpeggio_amp_step=1, samplerate=44100, **kwargs):
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    chords, drawbars = fix_chords(chords, drawbars)
    chords = [trim_chord(chord_for_quality[track % len(chord_for_quality)], seventh=seventh)[::arpeggio_order] for chord_for_quality in chords]
    save_steps = []
    prev_lcn = 0

    def func(x):
        nonlocal save_steps, prev_lcn
        chord_for_quality = chords[ctrl.track_register['syn'] % len(chords)]
        lcn = len(chord_for_quality)
        if save_steps is None or prev_lcn != lcn:
            if lcn > prev_lcn:
                save_steps += [0] * (lcn - prev_lcn)
            else:
                del save_steps[lcn:]
            prev_lcn = lcn
        if arpeggio_secs:  # note: requires high CPU settings otherwise you get clicks
            frames = get_arpeggio_frames(x, lcn, time(), samplerate, arpeggio_secs, save_steps, arpeggio_amp_step)
            for i in range(lcn):
                save_steps[i] = frames[i][-1]
        else:
            frames = [1] * lcn
        output = np.sum([frames[i] * harmonizer(waveform, x * 2 ** (n / bins_per_octave), drawbars[ctrl.transport_register['syn'] % len(drawbars)], drawbar_notes=drawbar_notes) for i, n in enumerate(chord_for_quality) if np.any(frames[i])], axis=0)
        if output.shape != x.shape:
            output = np.zeros_like(x)
        elif not arpeggio_secs:
            output /= lcn ** gain_normalization_exponent
        return output
    return func


def get_windowsize(windowsize_secs, samplerate):
    # make sure that windowsize is even and larger than 16
    windowsize = int(windowsize_secs * samplerate)
    if windowsize < 16:
        windowsize = 16
    while True:
        n = windowsize
        while (n % 2) == 0:
            n /= 2
        while (n % 3) == 0:
            n /= 3
        while (n % 5) == 0:
            n /= 5
        if n < 2:
            break
        windowsize += 1
    return windowsize // 2 * 2


def get_slice_len(sample, slice_secs, samplerate, windowsize=None, advance_factor=0, elongate_steps=None, elongate_factor=0, extend_reversal=False, smart_skipping=False, no_roll=False, return_elongate_steps=False):
    if windowsize and not advance_factor:
        if return_elongate_steps:
            return windowsize, None
        return windowsize
    sample_len = sample.shape[-1]
    if slice_secs is None:
        slice_len = sample_len
        slice_secs = slice_len / samplerate
    else:
        if extend_reversal:
            slice_secs = abs(slice_secs)
        slice_len = slice_secs * samplerate
    slice_len = round(slice_len)
    windowsize = windowsize or round(samplerate / 100)
    if slice_len > 0 or extend_reversal:
        slice_len = max(windowsize, min(slice_len, sample_len))
    else:
        slice_len = max(-sample_len, min(slice_len, -windowsize))
    if not elongate_steps or not elongate_factor:
        if return_elongate_steps:
            return int(slice_len), None
        return int(slice_len)

    step_len = abs(slice_len) * elongate_factor
    neg_slice_lens = []
    if not extend_reversal:
        slice_len = abs(slice_len)
        neg_slice_lens = list(np.arange(-slice_len, -sample_len, -step_len))[::-1]
        neg_slice_lens += list(np.arange(-slice_len, -windowsize if smart_skipping else 0, step_len))[1:]
        if not neg_slice_lens or round(neg_slice_lens[0]) != -sample_len:
            neg_slice_lens.insert(0, -sample_len)
        if smart_skipping and round(neg_slice_lens[-1]) != -windowsize:
            neg_slice_lens.append(-windowsize)
    pos_slice_lens = list(np.arange(slice_len, windowsize if smart_skipping else 0, -step_len))[::-1]
    pos_slice_lens += list(np.arange(slice_len, sample_len, step_len))[1:]
    if not pos_slice_lens or round(pos_slice_lens[-1]) != sample_len:
        pos_slice_lens.append(sample_len)
    if smart_skipping and round(pos_slice_lens[0]) != windowsize:
        pos_slice_lens.insert(0, windowsize)
    slice_lens = neg_slice_lens + pos_slice_lens
    index_shift = slice_lens.index(slice_len * int(np.sign(slice_secs)))
    index = index_shift + elongate_steps
    if no_roll:
        index = max(0, min(index, len(slice_lens) - 1))
    else:
        index %= len(slice_lens)
    slice_len = int(round(slice_lens[index]))
    if slice_len < 0:
        slice_len = min(slice_len, -windowsize)
    else:
        slice_len = max(slice_len, windowsize)
    if return_elongate_steps:
        return slice_len, index - index_shift
    return slice_len


def slice_scrub_bend(elongate_steps, ctrl, slice_len, sample, slice_secs, samplerate, elongate_factor, extend_reversal, sample_len_for_slicing, max_scrub_secs, pos, scrub_knob, track, loop_smp, pitch_knob, shifted, notes, note, freqs=None, windowsize=None, advance_factor=0, smart_skipping=False):
    if elongate_steps != ctrl.track_register['smp']:
        elongate_steps = ctrl.track_register['smp']
        slice_len = get_slice_len(sample, slice_secs, samplerate, windowsize=windowsize, advance_factor=advance_factor, elongate_steps=elongate_steps, elongate_factor=elongate_factor, extend_reversal=extend_reversal, smart_skipping=smart_skipping)
        if sample_len_for_slicing is None:
            initial_slice_len = slice_len
            if elongate_steps:
                initial_slice_len = get_slice_len(sample, slice_secs, samplerate, windowsize=windowsize, advance_factor=advance_factor)
            sample_len_for_slicing = sample.shape[-1] - initial_slice_len
        pos = 0
        scrub_knob = None
    if scrub_knob != ctrl.get_knob(track, mode='smp-scrub'):
        scrub_knob = ctrl.get_knob(track, mode='smp-scrub')
        scrub_len = sample.shape[-1]
        if max_scrub_secs:
            scrub_len = min(scrub_len, round(max_scrub_secs * samplerate))
        global_pos = max(0, min(int(scrub_knob * scrub_len + ctrl.relative_track(track) * sample_len_for_slicing), sample_len_for_slicing))
        loop_smp = sample[..., global_pos:global_pos + abs(slice_len)]
        if slice_len < 0:
            loop_smp = loop_smp[..., ::-1]
        if extend_reversal and (not windowsize or advance_factor):
            loop_smp = np.hstack((loop_smp, loop_smp[..., ::-1]))
        freqs = None
        pitch_knob = None
    if pitch_knob != ctrl.get_knob(track, mode='smp-pitch'):
        pitch_knob = ctrl.get_knob(track, mode='smp-pitch')
        shifted = None
    if ctrl.transport.get('set'):
        new_note = get_note_and_chord(ctrl, track, notes)
        if note != new_note:
            note = new_note
            shifted = None
    elif 'set' in ctrl.transport:
        note = None
        shifted = None
    return elongate_steps, slice_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, note, windowsize, freqs


def loop(notes=None, max_bend_semitones=bins_per_octave, slice_secs=0.25, elongate_factor=0.05, max_scrub_secs=None, extend_reversal=False, samplerate=44100, mono=True, **kwargs):
    # we currently use pysinewave which is (possibly duplicated) mono, so have to convert result to mono
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    sample = kwargs['sample']
    smart_skipping = True
    if isinstance(sample, list):
        smart_skipping = all(s.shape[-1] == sample[0].shape[-1] for s in sample[1:])
        sample = sample[track]
        slice_secs = None
    channels = len(sample.shape)

    elongate_steps = None
    slice_len = None
    sample_len_for_slicing = None
    pos = None
    scrub_knob = None
    loop_smp = None
    pitch_knob = None
    shifted = None
    note = None

    def func(x):
        nonlocal elongate_steps, slice_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, note
        elongate_steps, slice_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, note, *_ = slice_scrub_bend(elongate_steps, ctrl, slice_len, sample, slice_secs, samplerate, elongate_factor, extend_reversal, sample_len_for_slicing, max_scrub_secs, pos, scrub_knob, track, loop_smp, pitch_knob, shifted, notes, note, smart_skipping=smart_skipping)
        if shifted is None:
            shifted = loop_smp
            if pitch_knob:
                shifted = [librosa.effects.pitch_shift(smp, samplerate, pitch_knob * max_bend_semitones, bins_per_octave=bins_per_octave) for smp in (loop_smp if channels > 1 else [loop_smp])]
                if channels > 1:
                    shifted = np.asarray(shifted)
                else:
                    shifted = shifted[0]
            if mono and channels > 1:
                shifted = librosa.to_mono(shifted)

        output = shifted[..., int(pos):int(pos) + x.shape[-1]]
        while output.shape[-1] < x.shape[-1]:
            output = np.hstack((output, shifted[..., :x.shape[-1]]))
        pos = (pos + x.shape[-1]) % shifted.shape[-1]
        return output[..., :x.shape[-1]]
    return func


def paulstretch(notes=None, max_bend_semitones=bins_per_octave, windowsize_secs=0.25, slice_secs=0.5, elongate_factor=0.05, max_scrub_secs=None, advance_factor=0, extend_reversal=False, samplerate=44100, mono=True, **kwargs):
    # adapted from https://github.com/paulnasca/paulstretch_python, https://github.com/paulnasca/paulstretch_cpp
    # we currently use pysinewave which is (possibly duplicated) mono, so have to convert result to mono
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    sample = kwargs['sample']
    smart_skipping = True
    if isinstance(sample, list):
        smart_skipping = all(s.shape[-1] == sample[0].shape[-1] for s in sample[1:])
        sample = sample[track]
        slice_secs = None
    channels = len(sample.shape)

    elongate_steps = None
    slice_len = None
    sample_len_for_slicing = None
    pos = None
    scrub_knob = None
    loop_smp = None
    pitch_knob = None
    shifted = None
    note = None
    freqs = None

    windowsize = get_windowsize(windowsize_secs, samplerate)
    window = (1 - np.linspace(-1, 1, windowsize) ** 2) ** 1.25
    old_windowed_buf = np.zeros((channels if not mono else 1, windowsize)).squeeze()
    later = old_windowed_buf[..., :0]

    def func(x):
        nonlocal elongate_steps, slice_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, note, windowsize, freqs, old_windowed_buf, later
        elongate_steps, slice_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, note, windowsize, freqs = slice_scrub_bend(elongate_steps, ctrl, slice_len, sample, slice_secs, samplerate, elongate_factor, extend_reversal, sample_len_for_slicing, max_scrub_secs, pos, scrub_knob, track, loop_smp, pitch_knob, shifted, notes, note, freqs=freqs, windowsize=windowsize, advance_factor=advance_factor, smart_skipping=smart_skipping)
        while later.shape[-1] < x.shape[-1]:
            if freqs is None or advance_factor:
                # get the windowed buffer
                buf = loop_smp[..., int(pos):int(pos) + windowsize]
                if buf.shape[-1] < windowsize:
                    buf = np.hstack([buf, np.zeros((channels, windowsize - buf.shape[-1])).squeeze()])
                buf = buf * window

                # get the amplitudes of the frequency components and discard the phases
                freqs = abs(np.fft.rfft(buf))
                shifted = None

            if shifted is None:
                shifted = freqs
                if pitch_knob or ctrl.transport.get('set') and note is not None:
                    shifted = np.zeros_like(freqs)
                    pitch_shift = pitch_knob * max_bend_semitones
                    if ctrl.transport.get('set') and note is not None:
                        pitch_shift += note - np.log2(np.fft.rfftfreq(freqs.shape[-1], d=1/samplerate)[(np.argmax(freqs[..., 1:]) + 1) % freqs.shape[-1]] / BASE_C_FREQUENCY) * bins_per_octave
                    rap = 2 ** (pitch_shift / bins_per_octave)
                    if rap < 1:
                        for i in range(freqs.shape[-1]):
                            shifted[..., int(i * rap)] += freqs[..., i]
                    else:
                        for i in range(freqs.shape[-1]):
                            shifted[..., i] = freqs[..., int(i / rap)]

            # randomize the phases by multiplication with a random complex number with modulus=1
            ph = rng.uniform(0, 2 * np.pi, (channels, freqs.shape[-1])).squeeze() * 1j
            rand_freqs = shifted * np.exp(ph)

            # do the inverse FFT
            buf = np.fft.irfft(rand_freqs)

            if mono and channels > 1:
                buf = librosa.to_mono(buf)

            # window again the output buffer
            buf *= window

            # overlap-add the output
            output = (buf[..., :windowsize // 2] + old_windowed_buf[..., windowsize // 2:windowsize]) / np.sqrt(2) * 1.6 ** 2  # my estimated amplitude correction
            old_windowed_buf = buf

            # clamp the values to -1..1
            output = np.clip(output, -1, 1)

            later = np.hstack((later, output))

            pos = (pos + windowsize / 2 * advance_factor) % max(1, loop_smp.shape[-1] - windowsize)

        now = later[..., :x.shape[-1]]
        later = later[..., x.shape[-1]:]
        return now
    return func


dsaw.is_func_factory = True
chord_arp.is_func_factory = True
loop.is_func_factory = True
paulstretch.is_func_factory = True

loop.show_track_numbers = True
loop.skip_external_pitch_control = True
paulstretch.show_track_numbers = True
paulstretch.skip_external_pitch_control = True
