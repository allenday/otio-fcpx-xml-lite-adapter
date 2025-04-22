# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import opentimelineio as otio
from fractions import Fraction

# --- Time Parsing Utilities --- #

def _parse_fcpx_time(time_str):
    """Parses FCPX time strings like '1001/1000s', '10s', '0s'."""
    if not time_str:
        return None
    if 's' not in time_str:
         raise ValueError(f"Invalid FCPX time format (missing 's'): {time_str}")

    time_str = time_str.replace('s', '')
    if '/' in time_str:
        num, den = map(int, time_str.split('/'))
        return Fraction(num, den)
    else:
        return Fraction(time_str)

def _to_rational_time(fractional_seconds, rate):
    """Converts fractional seconds (Fraction object) to otio.RationalTime."""
    if fractional_seconds is None:
        return otio.opentime.RationalTime(0, rate)

    frame_duration_frac = Fraction(1, int(rate))
    value_frac = fractional_seconds / frame_duration_frac
    value_frames = int(round(value_frac))
    return otio.opentime.RationalTime(value_frames, rate)

# --- Time Formatting Utility --- #

def _fcpx_time_str(rational_time):
    """Converts otio.RationalTime to FCPX time string 'N/Ds'."""
    if rational_time is None:
        return "0s"

    try:
        # Ensure value and rate are treated as potentially having limited precision
        # Use as_integer_ratio() for precise conversion if floats are exact representations
        value_num, value_den = rational_time.value.as_integer_ratio()
        rate_num, rate_den = rational_time.rate.as_integer_ratio()

        total_seconds_num = value_num * rate_den
        total_seconds_den = value_den * rate_num

        # Avoid division by zero if rate is somehow zero
        if total_seconds_den == 0:
            print(f"Warning: Zero rate encountered for RationalTime {rational_time}. Returning '0s'.")
            return "0s"

        total_seconds = Fraction(total_seconds_num, total_seconds_den).limit_denominator()

        num = total_seconds.numerator
        den = total_seconds.denominator

        if den == 1:
            return f"{num}s"
        elif num == 0: # Handle zero time explicitly
            return "0s"
        else:
            return f"{num}/{den}s"
    except Exception as e:
        print(f"Error converting RationalTime {rational_time} to FCPX string: {e}. Returning '0s'.")
        return "0s" 