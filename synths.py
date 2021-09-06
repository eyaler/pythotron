import librosa
import numpy as np
import time


def sawtooth(x):  # 15x faster than scipy.signal.sawtooth which was too slow for fast transitions
    return np.mod(x, 2 * np.pi) / np.pi - 1


def dsaw(detune_semitones=0):
    def func(x):
        w = sawtooth(x * 2 ** (-detune_semitones / 2 / 12))
        if detune_semitones:
            w = (w + sawtooth(x * 2 ** (detune_semitones / 2 / 12))) / np.sqrt(2)
        return w
    return func


def chord(waveform=np.sin, chord_notes=((0, 4, 7),), arpeggio_secs=None, arpeggio_amp_step=1, samplerate=44100, **kwargs):
    track = kwargs['track']
    chord_notes = chord_notes[track % len(chord_notes)]
    lcn = len(chord_notes)
    save_steps = [0] * lcn

    def func(x):
        if arpeggio_secs:  # note: requires high CPU settings otherwise you get clicks
            frames = [np.empty_like(x) for _ in range(lcn)]
            t = time.time()
            for j in range(len(x)):
                ind = int((t + j / samplerate) / arpeggio_secs % lcn)
                for i in range(lcn):
                    prev = save_steps[i] if j == 0 else frames[i][j - 1]
                    frames[i][j] = min(prev + arpeggio_amp_step, 1) if i == ind else max(prev - arpeggio_amp_step, 0)
            for i in range(lcn):
                save_steps[i] = frames[i][-1]
        else:
            frames = [1] * lcn
        w = sum(frames[i] * waveform(x * 2 ** (n / 12)) for i, n in enumerate(chord_notes))
        if not arpeggio_secs:
            w /= np.sqrt(lcn)
        return w
    return func


def calc_lens(sample, slice_secs, max_scrub_secs, extend_reversal, samplerate, windowsize=None, advance_factor=0):
    sample_len = sample.shape[-1]
    if windowsize and not advance_factor:
        slice_len = windowsize
    elif slice_secs:
        slice_len = round(slice_secs * samplerate)
        if windowsize:
            slice_len = max(slice_len, windowsize)
        slice_len = min(slice_len, sample_len)
    else:
        slice_len = sample_len
    scrub_len = sample_len - slice_len
    if max_scrub_secs:
        scrub_len = min(scrub_len, round(max_scrub_secs * samplerate))
    loop_len = slice_len * (1 + extend_reversal)
    if windowsize:
        loop_len -= windowsize
    loop_len = max(1, loop_len)
    return slice_len, scrub_len, loop_len


def slice_and_scrub(sample, slice_len, knob, scrub_len, rel_track, loop_len, old_global_pos, extend_reversal, pos, minimize_clicks=False):
    sample_len_for_slicing = sample.shape[-1] - slice_len
    global_pos = max(0, min(int(knob * scrub_len + rel_track * sample_len_for_slicing), sample_len_for_slicing))
    loop_smp = sample[..., global_pos:global_pos + slice_len]
    if old_global_pos is not None and minimize_clicks:
        diff = global_pos - old_global_pos
        if not extend_reversal or pos < slice_len:
            pos = max(0, min((pos - diff), slice_len - 1))
        else:
            pos = max(slice_len, min((pos + diff), loop_len - 1))
    if extend_reversal:
        loop_smp = np.hstack((loop_smp, loop_smp[..., ::-1]))
    return global_pos, loop_smp, pos


def loop(slice_secs=0.25, max_scrub_secs=None, extend_reversal=False, samplerate=44100, mono=True, **kwargs):
    # we currently use pysinewave which is (possibly duplicated) mono, so have to convert result to mono
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    sample = kwargs['sample']

    if mono:
        sample = librosa.to_mono(sample)

    slice_len, scrub_len, loop_len = calc_lens(sample, slice_secs, max_scrub_secs, extend_reversal, samplerate)

    last_knob = None
    loop_smp = None
    old_global_pos = None
    pos = 0

    def func(x):
        nonlocal last_knob, loop_smp, old_global_pos, pos
        knob = ctrl.get_knob(track)
        if knob != last_knob:
            last_knob = knob
            global_pos, loop_smp, pos = slice_and_scrub(sample, slice_len, knob, scrub_len, ctrl.relative_track(track), loop_len, old_global_pos, extend_reversal, pos, minimize_clicks=True)
            old_global_pos = global_pos

        output = loop_smp[..., int(pos):int(pos) + x.shape[-1]]
        while output.shape[-1] < x.shape[-1]:
            output = np.hstack((output, loop_smp[..., :x.shape[-1]]))
        pos = (pos + x.shape[-1]) % loop_len
        return output[..., :x.shape[-1]]
    return func


