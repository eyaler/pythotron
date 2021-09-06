# A simple MIDI controller audiovisual monitor

![GUI](pythotron.gif)

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

Musical instruments:
- Fader Organ:
  - tracks = notes or sample slices
  - sliders = volume
  - knobs = pitch shift or temporal scrub
- Finger Theremin (TBD)
- Phased Looper (TBD)

Synths:
- Sine waves
- Chords
- Arpeggio 
- Detuned saw
- Sampler + slicer +
  - Looper
  - [Paulstretch](http://hypermammut.sourceforge.net/paulstretch) freeze (oh yeah!) 
  - Paulstretch stretch looper
    
Setup:
- pip install -r requirements.txt
- Code defaults settings are for KORG nanoKONTROL2
- In KORG KONTROL Editor:
  - If you have a KORG nanoKONTROL2, you can load the pythotron.nktrl2_data scene file included here
  - Otherwise:
    - Set Control Mode to CC
    - Set LED Mode to External, to allow programmatic control 
    - Set all solo/mute/record Button Behavior to Toggle
    - Set transport play/record Button Behavior to Toggle
    - Other transport buttons should be set to Momentary
- Otherwise, if LED Mode is Internal, change external_led_mode to: False
- Put your audio samples in "samples" folder
- For MP3 support [install ffmpeg or gstreamer](https://github.com/librosa/librosa#audioread-and-mp3-support)

Known issues:
- Stereo samples are rendered as mono
- High CPU settings are required to avoid clicks

I began this because I could not find an existing easy plug-and-play visual or audial monitor for my controller. 
But if it was not evident, I am using this as a platform to learn more about music theory, audio effects and sound synthesis, 
thinking about new "metaphors" to allow me as a non-musician to create and perform in the audio domain, and working on developing this into a performative musical instrument.
In the famous words of Feynman: What I cannot code in Python, I do not understand.

Press "h" for help