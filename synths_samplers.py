import numpy as np
import time
import librosa


def func_factory(f):
    f.is_func_factory = True
    return f


def show_track_numbers(f):
    f.show_track_numbers = True
    return f


def sawtooth(x):  # 15x faster than scipy.signal.sawtooth which was too slow for fast transitions
    return np.mod(x, 2 * np.pi) / np.pi - 1


@func_factory
def dsaw(detune=0):
    def func(x):
        w = sawtooth(x * 2 ** (-detune / 2 / 12))
        if detune:
            w = (w + sawtooth(x * 2 ** (detune / 2 / 12))) / 2
        return w
    return func


@func_factory
def chord(waveform=np.sin, chord_notes=((0, 4, 7),), dt=None, dv=1, samplerate=44100, **kwargs):
    track = kwargs['track']
    chord_notes = chord_notes[track % len(chord_notes)]
    save_steps = [0] * len(chord_notes)  # note: when this is used we must instantiate a new closure for each track + requires high CPU settings otherwise you get clicks

    def func(x):
        if dt:
            frames = [np.empty_like(x) for _ in range(len(chord_notes))]
            t = time.time()
            for j in range(len(x)):
                ind = int((t + j / samplerate) / dt % len(chord_notes))
                for i in range(len(chord_notes)):
                    prev = save_steps[i] if j == 0 else frames[i][j - 1]
                    frames[i][j] = min(prev + dv, 1) if i == ind else max(prev - dv, 0)
            for i in range(len(chord_notes)):
                save_steps[i] = frames[i][-1]
        else:
            frames = [1] * len(chord_notes)
        w = sum(frames[i] * waveform(x * 2 ** (n / 12)) for i, n in enumerate(chord_notes))
        if not dt:
            w /= len(chord_notes)
        return w
    return func


@func_factory
@show_track_numbers
def loop(reverse=True, mono=True, **kwargs):
    # we currently use pysinewave which is (possibly duplicated) mono
    smp = kwargs['sample']
    if mono:
        smp = librosa.to_mono(smp)
    if reverse:
        smp = np.hstack((smp, smp[..., ::-1]))
    pos = 0

    def func(x):
        nonlocal pos
        output = smp[..., pos:pos + x.shape[-1]]
        while output.shape[-1] < x.shape[-1]:
            output = np.hstack((output, smp[..., :x.shape[-1]]))
        pos = (pos + x.shape[-1]) % smp.shape[-1]
        return output[..., :x.shape[-1]]
    return func


@func_factory
@show_track_numbers
def freeze(windowsize_seconds=0.25, amp_factor=1, samplerate=44100, mono=True, **kwargs):  # from https://github.com/paulnasca/paulstretch_python
    # we currently use pysinewave which is (possibly duplicated) mono
    smp = kwargs['sample']

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

    nchannels = len(smp.shape)

    # make sure that windowsize is even and larger than 16
    windowsize = int(windowsize_seconds * samplerate)
    if windowsize < 16:
        windowsize = 16
    windowsize = optimize_windowsize(windowsize)
    windowsize = int(windowsize / 2) * 2
    half_windowsize = int(windowsize / 2)

    # correct the end of the smp
    nsamples = smp.shape[-1]
    end_size = int(samplerate * 0.05)
    if end_size < 16:
        end_size = 16

    smp[..., nsamples - end_size:nsamples] *= np.linspace(1, 0, end_size)

    # create Window window
    window = pow(1 - pow(np.linspace(-1, 1, windowsize), 2), 1.25)

    old_windowed_buf = np.zeros((nchannels if not mono else 1, windowsize)).squeeze()

    # get the windowed buffer
    buf = smp[..., :windowsize]
    if buf.shape[-1] < windowsize:
        buf = np.hstack([buf, np.zeros((nchannels, windowsize - buf.shape[-1])).squeeze()])
    buf = buf * window

    # get the amplitudes of the frequency components and discard the phases
    freqs = abs(np.fft.rfft(buf))

    later = old_windowed_buf[..., :0]

    def func(x):
        nonlocal old_windowed_buf, later
        while later.shape[-1] < x.shape[-1]:
            # randomize the phases by multiplication with a random complex number with modulus=1
            ph = np.random.uniform(0, 2 * np.pi, (nchannels, freqs.shape[-1])) * 1j
            rand_freqs = freqs * np.exp(ph)

            # do the inverse FFT
            buf = np.fft.irfft(rand_freqs)

            if mono:
                buf = librosa.to_mono(buf.squeeze())

            # window again the output buffer
            buf *= window

            # overlap-add the output
            output = buf[..., :half_windowsize] + old_windowed_buf[..., half_windowsize:windowsize]
            old_windowed_buf = buf

            # clamp the values to -1..1
            output = np.clip(output, -1, 1)

            later = np.hstack((later, output))

        now = later[..., :x.shape[-1]]
        later = later[..., x.shape[-1]:]
        return now * amp_factor
    return func
