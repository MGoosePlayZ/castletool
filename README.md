# castletool

Castletool is a command line tool for adding images and MIDI files to the Castle - Make and Play app by Monterey's Coast, Inc. (not affiliated)

### Installation

You can install Castletool by running `pip install castletool` in your terminal (Requires python). Be sure to install pillow, mido, ffmpeg, and the Castle CLI. 

### Usage

Once fully set up, run `castletool` and follow the instructions. 

### FAQ

Q: It says I don't have any decks, what do I do?
A: You can initialize a deck by running `castle init <name>` or get a pre-existing one by running `castle get-deck <id> folder`

Q: Why does it say "nothing to do"?
A: You either forgot to install pillow ffmpeg and mido, or you said no to all the prompts.

Q: What does quantizing mean?
A: Quantizing automatically makes your image use less data, but it may look worse if the value is too low.

Q: What does it mean by "frame split"? 
A: It divides your frames by the value you input. For example, if you enter "2", you will get half the frames.

Q: What does "Memory Access Out of Bounds" mean?
A: That means the image or MIDI file you input caused your deck to exceed castle's 10MB limit. You need to quantize it or use less frames.

Q: Why does it say I don't have any decks?
A: You are probably running the command while in a different directory. `cd` into where your deck is (probably `~/decks`)