def paulstretch(max_shift_semitones=12, windowsize_secs=0.25, slice_secs=0.5, max_scrub_secs=None, advance_factor=0, extend_reversal=False, samplerate=44100, mono=True, **kwargs):
    # adapted from https://github.com/paulnasca/paulstretch_python
    # we currently use pysinewave which is (possibly duplicated) mono, so have to convert result to mono
    track = kwargs['track']
    ctrl = kwargs['ctrl']
    sample = kwargs['sample']

    def optimize_windowsize(n):
        orig_n = n
        while True:
            n = orig_n
            while (n % 2) == 0:
                n /= 2
            while (n % 3) == 0:
                n /= 3
            while (n % 5) == 0:
                n /= 5

            if n < 2:
                break
            orig_n += 1
        return orig_n

    channels = len(sample.shape)

    # make sure that windowsize is even and larger than 16
    windowsize = int(windowsize_secs * samplerate)
    if windowsize < 16:
        windowsize = 16
    windowsize = optimize_windowsize(windowsize)
    windowsize = windowsize // 2 * 2
    half_windowsize = windowsize // 2

    # create Window window
    window = (1 - np.linspace(-1, 1, windowsize) ** 2) ** 1.25

    slice_len, scrub_len, loop_len = calc_lens(sample, slice_secs, max_scrub_secs, extend_reversal, samplerate, windowsize=windowsize, advance_factor=advance_factor)

    last_knob = None
    old_global_pos = None
    pos = 0
    loop_smp = None
    freqs = None
    shifted_freqs = None
    old_windowed_buf = np.zeros((channels if not mono else 1, windowsize)).squeeze()
    later = old_windowed_buf[..., :0]

    def func(x):
        nonlocal last_knob, old_global_pos, pos, loop_smp, freqs, shifted_freqs, old_windowed_buf, later
        knob = ctrl.get_knob(track)
        scrub_mode = 'cycle' in ctrl.transport and ctrl.transport['cycle']
        if knob != last_knob:
            last_knob = knob
            if loop_smp is None or scrub_mode:
                global_pos, loop_smp, pos = slice_and_scrub(sample, slice_len, knob, scrub_len, ctrl.relative_track(track), loop_len, old_global_pos, extend_reversal and advance_factor, pos)
                old_global_pos = global_pos
                freqs = None
            shifted_freqs = None

        while later.shape[-1] < x.shape[-1]:
            if freqs is None or advance_factor:
                # get the windowed buffer
                buf = loop_smp[..., int(pos):int(pos) + windowsize]
                if buf.shape[-1] < windowsize:
                    buf = np.hstack([buf, np.zeros((channels, windowsize - buf.shape[-1])).squeeze()])
                buf = buf * window

                # get the amplitudes of the frequency components and discard the phases
                freqs = abs(np.fft.rfft(buf))
                shifted_freqs = None

            if shifted_freqs is None:
                shifted_freqs = freqs
                if not scrub_mode and knob:
                    shifted_freqs = np.zeros_like(freqs)
                    rap = 2 ** (knob * max_shift_semitones / 12)
                    if rap < 1:
                        for i in range(len(freqs)):
                            i2 = int(i * rap)
                            if i2 >= len(freqs):
                                break
                            shifted_freqs[i2] += freqs[i]
                    else:
                        rap = 1 / rap
                        for i in range(len(freqs)):
                            i2 = int(i * rap)
                            if i2 < len(freqs):
                                shifted_freqs[i] = freqs[i2]

            # randomize the phases by multiplication with a random complex number with modulus=1
            ph = np.random.uniform(0, 2 * np.pi, (channels, freqs.shape[-1])) * 1j
            rand_freqs = shifted_freqs * np.exp(ph)

            # do the inverse FFT
            buf = np.fft.irfft(rand_freqs)

            if mono:
                buf = librosa.to_mono(buf.squeeze())

            # window again the output buffer
            buf *= window

            # overlap-add the output
            output = (buf[..., :half_windowsize] + old_windowed_buf[..., half_windowsize:windowsize]) / np.sqrt(2) * 1.6 ** 2  # my estimated amplitude correction
            old_windowed_buf = buf

            # clamp the values to -1..1
            output = np.clip(output, -1, 1)

            later = np.hstack((later, output))

            pos = (pos + windowsize / 2 * advance_factor) % loop_len

        now = later[..., :x.shape[-1]]
        later = later[..., x.shape[-1]:]
        return now
    return func


dsaw.is_func_factory = True
chord.is_func_factory = True
loop.is_func_factory = True
paulstretch.is_func_factory = True

loop.show_track_numbers = True
loop.skip_pitch_control = True
paulstretch.show_track_numbers = True
paulstretch.skip_pitch_control = True