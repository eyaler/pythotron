import librosa
from numba import jit
import numpy as np
import time


def sawtooth(x):  # 15x faster than scipy.signal.sawtooth which was too slow for fast transitions
    return np.mod(x, 2 * np.pi) / np.pi - 1


def dsaw(detune_semitones=0):
    def func(x):
        output = sawtooth(x * 2 ** (-detune_semitones / 2 / 12))
        if detune_semitones:
            output = (output + sawtooth(x * 2 ** (detune_semitones / 2 / 12))) / 2  # # not normalizing with sqrt to avoid clipping
        return output
    return func


hammond_drawbar_notes = (-12, 7, 0, 12, 19, 24, 28, 31, 36)


def harmonizer(waveform, x, drawbar, drawbar_notes=hammond_drawbar_notes):
    if drawbar is None:
        return waveform(x)
    if isinstance(drawbar, str):
        drawbar = [int(c) for c in drawbar]
    return np.sum([v * waveform(x * 2 ** (n / 12)) for v, n in zip(drawbar, drawbar_notes) if v], axis=0) / sum(drawbar)  # not normalizing with sqrt to avoid clipping


@jit(cache=True)
def get_arpeggio_frames(x, lcn, t, samplerate, arpeggio_secs, save_steps, arpeggio_amp_step):
    frames = np.empty((lcn, *x.shape))
    for j in range(len(x)):
        ind = int((t + j / samplerate) / arpeggio_secs % lcn)
        for i in range(lcn):
            prev = save_steps[i] if j == 0 else frames[i, j - 1]
            frames[i, j] = min(prev + arpeggio_amp_step, 1) if i == ind else max(prev - arpeggio_amp_step, 0)
    return frames


def chord(waveform=np.sin, chord_notes=(0,), seventh=False, drawbars=None, drawbar_notes=hammond_drawbar_notes, arpeggio_order=1, arpeggio_secs=None, arpeggio_amp_step=1, samplerate=44100, **kwargs):
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    if not isinstance(chord_notes[0], (list, tuple)):
        chord_notes = [chord_notes]
    if not isinstance(chord_notes[0][0], (list, tuple)):
        chord_notes = [chord_notes]
    if not isinstance(drawbars, (list, tuple)) or not hasattr(drawbars[-1], '__len__'):
        drawbars = [drawbars]
    chord_notes = [chord_for_quality[track % len(chord_for_quality)][:None if seventh else 3][::arpeggio_order] for chord_for_quality in chord_notes]
    save_steps = []
    prev_lcn = 0

    def func(x):
        nonlocal save_steps, prev_lcn
        chord_for_quality = chord_notes[ctrl.track_register['syn'] % len(chord_notes)]
        lcn = len(chord_for_quality)
        if save_steps is None or prev_lcn != lcn:
            if lcn > prev_lcn:
                save_steps += [0] * (lcn - prev_lcn)
            else:
                del save_steps[lcn:]
            prev_lcn = lcn
        if arpeggio_secs:  # note: requires high CPU settings otherwise you get clicks
            frames = get_arpeggio_frames(x, lcn, time.time(), samplerate, arpeggio_secs, save_steps, arpeggio_amp_step)
            for i in range(lcn):
                save_steps[i] = frames[i][-1]
        else:
            frames = [1] * lcn
        output = np.sum([frames[i] * harmonizer(waveform, x * 2 ** (n / 12), drawbars[ctrl.transport_register['syn'] % len(drawbars)], drawbar_notes=drawbar_notes) for i, n in enumerate(chord_for_quality) if np.any(frames[i])], axis=0)
        if output.shape != x.shape:
            output = np.zeros_like(x)
        elif not arpeggio_secs:
            output /= lcn  # not normalizing with sqrt to avoid clipping
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


def get_slice_len(sample, slice_secs, samplerate, windowsize=None, advance_factor=0, elongate_step=0, elongate_factor=0, extend_reversal=False):
    if windowsize and not advance_factor:
        return windowsize
    sample_len = sample.shape[-1]
    if slice_secs is None:
        sssr = sample_len
    else:
        sssr = abs(slice_secs) * samplerate
    windowsize = windowsize or round(samplerate / 100)
    rsssr = max(windowsize, min(round(sssr), sample_len))
    if not elongate_step or not elongate_factor:
        return int(rsssr)
    step = sssr * elongate_factor
    slice_lens_1 = []
    slice_lens_2 = []
    if not extend_reversal:
        slice_lens_1 = list(np.arange(-rsssr, -sample_len, -step))[::-1]
        if round(slice_lens_1[0]) != -sample_len:
            slice_lens_1.insert(0, -sample_len)
        slice_lens_2 = list(np.rint(np.arange(-rsssr, -windowsize, step)))[1:]
        if round(slice_lens_2[-1]) != -windowsize:
            slice_lens_2.append(-windowsize)
    slice_lens_3 = list(np.rint(np.arange(rsssr, windowsize, -step)))[::-1]
    if round(slice_lens_3[0]) != windowsize:
        slice_lens_3.insert(0, windowsize)
    slice_lens_4 = list(np.rint(np.arange(rsssr, sample_len, step)))[1:]
    if round(slice_lens_4[-1]) != sample_len:
        slice_lens_4.append(sample_len)
    slice_lens = slice_lens_1 + slice_lens_2 + slice_lens_3 + slice_lens_4
    index_shift = len(slice_lens_1) if slice_secs < 0 and not extend_reversal else len(slice_lens) - len(slice_lens_4)
    return int(round(slice_lens[(index_shift - 1 + elongate_step) % len(slice_lens)]))


