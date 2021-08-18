# A simple MIDI contoller audiovisual monitor

![GUI](pythotron.webp)

Supports:
- CC MIDI input   
  - 8 sliders
  - 8 knobs
  - 8 solo/mute/record buttons
- State/LED programmatic control:
  - solo/mute/record toggle all
  - solo/record exclusive mode
- Software override options:
  - mute override all
  - solo defeats mute

Setup:
- Code defaults settings are for KORG nanoKONTROL2
- In KORG KONTROL Editor:
  - Set Control Mode to CC
  - Set LED Mode to External, to allow programmatic control 
  - Set all solo/mute/record Button Behavior to Toggle
- Otherwise, if LED Mode is Internal, change external_led_mode to: False

Press "h" for help