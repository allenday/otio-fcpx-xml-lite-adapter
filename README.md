# otio-fcpx-xml-lite-adapter

OpenTimelineIO adapter for basic Final Cut Pro X XML (.fcpxml) support.

## Status

Work in progress.

## Installation

```bash
pip install -e .
```

## Usage

```python
import opentimelineio as otio

# Read
timeline = otio.adapters.read_from_file("your_sequence.fcpxml")

# Write
otio.adapters.write_to_file(timeline, "output.fcpxml")
``` 