def slice_scrub_bend(elongate_step, ctrl, slice_len, sample, slice_secs, samplerate, elongate_factor, extend_reversal, scrub_len, sample_len_for_slicing, max_scrub_secs, pos, scrub_knob, track, loop_smp, pitch_knob, shifted, freqs=None, windowsize=None, advance_factor=0):
    if elongate_step != ctrl.track_register['smp']:
        elongate_step = ctrl.track_register['smp']
        slice_len = get_slice_len(sample, slice_secs, samplerate, windowsize=windowsize, advance_factor=advance_factor, elongate_step=elongate_step, elongate_factor=elongate_factor, extend_reversal=extend_reversal)
        if scrub_len is None:
            scrub_len = sample.shape[-1] - get_slice_len(sample, slice_secs, samplerate, windowsize=windowsize, advance_factor=advance_factor)
            sample_len_for_slicing = scrub_len
            if max_scrub_secs:
                scrub_len = min(scrub_len, round(max_scrub_secs * samplerate))
        pos = 0
        scrub_knob = None
    if scrub_knob != ctrl.get_knob(track, mode='smp-scrub'):
        scrub_knob = ctrl.get_knob(track, mode='smp-scrub')
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
    return elongate_step, slice_len, scrub_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, freqs


def loop(max_bend_semitones=12, slice_secs=0.25, elongate_factor=0.1, max_scrub_secs=None, extend_reversal=False, samplerate=44100, mono=True, **kwargs):
    # we currently use pysinewave which is (possibly duplicated) mono, so have to convert result to mono
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    sample = kwargs['sample']

    channels = len(sample.shape)

    elongate_step = None
    slice_len = None
    scrub_len = None
    sample_len_for_slicing = None
    pos = None
    scrub_knob = None
    loop_smp = None
    pitch_knob = None
    shifted = None

    def func(x):
        nonlocal elongate_step, slice_len, scrub_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted
        elongate_step, slice_len, scrub_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, _ = slice_scrub_bend(elongate_step, ctrl, slice_len, sample, slice_secs, samplerate, elongate_factor, extend_reversal, scrub_len, sample_len_for_slicing, max_scrub_secs, pos, scrub_knob, track, loop_smp, pitch_knob, shifted)
        if shifted is None:
            shifted = loop_smp
            if pitch_knob:
                shifted = [librosa.effects.pitch_shift(smp, samplerate, pitch_knob * max_bend_semitones) for smp in (loop_smp if channels > 1 else [loop_smp])]
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


rng = np.random  #.Generator(np.random.MT19937())  # Mersenne Twister


def paulstretch(max_bend_semitones=12, windowsize_secs=0.25, slice_secs=0.5, elongate_factor=0.1, max_scrub_secs=None, advance_factor=0, extend_reversal=False, samplerate=44100, mono=True, **kwargs):
    # adapted from https://github.com/paulnasca/paulstretch_python, https://github.com/paulnasca/paulstretch_cpp
    # we currently use pysinewave which is (possibly duplicated) mono, so have to convert result to mono
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    sample = kwargs['sample']

    windowsize = get_windowsize(windowsize_secs, samplerate)
    half_windowsize = windowsize // 2

    channels = len(sample.shape)

    # create Window window
    window = (1 - np.linspace(-1, 1, windowsize) ** 2) ** 1.25

    elongate_step = None
    slice_len = None
    scrub_len = None
    sample_len_for_slicing = None
    pos = None
    scrub_knob = None
    loop_smp = None
    pitch_knob = None
    shifted = None
    freqs = None
    old_windowed_buf = np.zeros((channels if not mono else 1, windowsize)).squeeze()
    later = old_windowed_buf[..., :0]

    def func(x):
        nonlocal elongate_step, slice_len, scrub_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, freqs, old_windowed_buf, later
        elongate_step, slice_len, scrub_len, sample_len_for_slicing, pos, scrub_knob, loop_smp, pitch_knob, shifted, freqs = slice_scrub_bend(elongate_step, ctrl, slice_len, sample, slice_secs, samplerate, elongate_factor, extend_reversal, scrub_len, sample_len_for_slicing, max_scrub_secs, pos, scrub_knob, track, loop_smp, pitch_knob, shifted, freqs=freqs, windowsize=windowsize, advance_factor=advance_factor)
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
                if pitch_knob:
                    shifted = np.zeros_like(freqs)
                    rap = 2 ** (pitch_knob * max_bend_semitones / 12)
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
            output = (buf[..., :half_windowsize] + old_windowed_buf[..., half_windowsize:windowsize]) / np.sqrt(2) * 1.6 ** 2  # my estimated amplitude correction
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
chord.is_func_factory = True
loop.is_func_factory = True
paulstretch.is_func_factory = True

loop.show_track_numbers = True
loop.skip_external_pitch_control = True
paulstretch.show_track_numbers = True
paulstretch.skip_external_pitch_control = True
