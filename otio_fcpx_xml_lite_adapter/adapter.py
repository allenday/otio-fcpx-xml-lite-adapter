# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import opentimelineio as otio
import xml.etree.ElementTree as ET
import re
from fractions import Fraction
import os
import xml.dom.minidom # Added for pretty printing
import logging

# Import shared utilities
from otio_fcpx_xml_lite_adapter.utils import _fcpx_time_str, _parse_fcpx_time, _to_rational_time
# Import the writer class
from otio_fcpx_xml_lite_adapter.writer import FcpXmlWriter
# Import the reader class
from otio_fcpx_xml_lite_adapter.reader import FcpXmlReader

logger = logging.getLogger(__name__)

# --- Time Parsing Utilities ---

# REMOVED - Moved to utils.py

# --- Time Formatting Utility ---

# REMOVED - Moved to utils.py

# --- FCPXML Parsing Logic (Simplified) ---

def read_from_string(input_str):
    """Reads an FCPX XML string and returns an OTIO Timeline using FcpXmlReader."""
    try:
        reader = FcpXmlReader(input_str)
        return reader.build_timeline()
    except Exception as e:
        # Catch errors during reader initialization or building
        # print(f"Error during FcpXmlReader process: {type(e).__name__} - {e}")
        logger.error(f"Error during FcpXmlReader process: {type(e).__name__} - {e}", exc_info=True)
        # Re-raise as OTIOError or handle appropriately
        raise otio.exceptions.OTIOError(f"Failed to parse FCPXML: {e}")

def read_from_file(filepath):
    """Reads an FCPX XML file and returns an OTIO Timeline."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # Use the simplified read_from_string which now uses the reader class
            return read_from_string(f.read())
    except FileNotFoundError:
        raise otio.exceptions.OTIOError(f"File not found: {filepath}")
    except Exception as e:
        # Catch file reading errors or errors from the reader process
        raise otio.exceptions.OTIOError(f"Error reading file {filepath}: {type(e).__name__} - {e}")

# --- FCPXML Writing Logic (Simplified) ---

def write_to_string(input_otio):
    """Writes an OTIO Timeline to an FCPX XML string using FcpXmlWriter."""
    try:
        writer = FcpXmlWriter(input_otio)
        return writer.build_xml_string()
    except Exception as e:
        # Catch errors during writer initialization or building
        # print(f"Error during FcpXmlWriter process: {type(e).__name__} - {e}")
        logger.error(f"Error during FcpXmlWriter process: {type(e).__name__} - {e}", exc_info=True)
        # Re-raise as OTIOError or handle appropriately
        raise otio.exceptions.OTIOError(f"Failed to generate FCPXML: {e}")

def write_to_file(input_otio, filepath):
    """Writes an OTIO object to an FCPX XML file."""
    try:
        # Get the final XML string from write_to_string (which now uses the writer)
        final_xml_string = write_to_string(input_otio)

        # Ensure output directory exists
        output_dir = os.path.dirname(filepath)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Write the string to the file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_xml_string)

    except Exception as e:
        # Catch errors during string generation or writing
        raise otio.exceptions.OTIOError(f"Error writing file {filepath}: {type(e).__name__} - {e}")

# Optional: Plugin manifest
# def plugin_manifest(): ...

# ... (Keep read_from_file, write_to_string, write_to_file placeholders) ...

# ... (Keep read_from_file placeholder) ...

# ... (Keep write_to_file placeholder) ...

# ... (Keep plugin_manifest placeholder) ... 