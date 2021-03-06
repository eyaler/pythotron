# A simple MIDI controller audiovisual monitor
### (and wannabe musical instrument)
### By Eyal Gruss
#### https://eyalgruss.com

<p align="center">
<img src="pythotron.gif" /> 
</p>


### Supported controls:
- CC MIDI input   
  - 8 sliders
  - 8 knobs
  - 8 solo/mute/record buttons
  - Transport buttons
- State/LED programmatic control:
  - solo/mute/record toggle all
  - solo/record exclusive mode
  - Slider up solo exclusive "one-finger" mode
  - Stop toggles off record button
- Software override logic:
  - Mute override all
  - Solo defeats mute mode
  - Several knob modes with memory
  - Reset knob and slider states
- OSC


### Musical instruments:
- Fader Organ:
  - Tracks = notes or samples / slices
  - Sliders, solo, mute = volume
  - Knobs = pitch bend or temporal scrub
  - "One-finger" (slider-up solo-exclusive) mode
- Live looper
  - Record = start / pause recording 
  - Stop = stop recording and clear buffer for next recording
  - Play = grab current recorded buffer and loop it / stop
  - Tracks' record-arm = Grab current recorded buffer, assign to track and loop it / revert to last synth 
- Finger Theremin [TBD]


### Synths / samplers / effects:
- Sine waves
- Detuned saw
- Chords
- Arpeggiator
- [Hammond drawbar harmonizer](https://hammondorganco.com/wp-content/uploads/2015/06/03-DRAWBARS-PERCUSSION-corrected.pdf)
- Sample slicer and looper
- [Paulstretch](http://hypermammut.sourceforge.net/paulstretch) stretch and freeze (oh yeah!)
- Pitch bending
- Autotune 


### Setup:
- This codebase has only been tested on Windows 10
- pip install -r requirements.txt
- Code defaults settings in controller.py are for KORG nanoKONTROL2
- In KORG KONTROL Editor:
  - If you have a KORG nanoKONTROL2, you can load the pythotron.nktrl2_data scene file included here
  - Otherwise:
    - Set Control Mode to CC
    - Set LED Mode to External, to allow programmatic control 
    - Set all solo/mute/record Button Behavior to Toggle
    - Set transport cycle, set, play, record Button Behavior to Toggle
    - Other transport buttons should be set to Momentary
- Otherwise, if LED Mode is Internal, change external_led_mode to: False
- Put your audio samples in the "samples" folder (dynamically read, so you can also add files while running)
  - files in that folder will be sliced to the tracks
  - files in subfolders will be cyclically mapped to the tracks 
- For MP3 support [install ffmpeg or gstreamer](https://github.com/librosa/librosa#audioread-and-mp3-support)
- Download the [rubberband](https://breakfastquay.com/rubberband) executable and add to your path
- Issues are to be expected when running inside an IDE.
  - For best compatibility run in a native terminal
  - To run in PyCharm enable: Run -> Edit Configurations -> Emulate terminal in output console


### Known issues:
- OSC interface not functional [WIP]
- Autotune not implemented for looper [WIP]
- Need a lowpass filter to reduce paulstretch hiss and improve saws
- No way to run without a MIDI controller
- No way to save and recover the controller state
- My inefficient implementation requires high CPU settings to avoid glitches and clicks (make sure your laptop is plugged in)
- Code needs to be refactored to use classes instead of function factories 
- Looper (but not Paulstretch) has significant clicks when pitch bending and scrubbing  
- Due to the currently used framework of [pysinewave](https://github.com/daviddavini/pysinewave): 
  - Controls latency is high
  - Stereo samples are collapsed to duplicated mono
  - Polyphony is implemented by multiple stream which may not be supported on all platforms


> I began this because I could not find an existing easy plug-and-play visual or audial monitor for my controller. 
But if it was not evident, I am using this as a platform to learn more about music theory, digital audio and sound synthesis, 
thinking about new "metaphors" to allow me, as a non-musician, to create and perform in the audio domain, and working on developing this into a performative musical instrument.
In the famous words of Feynman: "What I cannot code in Python, I do not understand."


#### Ride the tide: [a_saucerful_of_secrets_celestial_voices.txt](https://github.com/eyaler/pythotron/blob/main/a_saucerful_of_secrets_celestial_voices.txt)


#### Press "h" for help
