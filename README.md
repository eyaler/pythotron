# A simple MIDI controller audiovisual monitor

![GUI](pythotron.webp)

Supported controls:
- CC MIDI input   
  - 8 sliders
  - 8 knobs
  - 8 solo/mute/record buttons
  - Transport buttons
- State/LED programmatic control:
  - solo/mute/record toggle all
  - solo/record exclusive mode
- Software override options:
  - mute override all
  - solo defeats mute

Musical metaphors:
  - Fader Organ:
    - tracks = notes
    - slider = volume
    - knob = pitch shift
    - track rewind/forward = semitone scale shift
    - marker rewind/forward = change waveform
    - rewind/forward = change sample
  - Finger Theremin (TBD)
  - Phased Looper (TBD)

Sound effects:
  - Sine waves
  - Chords
  - Arpeggio 
  - Detuned saw
  - Sample slicer +
    - Looper
    - [Paulstretch](http://hypermammut.sourceforge.net/paulstretch) freeze (oh yes)
  
Setup:
- pip install -r requirements.txt
- Code defaults settings are for KORG nanoKONTROL2
- In KORG KONTROL Editor:
  - Either load the pythotron.nktrl2_data scene file included here, or:
  - Set Control Mode to CC
  - Set LED Mode to External, to allow programmatic control 
  - Set all solo/mute/record Button Behavior to Toggle
  - Set transport play/record Button Behavior to Toggle
  - Other transport buttons should be set to Momentary
- Otherwise, if LED Mode is Internal, change external_led_mode to: False
- Put your audio samples in "samples" folder
- For MP3 support [install ffmpeg or gstreamer](https://github.com/librosa/librosa#audioread-and-mp3-support)

I began this because I could not find an existing easy plug-and-play visual or audial monitor for my controller. 
But if it was not evident, I am using this as a platform to learn more about music theory, audio effects and sound synthesis, 
thinking about new "metaphors" to allow me as a non-musician to create and perform in the audio domain, and working on developing this into a performative musical instrument.
In the famous words of Feynman: What I cannot code in Python, I do not understand.

Press "h" for help