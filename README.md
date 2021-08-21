# A simple MIDI contoller audiovisual monitor

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
  - Finger Theremin (TBD)
  - Phased Looper (TBD)
  
Setup:
- pip install -r requirements.txt
- Code defaults settings are for KORG nanoKONTROL2
- In KORG KONTROL Editor:
  - Set Control Mode to CC
  - Set LED Mode to External, to allow programmatic control 
  - Set all solo/mute/record Button Behavior to Toggle
  - Set transport play/record Button Behavior to Toggle
  - Other transport buttons should be set to Momentary
- Otherwise, if LED Mode is Internal, change external_led_mode to: False

Press "h" for help