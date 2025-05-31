# otio-fcpx-xml-lite-adapter

[![PyPI version](https://badge.fury.io/py/otio-fcpx-xml-lite-adapter.svg)](https://badge.fury.io/py/otio-fcpx-xml-lite-adapter) <!-- Placeholder - Update if published -->
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://github.com/allenday/otio-fcpx-xml-lite-adapter/actions/workflows/test.yml/badge.svg)](https://github.com/allenday/otio-fcpx-xml-lite-adapter/actions/workflows/test.yml) <!-- Placeholder - Update if using GH Actions -->

An [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) adapter for converting between OTIO timelines and a simplified interpretation of Final Cut Pro X XML (`.fcpxml`), focusing on marker and basic structure round-tripping.

## Overview

This adapter provides basic read and write capabilities for FCPXML files (tested primarily with v1.9 and v1.13 structures), allowing interchange with OTIO. It is designed to be "lite", meaning it handles core timeline structures, clips, and markers but may not support all advanced FCPXML features.

Its development has focused on specific use cases, such as:
*   Transferring marker data (e.g., beat markers from JSON) onto placeholder clips within an FCPXML structure.
*   Round-tripping timelines with basic audio/video clips and markers.

## Features

*   **Reader:**
    *   Parses FCPXML v1.9+ (tested with v1.13).
    *   Reads `<sequence>`, `<spine>`, `<gap>`, `<asset-clip>`, `<video>` (as placeholders), and `<marker>` elements.
    *   Handles basic resources (`<format>`, `<asset>`, `<effect>`).
    *   Interprets lanes for track mapping.
    *   Creates OTIO `Timeline`, `Track`, `Clip`, `Gap`, `Marker`, `ExternalReference`, and `GeneratorReference` objects.
*   **Writer:**
    *   Generates FCPXML v1.9 structure.
    *   Writes OTIO `Timeline`, `Track` (Video/Audio), `Clip`, `Gap`, `Marker`.
    *   Maps OTIO tracks to FCPXML lanes.
    *   Handles `ExternalReference` (creating `<asset-clip>`) and `GeneratorReference` (creating `<video>` or `<title>` placeholders using `<effect>` resources).
    *   Supports placing markers on clips.
    *   Includes logic for time quantization.
    *   Creates necessary `<resources>` (format, asset, effect).
*   **Utilities:** Includes functions for parsing and formatting FCPXML time strings (`N/Ds`).
*   **Diagnostics:** Uses Python's `logging` module.

## Limitations

*   **Lite Scope:** This adapter intentionally does not aim to support the full FCPXML specification. Features like complex effects, transitions, audio adjustments beyond basic roles, multicam clips, detailed metadata mapping, etc., are likely **not** supported or may be handled in a simplified manner.
*   **Simplifying Assumptions:** The reader and writer might make assumptions about the structure (e.g., expecting a main container gap in the spine for writing).
*   **Metadata:** Minimal metadata transfer beyond basic names and resource links.

## Installation

You can install the adapter from PyPI (if published):

```bash
pip install otio-fcpx-xml-lite-adapter
```

Or, for development, clone the repository and install in editable mode:

```bash
git clone https://github.com/allenday/otio-fcpx-xml-lite-adapter.git
cd otio-fcpx-xml-lite-adapter
pip install -e .
```

## Usage

Use the adapter like any other standard OTIO adapter via the `opentimelineio.adapters` module. The adapter name is `otio_fcpx_xml_lite_adapter`.

```python
import opentimelineio as otio

# --- Reading ---
try:
    # Specify the adapter name if it's not automatically detected
    timeline = otio.adapters.read_from_file(
        "input_sequence.fcpxml",
        adapter_name="otio_fcpx_xml_lite_adapter"
    )
    print(f"Successfully read timeline: {timeline.name}")
    # ... process the timeline ...

except otio.exceptions.OTIOError as e:
    print(f"Error reading FCPXML: {e}")

# --- Writing ---
# Assume 'my_timeline' is an existing otio.schema.Timeline object
output_path = "output_sequence.fcpxml"
try:
    otio.adapters.write_to_file(
        my_timeline,
        output_path,
        adapter_name="otio_fcpx_xml_lite_adapter"
    )
    print(f"Successfully wrote timeline to: {output_path}")

except otio.exceptions.OTIOError as e:
    print(f"Error writing FCPXML: {e}")

# --- Reading/Writing Strings ---
# fcpxml_string = otio.adapters.write_to_string(my_timeline, adapter_name="otio_fcpx_xml_lite_adapter")
# timeline_from_string = otio.adapters.read_from_string(fcpxml_string, adapter_name="otio_fcpx_xml_lite_adapter")
```

*Note: Explicitly specifying `adapter_name="otio_fcpx_xml_lite_adapter"` might be necessary if the default OTIO plugin loading doesn't pick it up automatically or if other FCPXML adapters are present.*

## Development

### Setup

1.  Clone the repository.
2.  Create and activate a virtual environment (recommended).
3.  Install in editable mode with test dependencies:
    ```bash
    pip install -e .[dev]
    ```
    *(Note: Define `[dev]` extras in `pyproject.toml` if needed for test dependencies like `pytest`)*

### Running Tests

Tests are written using `unittest` and can be run with `pytest`:

```bash
pytest
```

Or run specific files:

```bash
pytest tests/test_writer.py
pytest tests/test_roundtrip.py
```

## Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

# Check Video Range Utility

This script checks if a video URL properly supports HTTP Range Requests and 
attempts to extract basic metadata and determine if the MOOV atom (index)
is located at the beginning of the file (required for efficient web seeking).

## Requirements

*   Python 3.x
*   Libraries: `requests`, `hachoir`

Install requirements:
```bash
pip install -r requirements.txt
```

## Usage

```bash
python check_video_range.py <video_url> [options]
```

**Arguments:**

*   `video_url`: (Required) The full URL of the video file to check.

**Options:**

*   `-b BYTES`, `--bytes BYTES`: Number of initial bytes to download and analyze. 
    Defaults to 4194304 (4MB). Choose a value large enough to likely contain
    the MOOV atom if it's at the start, but small enough for a quick check.
*   `-t TIMEOUT`, `--timeout TIMEOUT`: Request timeout in seconds.
    Defaults to 15 seconds.
*   `-h`, `--help`: Show help message.

## Example

```bash
# Check a file, fetching the first 2MB
python check_video_range.py "https://example.com/my_video.mp4" --bytes 2097152

# Check a file with default settings (4MB)
python check_video_range.py "https://storage.pmvhaven.com/path/to/video.mp4"
```

## Interpreting Output

1.  **Range Request Analysis:**
    *   `HONORED`: The server responded with `206 Partial Content` and correct `Content-Range`/`Content-Length` headers. This is **good**. 
    *   `NOT HONORED`: The server responded with `200 OK` (sending the whole file) or the `206` headers were incorrect/missing. This indicates a problem with the server configuration or the specific file handling for range requests. Seeking will likely **fail** or be inefficient.
    *   `FAILED`: A network error or timeout occurred.

2.  **Metadata & MOOV Atom Analysis:**
    *   Shows basic metadata extracted by Hachoir (if parsing is successful).
    *   Reports if `ftyp` (file type) and `moov` (movie metadata/index) atom signatures were found within the downloaded chunk.

3.  **MOOV Atom Summary:**
    *   `LIKELY AT START`: Found `moov` signature near the beginning. The file is **likely optimized** for web streaming/seeking.
    *   `LIKELY AT END or MISSING`: Did not find `moov` signature in the initial chunk. The file **likely needs optimization** (e.g., using `ffmpeg -movflags +faststart`) for efficient web seeking.
    *   `Unknown`: Could not determine due to errors or missing data.

**Note:** Finding the `moov` signature is a strong indicator, but not absolute proof without fully parsing the file structure. However, its absence in the first few MB is a very common reason for seeking failures. 